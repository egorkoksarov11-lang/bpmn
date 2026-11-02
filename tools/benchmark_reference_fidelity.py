"""Compare output to the actual supplied human DI as well as a prior engine.

All per-model regressions remain visible. Fixed document anchors are selected
once from source semantics and geometry; output cannot choose a closer owner.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from statistics import median
import argparse,hashlib,json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_refkit.model import read_bpmn
from bpmn_v23.pipeline import geometry,validate_xml
from bpmn_v23.quality import score
from bpmn_v23.reference_metrics import features
from bpmn_v23.document_layout import owners_for,attachment_metrics


def measure(path,owners):
    m=read_bpmn(path);nodes,seq,assocs,docs=m[4:8];boxes,paths=m[-2:];g=geometry(path)
    flows=score({i:paths[i] for i,_,_,_ in seq},{i:(u,v) for i,u,v,_ in seq})
    allq=score(paths,{i:(u,v) for i,u,v,_ in seq+assocs});a=attachment_metrics(nodes,docs,assocs,boxes,paths,owners)
    return {'contacts':allq[0],'sequence_contacts':flows[0],'sequence_bends':flows[1],'sequence_length':flows[2],
            'association_bends':a['association_bends'],'association_length':a['association_length'],
            'mean_anchor_gap':a['mean_anchor_gap'],'anchor_gaps':a['anchor_gaps'],
            'extent_area':g['extent']['width']*g['extent']['height'],
            'straight_fraction':features(path)['straight_fraction'],
            **{k:g['readability'][k] for k in ('forward_hop_excess','parallel_crowding_per_flow','hotspot_excess')},
            'hard_geometry':g['routing_safety_passed'] and g['edge_clearance_passed'] and not(g['label_collision_pairs'] or g['label_line_cuts'] or g['task_text_overflows'] or g['excessive_bend_edges'])}


METRICS=('contacts','sequence_contacts','sequence_bends','sequence_length','association_bends','association_length','mean_anchor_gap','extent_area','forward_hop_excess','parallel_crowding_per_flow','hotspot_excess')


def comparison(rows,key):
    pairs=[r for r in rows if r['status']=='success' and key in r];out={'paired_count':len(pairs),'metrics':{}}
    for metric in METRICS:
        before=sum(r[key][metric] for r in pairs);after=sum(r['after'][metric] for r in pairs)
        out['metrics'][metric]={'before_sum':before,'after_sum':after,'change_percent':100*(after/before-1) if before else None,
            'before_median':median([r[key][metric] for r in pairs]) if pairs else None,'after_median':median([r['after'][metric] for r in pairs]) if pairs else None,
            'regressions':[r['id'] for r in pairs if r['after'][metric]>r[key][metric]+.05]}
    out['all_metrics_nonregressing']=[r['id'] for r in pairs if all(r['after'][m]<=r[key][m]+.05 for m in METRICS)]
    return out


def main():
    p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--incumbent-dir',type=Path)
    p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--candidate-timeout',type=int,default=4);p.add_argument('--model-timeout',type=int,default=65);p.add_argument('--workers',type=int,default=2)
    p.add_argument('--layout-engine',choices=['reference','attachments','scratch','scratch-human'],default='reference')
    p.add_argument('--refine-only',action='store_true')
    a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
    if a.layout_engine.startswith('scratch') and (a.incumbent_dir or a.refine_only):p.error('Scratch trials forbid external incumbents and refinement-only mode')
    def one(source):
        row={'id':source.stem,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
        try:validate_xml(source)
        except Exception as e:return {**row,'status':'rejected_input','reason':str(e)}
        m=read_bpmn(source);owners=owners_for(m[4],m[7],m[6],m[-2]);row['manual']=measure(source,owners);row['fixed_owners']=owners
        dest=a.output_dir/source.stem;dest.mkdir(exist_ok=True)
        cmd=[sys.executable,str(ROOT/'run_v23.py'),'--input',str(source),'--output-dir',str(dest),'--layout-engine',a.layout_engine,'--candidate-timeout',str(a.candidate_timeout)]
        if a.incumbent_dir:
            inc=a.incumbent_dir/source.stem/'process_08_v23.bpmn'
            if inc.exists():cmd.extend(['--incumbent',str(inc)]);row['previous']=measure(inc,owners)
        if a.refine_only and '--incumbent' in cmd:cmd.append('--refine-only')
        started=time.monotonic()
        try:
            proc=subprocess.run(cmd,capture_output=True,text=True,timeout=a.model_timeout);(dest/'private_log.txt').write_text(proc.stdout+proc.stderr)
            row['status']='success' if proc.returncode==0 else 'failed'
            if proc.returncode:row['reason']=proc.stderr[-2000:]
            else:
                row['after']=measure(dest/'process_08_v23.bpmn',owners)
                row['freeze']=json.loads((dest/'semantic_diff.json').read_text())['equal']
                if a.layout_engine.startswith('scratch'):
                    backend_report=json.loads((dest/'run_report.json').read_text())['backend_report'];row['geometry_erasure']=backend_report['geometry_erasure'];row['from_scratch']=backend_report['from_scratch']
                    assert row['from_scratch'] and not any(row['geometry_erasure'][k] for k in ('source_positions_used','source_dimensions_used','source_waypoints_used','source_label_bounds_used','external_incumbent_used'))
        except subprocess.TimeoutExpired:row['status']='timeout'
        row['seconds']=round(time.monotonic()-started,3)
        if hashlib.sha256(source.read_bytes()).hexdigest()!=row['source_sha256']:raise RuntimeError('Input changed')
        return row
    rows=[]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(one,s) for s in sorted(a.input_dir.glob('*.bpmn'))]):
            row=f.result();rows.append(row);print(row['id'],row['status'],flush=True)
            (a.output_dir/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    report={'protocol':{'engine':a.layout_engine,'candidate_seconds':a.candidate_timeout,'model_seconds':a.model_timeout,'workers':a.workers,'manual_is_current_input':True,'interpretation':'source-DI stability and refinement; not coordinate-free reconstruction or a visual similarity percentage','fixed_document_anchors':True,'unsupported_inputs_are_included':True},
        'results':sorted(rows,key=lambda r:r['id']),'versus_manual':comparison(rows,'manual'),'versus_previous':comparison(rows,'previous')}
    if a.layout_engine.startswith('scratch'):report['protocol'].update(source_geometry_used=False,external_incumbent_used=False,interpretation='complete input DI erasure before reconstruction; original reference used only after layout for assessment; no visual similarity percentage')
    (a.output_dir/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
