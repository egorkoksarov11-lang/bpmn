"""Transactional graph/role finishing pass on already verified cold generation."""
from pathlib import Path
import argparse,json,os,shutil,sys,tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from benchmark_four_processes import evaluate
from bpmn_v23.graph_refinement import refine_graph
from bpmn_v23.pipeline import geometry
from bpmn_v23 import __version__


def refine(source,folder,seconds=90):
    initial=evaluate(source,folder)
    with tempfile.TemporaryDirectory(prefix='verified-graph-stage-',dir=folder.parent) as tmp:
        stage=Path(tmp)
        for name in ('process_08_v23.bpmn','process_08_v23.svg','run_report.json','geometry_report.json','semantic_diff.json'):shutil.copyfile(folder/name,stage/name)
        result=refine_graph(stage/'process_08_v23.bpmn',stage/'process_08_v23.svg',source,seconds)
        from bpmn_v23.whitespace import compact_whitespace
        result['whitespace_compaction']=compact_whitespace(stage/'process_08_v23.bpmn',stage/'process_08_v23.svg',source)
        report=json.loads((stage/'run_report.json').read_text());report['version']=__version__;report['backend_report']['post_generation_graph']=result
        (stage/'run_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        geo=json.loads((stage/'geometry_report.json').read_text());geo['after']=geometry(stage/'process_08_v23.bpmn');(stage/'geometry_report.json').write_text(json.dumps(geo,ensure_ascii=False,indent=2)+'\n')
        final=evaluate(source,stage)
        for p in stage.iterdir():os.replace(p,folder/p.name)
    return {'case':source.stem,'checks':final['checks'],'before':initial['generated'],'after':final['generated'],'graph_refinement':result}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--results-dir',type=Path,required=True);p.add_argument('--seconds',type=float,default=90);p.add_argument('--case',action='append');a=p.parse_args();rows=[]
    for source in sorted(a.input_dir.glob('*.bpmn')):
        if a.case and source.stem not in a.case:continue
        row=refine(source,a.results_dir/source.stem,a.seconds);rows.append(row);print(source.stem,row['before']['sequence_bends'],row['after']['sequence_bends'],row['before']['contacts'],row['after']['contacts'],flush=True)
    target=a.results_dir/'graph_stage_report.json'
    previous=json.loads(target.read_text()).get('results',[]) if target.exists() else []
    merged={r['case']:r for r in previous};merged.update({r['case']:r for r in rows})
    target.write_text(json.dumps({'protocol':'extra alternating optimization of verified cold outputs; reference DI excluded from planning','results':[merged[k] for k in sorted(merged)]},ensure_ascii=False,indent=2)+'\n')
