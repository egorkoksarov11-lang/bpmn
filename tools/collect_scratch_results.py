"""Audit every cold reconstruction and compare it to control and manual DI."""
from pathlib import Path
from collections import Counter
import argparse,json,sys
from lxml import etree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from benchmark_reference_fidelity import measure,comparison
from bpmn_refkit.model import read_bpmn,TAG_TASK,TAG_GATE,TAG_EVENT
from bpmn_v23.document_layout import owners_for
from bpmn_v23.pipeline import geometry
from bpmn_v23.freeze import equal
from bpmn_universal.contract import semantic_equality


def visible_names(model,svg):
    tree=ET.parse(str(svg));nodes,seq,_,docs=model[4:8]
    for n,o in (nodes|docs).items():
        if not o.get('name'):continue
        attr='data-bpmn-id' if n in nodes and o['kind'] in TAG_TASK else 'data-label-for'
        groups=tree.xpath('//*[@'+attr+'=$id]',id=n)
        if not groups:raise ValueError('Missing visible object name: '+n)
        text=''.join(groups[0].xpath('.//*[local-name()="text"]/text()'))
        if ''.join(text.split())!=''.join(o['name'].split()):raise ValueError('Incomplete visible object name: '+n)
    for i,_,_,name in seq:
        if not name:continue
        groups=tree.xpath('//*[@data-label-for=$id]',id=i)
        if not groups or ''.join(''.join(groups[0].xpath('.//*[local-name()="text"]/text()')).split())!=''.join(name.split()):raise ValueError('Incomplete visible branch caption: '+i)
    return True


def main():
    p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--control-dir',type=Path,required=True);p.add_argument('--candidate-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    candidate=json.loads((a.candidate_dir/'report.json').read_text());control=json.loads((a.control_dir/'report.json').read_text());baseline={r['id']:r for r in control['results']};rows=candidate['results']
    for row in rows:
        identifier=row['id'];source=a.input_dir/(identifier+'.bpmn');previous=baseline[identifier];row['control_status']=previous['status']
        if row['status']=='rejected_input':continue
        original=read_bpmn(source);owners=owners_for(original[4],original[7],original[6],original[-2]);row['manual']=measure(source,owners)
        if previous['status']=='success':row['previous']=measure(a.control_dir/identifier/'process_08_v23.bpmn',owners)
        if row['status']!='success':continue
        out=a.candidate_dir/identifier/'process_08_v23.bpmn';model=read_bpmn(out);g=geometry(out)
        assert row['from_scratch'] and not any(row['geometry_erasure'][k] for k in ('source_positions_used','source_dimensions_used','source_waypoints_used','source_label_bounds_used','external_incumbent_used'))
        assert semantic_equality(source,out) and equal(source,out) and not g['missing_named_flow_labels']
        row['after']=measure(out,owners);row['full_visible_names_preserved']=visible_names(model,out.with_suffix('.svg'))
        assert row['after']['hard_geometry']
    candidate['versus_previous']=comparison(rows,'previous');candidate['versus_manual']=comparison(rows,'manual')
    candidate['coverage']={'control':dict(Counter(r['status'] for r in control['results'])),'candidate':dict(Counter(r['status'] for r in rows))}
    candidate['lost_successes']=[r['id'] for r in rows if r['control_status']=='success' and r['status']!='success']
    candidate['recovered_successes']=[r['id'] for r in rows if r['control_status']!='success' and r['status']=='success']
    candidate['protocol'].update(input_kind='from-scratch',baseline='scratch-human; input DI fully erased; no external incumbent',candidate='scratch; input DI fully erased; no external incumbent',interpretation='original references used only for assessment; all failures and per-model regressions retained; no claimed 80% visual similarity',sequential_engine_phases=True)
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(candidate,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
