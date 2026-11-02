"""Rebuild every uploaded reference; report failures and paired metrics openly."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from collections import Counter
from statistics import median
import argparse,hashlib,json,subprocess,sys,time,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_v23.pipeline import validate_xml,geometry
from bpmn_v23.reference_metrics import features
from bpmn_refkit.model import read_bpmn
from bpmn_v23.quality import score


def measurements(path):
    parsed=read_bpmn(path);nodes,seq,assocs=parsed[4:7];boxes,paths=parsed[-2:]
    raw=score(paths,{i:(u,v) for i,u,v,_ in seq+assocs})
    flows=score({i:paths[i] for i,_,_,_ in seq},{i:(u,v) for i,u,v,_ in seq})
    g=geometry(path)
    return {'features':features(path),'contacts':raw[0],'bends':raw[1],'length':raw[2],
            'sequence_contacts':flows[0],'sequence_bends':flows[1],'sequence_length':flows[2],
            'extent':g['extent'],'extent_area':g['extent']['width']*g['extent']['height'],
            'hard_geometry':g['routing_safety_passed'] and g['edge_clearance_passed'] and not g['excessive_bend_edges'] and not g['task_text_overflows'] and not g['label_collision_pairs'] and not g['label_line_cuts']}


def summarize(results,baseline,candidate):
    a={r['id']:r for r in results if r['engine']==baseline};b={r['id']:r for r in results if r['engine']==candidate}
    ids=sorted(i for i in a.keys()&b.keys() if a[i]['status']=='success' and b[i]['status']=='success')
    summary={'paired_success_count':len(ids),'paired_ids':ids,'coverage':{e:dict(Counter(r['status'] for r in results if r['engine']==e)) for e in (baseline,candidate)},'totals':{},'per_model_median_ratios':{},'regressions':{}}
    for key in ('contacts','bends','length','sequence_contacts','sequence_bends','sequence_length','extent_area'):
        before=sum(a[i]['measurements'][key] for i in ids);after=sum(b[i]['measurements'][key] for i in ids)
        summary['totals'][key]={'baseline':before,'candidate':after,'change_percent':100*(after/before-1) if before else None}
        ratios=[b[i]['measurements'][key]/a[i]['measurements'][key] for i in ids if a[i]['measurements'][key]>0]
        summary['per_model_median_ratios'][key]=median(ratios) if ratios else None
        summary['regressions'][key]=[i for i in ids if b[i]['measurements'][key]>a[i]['measurements'][key]+.01]
    for key in ('straight_fraction','forward_hop_excess','parallel_crowding_per_flow','hotspot_excess'):
        before=[a[i]['measurements']['features'][key] for i in ids];after=[b[i]['measurements']['features'][key] for i in ids]
        summary[key]={'baseline_median':median(before) if before else None,'candidate_median':median(after) if after else None}
    summary['lost_successes']=[i for i in a.keys()&b.keys() if a[i]['status']=='success' and b[i]['status']!='success']
    summary['recovered_successes']=[i for i in a.keys()&b.keys() if a[i]['status']!='success' and b[i]['status']=='success']
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--engines',nargs='+',default=['human','adaptive'],choices=['human','axes','adaptive'])
    p.add_argument('--stage-from-baseline',action='store_true',help='seed later engines from the first engine verified result')
    p.add_argument('--candidate-timeout',type=int,default=8);p.add_argument('--model-timeout',type=int,default=65);p.add_argument('--workers',type=int,default=2)
    a=p.parse_args();out=a.output_dir.resolve()
    if out==a.archive.resolve() or out==a.archive.resolve().parent:p.error('Use a separate results directory')
    if not 1<=a.workers<=4 or not 1<=a.candidate_timeout<=600 or a.model_timeout<10:p.error('Invalid budgets')
    out.mkdir(parents=True,exist_ok=True);inputs=out/'inputs';inputs.mkdir(exist_ok=True);manifest=[]
    archive_hash=hashlib.sha256(a.archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(a.archive) as z:
        entries=[i for i in z.infolist() if i.filename.lower().endswith('.bpmn')]
        if len(entries)>512:raise ValueError('Too many models')
        for idx,item in enumerate(entries,1):
            if item.file_size>25_000_000:raise ValueError('Oversized reference')
            path=inputs/f'ref_{idx:02}.bpmn';raw=z.read(item);path.write_bytes(raw)
            row={'id':path.stem,'file':item.filename,'sha256':hashlib.sha256(raw).hexdigest()}
            try:validate_xml(path);row['input_status']='valid';row['original']=measurements(path)
            except Exception as e:row['input_status']='rejected_input';row['input_error']=str(e)
            manifest.append(row)
    def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    save(out/'manifest.json',{'archive_sha256':archive_hash,'models':manifest})
    def rebuild(row,engine):
        result={'id':row['id'],'engine':engine}
        if row['input_status']!='valid':return {**result,'status':'rejected_input','reason':row['input_error']}
        dest=out/engine/row['id'];dest.mkdir(parents=True,exist_ok=True);source=inputs/(row['id']+'.bpmn');start=time.monotonic()
        command=[sys.executable,str(ROOT/'run_v23.py'),'--input',str(source),'--output-dir',str(dest),'--layout-engine',engine,'--candidate-timeout',str(a.candidate_timeout),'--no-decision-orientations']
        if a.stage_from_baseline and engine!=a.engines[0]:
            seed=out/a.engines[0]/row['id']/'process_08_v23.bpmn'
            if seed.exists():command.extend(['--incumbent',str(seed)]);result['initialization']='verified-baseline-result'
        try:
            proc=subprocess.run(command,capture_output=True,text=True,timeout=a.model_timeout)
            (dest/'log.txt').write_text(proc.stdout+proc.stderr)
            result['status']='success' if proc.returncode==0 else 'failed'
            if proc.returncode:result['reason']=proc.stderr[-6000:].replace(str(out),'BENCHMARK')
            else:
                result['measurements']=measurements(dest/'process_08_v23.bpmn')
                semantic=json.loads((dest/'semantic_diff.json').read_text());result['semantic_diff']=semantic['diff_count'];result['DI_freeze']=semantic['di_structure_preserved']
        except subprocess.TimeoutExpired:result['status']='timeout'
        result['seconds']=round(time.monotonic()-start,3)
        if hashlib.sha256(source.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Input changed')
        save(dest/'benchmark_status.json',result);return result
    results=[]
    for engine in a.engines:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            for future in as_completed([pool.submit(rebuild,row,engine) for row in manifest]):
                result=future.result();results.append(result);save(out/'results.json',results);print(result['engine'],result['id'],result['status'],flush=True)
    report={'protocol':{'archive_sha256':archive_hash,'input_DI':'current source reading geometry; no external coordinate lookup','stage_from_baseline':a.stage_from_baseline,'baseline':'explicit human mode, decision orientations disabled','candidate_timeout':a.candidate_timeout,'model_timeout':a.model_timeout,'workers':a.workers,'note':'development regression corpus; not independent human visual validation; failures stay in the report'},'manifest':manifest,'results':results}
    if len(a.engines)>=2:report['comparison']=summarize(results,a.engines[0],a.engines[-1])
    save(out/'report.json',report)
    if hashlib.sha256(a.archive.read_bytes()).hexdigest()!=archive_hash:raise ValueError('Archive changed')


if __name__=='__main__':main()
