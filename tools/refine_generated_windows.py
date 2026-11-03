"""Transactional second stage on verified cold-generated outputs, never references.

Usage after benchmark_four_processes.py; the input diagrams supply only the
semantic/DI freeze contract. Existing outputs must prove coordinate erasure.
"""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sys,tempfile,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from benchmark_four_processes import evaluate
from bpmn_v23.window_planner import refine_windows
from bpmn_v23.pipeline import geometry,validate_xml
from bpmn_v23 import __version__


def refine(source,folder,seconds=45,recheck_guard=False):
    # Audit the seed before making any change; no teacher DI enters the planner.
    initial=evaluate(source,folder);started=time.monotonic();source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='verified-window-stage-',dir=folder.parent) as tmp:
        stage=Path(tmp)
        for name in ('process_08_v23.bpmn','process_08_v23.svg','run_report.json','geometry_report.json','semantic_diff.json'):
            shutil.copyfile(folder/name,stage/name)
        report=json.loads((stage/'run_report.json').read_text())
        if recheck_guard:
            from bpmn_v23.scratch_layout import erase_geometry
            from bpmn_v23.cold_guard import protect_cold_result
            neutral=stage/'erased-neutral.bpmn';erase_geometry(source,neutral)
            try:
                guard,adopted=protect_cold_result(neutral,stage/'process_08_v23.bpmn',stage/'process_08_v23.svg',candidate_seconds=60,search_seconds=200)
            finally:neutral.unlink(missing_ok=True)
            report['backend_report']['post_generation_cold_guard']=guard
            if adopted is not None:report['backend_report']['selected_candidate']=adopted['selected_candidate']
        result=refine_windows(stage/'process_08_v23.bpmn',stage/'process_08_v23.svg',source,seconds=seconds)
        validate_xml(stage/'process_08_v23.bpmn')
        report['version']=__version__
        if 'post_generation_windows' in report['backend_report']:
            report['backend_report'].setdefault('post_generation_window_history',[]).append(report['backend_report']['post_generation_windows'])
        report['backend_report']['post_generation_windows']=result
        report['backend_report']['post_generation_windows']['seed']='verified cold-generated output, not reference coordinates'
        (stage/'run_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        geo=json.loads((stage/'geometry_report.json').read_text());geo['after']=geometry(stage/'process_08_v23.bpmn')
        (stage/'geometry_report.json').write_text(json.dumps(geo,ensure_ascii=False,indent=2)+'\n')
        final=evaluate(source,stage)
        assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
        for p in stage.iterdir():os.replace(p,folder/p.name)
    return {'case':source.stem,'checks':final['checks'],'before':initial['generated'],'after':final['generated'],'staged_result':result,'seconds':round(time.monotonic()-started,3)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--results-dir',type=Path,required=True);p.add_argument('--seconds',type=float,default=45);p.add_argument('--case',action='append');p.add_argument('--recheck-cold-guard',action='store_true',help='construct a fresh graph-only alternative if dense; never use an archived layout');a=p.parse_args()
    report_path=a.results_dir/'window_stage_report.json'
    previous=json.loads(report_path.read_text()).get('results',[]) if report_path.exists() else []
    rows={r['case']:r for r in previous}
    for source in sorted(a.input_dir.glob('*.bpmn')):
        if a.case and source.stem not in a.case:continue
        row=refine(source,a.results_dir/source.stem,a.seconds,a.recheck_cold_guard);rows[source.stem]=row;print(row['case'],row['staged_result']['accepted_windows'],row['staged_result']['before'],row['staged_result']['after'],flush=True)
    report_path.write_text(json.dumps({'protocol':'extra staged pass on verified cold generation; not reconstruction from teacher DI','seconds_per_case':a.seconds,'results':[rows[k] for k in sorted(rows)]},ensure_ascii=False,indent=2)+'\n')
