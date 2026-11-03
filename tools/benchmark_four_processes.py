"""Reproduce cold generation and independent audits on user-supplied BPMN files.

Inputs stay outside the output directory. Reference geometry is read only AFTER
layout, for assessment. Reports retain failures and never equate a metric with
percentage visual similarity. Run sequentially for comparable wall-clock budgets.
"""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,time,statistics,traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_refkit.model import read_bpmn,TAG_TASK
from bpmn_universal.contract import semantic_equality
from bpmn_v23.freeze import equal
from bpmn_v23.pipeline import run,geometry
from bpmn_v23.scratch_layout import ScratchBackend,GraphChannelsBackend
from collect_scratch_results import audited_measure,correspondence,visible_names,physical_bends
from bpmn_v23.document_layout import owners_for


def measure(path,owners):
    value=audited_measure(path,owners);m=read_bpmn(path)
    taskw=statistics.median(m[-2][n][2] for n,o in m[4].items() if o['kind'] in TAG_TASK)
    value.update(task_width_median=taskw,normalized_sequence_length=value['sequence_length']/taskw,
                 sequence_bends_per_flow=value['sequence_bends']/max(1,len(m[5])))
    bends=[physical_bends(m[-1][i]) for i,*_ in m[5]]
    value['at_most_one_bend_fraction']=sum(n<=1 for n in bends)/max(1,len(bends))
    stretch=[]
    for i,u,v,_ in m[5]:
        a,b=m[-2][u],m[-2][v]
        gap=max(0,b[0]-a[0]-a[2],a[0]-b[0]-b[2])+max(0,b[1]-a[1]-a[3],a[1]-b[1]-b[3])
        if gap>=12:
            import math
            stretch.append(sum(math.dist(x,y) for x,y in zip(m[-1][i],m[-1][i][1:]))/gap)
    value['sequence_stretch_p90']=sorted(stretch)[min(len(stretch)-1,int(len(stretch)*.9))] if stretch else None
    from bpmn_v23.window_metrics import metrics as window_metrics
    value['window_readability']=window_metrics(m[-2],m[-1],m[4],m[5],m[8],m[7],m[6])
    return value


def evaluate(source,folder):
    generated=folder/'process_08_v23.bpmn';m=read_bpmn(source);out=read_bpmn(generated)
    g=geometry(generated);r=json.loads((folder/'run_report.json').read_text())
    owners=owners_for(m[4],m[7],m[6],m[-2])
    checks={'semantic_freeze':semantic_equality(source,generated),'di_identity':equal(source,generated),
            'full_visible_names':visible_names(out,generated.with_suffix('.svg')),
            'routing_safety':g['routing_safety_passed'],'object_clearance':g['edge_clearance_passed'],
            'labels_clear':not(g['label_collision_pairs'] or g['label_line_cuts'] or g['missing_named_flow_labels']),
            'task_text_fits':not g['task_text_overflows'],'bend_limit':not g['excessive_bend_edges']}
    erased=r['backend_report']['geometry_erasure']
    checks['source_geometry_erased']=not any(erased[k] for k in ('source_positions_used','source_dimensions_used','source_waypoints_used','source_label_bounds_used','external_incumbent_used','source_lane_order_used'))
    if not all(checks.values()):raise ValueError(checks)
    return {'checks':checks,'reference':measure(source,owners),'generated':measure(generated,owners),
            'correspondence':correspondence(m[4],m[5],m[-2],m[-1],out[-2],out[-1]),
            'counts':{'nodes':len(out[4]),'flows':len(out[5]),'documents':len(out[7]),'information_links':len(out[6]),'roles':len(out[9])},
            'extent':g['extent'],'selected_candidate':r['backend_report']['selected_candidate'],
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'output_sha256':hashlib.sha256(generated.read_bytes()).hexdigest()}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--candidate-timeout',type=int,default=45);p.add_argument('--search-seconds',type=int,default=240)
    p.add_argument('--legacy',action='store_true');p.add_argument('--audit-only',action='store_true')
    p.add_argument('--case',action='append',help='file stem to run; repeatable')
    args=p.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    files=sorted(args.input_dir.glob('*.bpmn'));files=[f for f in files if not args.case or f.stem in args.case]
    if not files:raise SystemExit('No BPMN inputs')
    if args.input_dir.resolve().is_relative_to(args.output_dir.resolve()):raise SystemExit('Inputs must be outside output directory')
    results=[]
    for source in files:
        folder=args.output_dir/source.stem;started=time.monotonic();before=source.read_bytes()
        row={'case':source.stem,'status':'failed'}
        try:
            if not args.audit_only:
                run(source,folder,ScratchBackend(candidate_seconds=args.candidate_timeout,search_seconds=args.search_seconds,graph_backend=GraphChannelsBackend if args.legacy else None))
            row.update(evaluate(source,folder));row['status']='verified'
        except Exception as error:
            row['error']=str(error);folder.mkdir(parents=True,exist_ok=True);(folder/'failure.txt').write_text(traceback.format_exc())
        row['input_unchanged']=source.read_bytes()==before;row['seconds']=round(time.monotonic()-started,3);results.append(row)
        report={'protocol':{'from_scratch':True,'reference_used_only_after_generation':True,'input_di_erased':True,'external_incumbent':False,
                            'candidate_timeout':args.candidate_timeout,'search_seconds':args.search_seconds,'legacy':args.legacy,
                            'successes':sum(r['status']=='verified' for r in results),'cases':len(results),
                            'interpretation':'development corpus; structural direction agreement is not percentage human similarity'},'results':results}
        (args.output_dir/'benchmark_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(source.stem,row['status'],row['seconds'],flush=True)
    return 0 if all(r['status']=='verified' and r['input_unchanged'] for r in results) else 1

if __name__=='__main__':raise SystemExit(main())
