from pathlib import Path
import json,shutil
import pytest
from lxml import etree as ET
from bpmn_refkit.model import read_bpmn
from bpmn_universal.contract import NS,semantic_equality
from bpmn_v23.freeze import equal
from bpmn_v23.scratch_layout import erase_geometry,ScratchBackend

ROOT=Path(__file__).resolve().parents[1]


def scrambled(source,target):
    tree=ET.parse(str(source))
    for index,b in enumerate(tree.xpath('.//dc:Bounds',namespaces=NS)):
        for key,value in zip(('x','y','width','height'),(20000-index*123,10000+index*55,900+index*17,300+index*3)):b.set(key,str(value))
    for index,p in enumerate(tree.xpath('.//di:waypoint',namespaces=NS)):p.set('x',str(-10000+index*211));p.set('y',str(6000-index*41))
    tree.write(str(target),encoding='utf-8',xml_declaration=True)


def test_neutral_input_is_identical_despite_completely_different_source_di(tmp_path):
    source=ROOT/'examples/benchmarks/r8/ref_11/after.bpmn';other=tmp_path/'scrambled.bpmn';scrambled(source,other)
    a=tmp_path/'a.bpmn';b=tmp_path/'b.bpmn';before=source.read_bytes()
    erasure=erase_geometry(source,a);erase_geometry(other,b)
    ma,mb=read_bpmn(a),read_bpmn(b)
    assert ma[-2]==mb[-2] and ma[-1]==mb[-1]
    assert not ma[1].xpath('.//bd:BPMNLabel',namespaces=NS)
    assert semantic_equality(source,a) and equal(source,a)
    assert source.read_bytes()==before
    assert {(b[0]+b[2]/2,b[1]+b[3]/2) for n,b in ma[-2].items() if n in ma[4]}=={(200,200)}
    assert not any(erasure[k] for k in ('source_positions_used','source_dimensions_used','source_waypoints_used','source_label_bounds_used','external_incumbent_used'))


@pytest.mark.skipif(not shutil.which('node') or not (ROOT/'node_modules/elkjs/lib/elk.bundled.js').exists(),reason='npm ci installs the optional ELK dependency')
def test_actual_reconstruction_is_invariant_to_all_original_coordinates(tmp_path):
    from bpmn_v23.pipeline import run,geometry
    source=ROOT/'tests/fixtures/straight_pair.bpmn';other=tmp_path/'scrambled.bpmn';scrambled(source,other)
    run(source,tmp_path/'original',ScratchBackend(candidate_seconds=3))
    run(other,tmp_path/'scrambled',ScratchBackend(candidate_seconds=3))
    a=tmp_path/'original/process_08_v23.bpmn';b=tmp_path/'scrambled/process_08_v23.bpmn';ma,mb=read_bpmn(a),read_bpmn(b)
    assert ma[-2]==mb[-2] and ma[-1]==mb[-1]
    assert semantic_equality(source,a) and semantic_equality(other,b)
    for folder in ('original','scrambled'):
        report=json.loads((tmp_path/folder/'run_report.json').read_text())['backend_report']
        assert report['from_scratch'] and report['geometry_erasure']['source_positions_used'] is False
    assert not geometry(a)['missing_named_flow_labels']


def test_document_dependency_orders_independent_scenarios_without_adding_flows():
    from copy import deepcopy
    from bpmn_v23.scratch_layout import independent_scenarios
    nodes={'reader':{'kind':'task','name':'1. Проверить полученный документ'},'writer':{'kind':'task','name':'9. Создать документ'},'other':{'kind':'task','name':'10. Завершить'}}
    docs={'d':{'kind':'dataObjectReference'}};seq=[];assocs=[('a','writer','d','Output'),('b','d','reader','Input')]
    before=deepcopy((nodes,docs,seq,assocs));components,deps=independent_scenarios(nodes,seq,docs,assocs)
    index={n:i for i,c in enumerate(components) for n in c}
    assert index['writer']<index['reader'] and deps
    assert (nodes,docs,seq,assocs)==before


def test_productive_spine_continues_through_actions_instead_of_early_exit(tmp_path):
    from bpmn_v23.patterns import analyze
    from bpmn_v23.readability import graph_returns
    from bpmn_v23.semantic_spines import align_spines
    source=ROOT/'examples/benchmarks/r8/ref_11/after.bpmn';neutral=tmp_path/'neutral.bpmn';erase_geometry(source,neutral);m=read_bpmn(neutral)
    returns=graph_returns(m[4],m[5]);motifs=analyze(m[4],[e for e in m[5] if e[0] not in returns],m[8],m[-2])
    boxes,report=align_spines(m[-2],motifs,m[4],m[5],m[8],{n:n for n in m[4]})
    main=['Start_Update','Task_CheckNeed','Gateway_Include','Task_UpdateFile','Task_CheckCompleteness','Gateway_Complete','End_Updated']
    assert any(r['main_path']==main for r in report)
    assert len({boxes[n][1]+boxes[n][3]/2 for n in main})==1
    assert all(boxes[a][0]+boxes[a][2]+24<=boxes[b][0]+.01 for a,b in zip(main,main[1:]))
    assert boxes['End_NoUpdate'][0]+boxes['End_NoUpdate'][2]/2==boxes['Gateway_Include'][0]+boxes['Gateway_Include'][2]/2


def test_skyline_shares_free_vertical_bays_only_in_disjoint_columns():
    from bpmn_v23.skyline_layout import compact_rows
    nodes={'a':{'kind':'task'},'b':{'kind':'task'}};docs={'d1':{},'d2':{}}
    boxes={'a':(100,100,100,60),'d1':(100,180,36,50),'b':(400,400,100,60),'d2':(400,300,36,50),'lane':(30,65,600,600)}
    report={'document_owners':{'d1':'a','d2':'b'},'axis_rows':{'a':['lane',0],'b':['lane',1]},'reserved_captions':{},'mapped_axes':{'x':[],'y':[[130,130],[430,430]]}}
    result,info=compact_rows(boxes,report,nodes,docs,{'a':'lane','b':'lane'},{'lane':'role'},[])
    assert result['b'][1]-result['a'][1]<200
    assert result['d1'][1]-result['a'][1]==80 and result['d2'][1]-result['b'][1]==-100
    assert info['row_skyline']['new_lane_height']<info['row_skyline']['old_lane_height']


@pytest.mark.skipif(not shutil.which('node') or not (ROOT/'node_modules/elkjs/lib/elk.bundled.js').exists(),reason='npm ci installs ELK')
def test_default_pipeline_audits_reference_geometry_only_after_reconstruction(tmp_path,monkeypatch):
    import bpmn_v23.pipeline as pipeline
    source=ROOT/'tests/fixtures/straight_pair.bpmn';events=[];actual_layout=ScratchBackend.layout;actual_geometry=pipeline.geometry
    def layout(self,*args):
        result=actual_layout(self,*args);events.append('reconstruction_complete');return result
    def geometry(path):
        if Path(path).resolve()==source.resolve():events.append('reference_audit')
        return actual_geometry(path)
    monkeypatch.setattr(ScratchBackend,'layout',layout);monkeypatch.setattr(pipeline,'geometry',geometry)
    pipeline.run(source,tmp_path/'default')
    report=json.loads((tmp_path/'default/run_report.json').read_text())
    assert report['backend']=='v23-from-scratch' and report['backend_report']['from_scratch']
    assert events.index('reconstruction_complete')<events.index('reference_audit')
