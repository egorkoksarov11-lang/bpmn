from copy import deepcopy
from pathlib import Path
from bpmn_v23.continuity import elbow_routes,neighbourhood,local_metrics,placement_options,ContinuityBackend
from bpmn_v23.router import route_graph
from bpmn_v23.clearance import safe_poly
from bpmn_v23.pipeline import run,geometry
from bpmn_refkit.model import read_bpmn
from bpmn_universal.contract import semantic_equality
import pytest


def test_mixed_side_ports_allow_a_single_elbow():
    boxes={'a':(0,0,200,80),'b':(0,160,90,80)};uv={'f':('a','b')}
    routes=list(elbow_routes(boxes['a'],boxes['b']))
    assert any(len(p)==3 and safe_poly('f',p,boxes,uv) for p in routes)


def test_neighbourhood_is_frozen_so_moves_cannot_hide_a_bad_link():
    nodes={n:{'kind':'task'} for n in ('a','b')};seq=[('f','a','b','')];boxes={'a':(0,0,100,80),'b':(140,100,100,80)}
    ids=neighbourhood(nodes,seq,boxes);assert ids==['f']
    far=[(100,40),(900,40),(900,200),(1000,200)]
    assert local_metrics({'f':far},ids)['two_plus_bends']==1


def test_joint_moves_are_available_and_leave_the_model_unchanged():
    boxes={'a':(0,0,100,80),'b':(130,160,100,80)};before=deepcopy(boxes)
    options=list(placement_options('a','b',boxes,{},{}))
    assert any({'a','b'}<=moved for _,moved,_ in options)
    assert boxes==before


def test_fixed_paths_survive_routing_without_mutation():
    boxes={'a':(0,0,100,80),'b':(200,0,100,80),'c':(400,0,100,80)}
    nodes={n:{'kind':'task'} for n in boxes};seq=[('f','a','b',''),('g','b','c','')]
    fixed={'f':[(100,40),(200,40)]};old={'f':fixed['f'],'g':[(300,40),(400,40)]};before=deepcopy(fixed)
    paths,_=route_graph(boxes,nodes,seq,[],{},old,fixed_paths=fixed)
    assert paths['f']==fixed['f'] and fixed==before and len(paths['g'])==2


def test_unsafe_fixed_wire_is_rejected():
    boxes={'a':(0,0,100,80),'b':(200,0,100,80),'obstacle':(140,20,20,40)}
    with pytest.raises(ValueError,match='Unsafe fixed'):
        route_graph(boxes,{'a':{'kind':'task'},'b':{'kind':'task'}},[('f','a','b','')],[],{}, {'f':[(100,40),(200,40)]},fixed_paths={'f':[(100,40),(200,40)]})


def test_refinement_cannot_move_protected_wires(monkeypatch):
    import bpmn_v23.router as router
    paths={'f':[(100,40),(300,40)],'g':[(200,-20),(200,100)]};before=deepcopy(paths)
    def forbidden(*a,**kw):raise AssertionError('A protected edge was rerouted')
    monkeypatch.setattr(router,'astar',forbidden)
    router.refine_paths({}, {'f':('a','b'),'g':('c','d')},paths,protected_ids={'f','g'})
    assert paths==before


def test_full_pipeline_straightens_a_close_successor_without_business_edits(tmp_path):
    source=tmp_path/'source.bpmn'
    source.write_text('''<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bd="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="defs" targetNamespace="test">
    <process id="p"><laneSet id="ls"><lane id="lane" name="Role"><flowNodeRef>a</flowNodeRef><flowNodeRef>b</flowNodeRef></lane></laneSet><task id="a" name="First"/><task id="b" name="Next"/><sequenceFlow id="f" sourceRef="a" targetRef="b"/></process>
    <bd:BPMNDiagram id="diagram"><bd:BPMNPlane id="plane" bpmnElement="p">
    <bd:BPMNShape id="sl" bpmnElement="lane"><dc:Bounds x="100" y="100" width="800" height="400"/></bd:BPMNShape>
    <bd:BPMNShape id="sa" bpmnElement="a"><dc:Bounds x="150" y="120" width="200" height="80"/></bd:BPMNShape>
    <bd:BPMNShape id="sb" bpmnElement="b"><dc:Bounds x="420" y="280" width="200" height="80"/></bd:BPMNShape>
    <bd:BPMNEdge id="ef" bpmnElement="f"><di:waypoint x="350" y="160"/><di:waypoint x="400" y="160"/><di:waypoint x="400" y="320"/><di:waypoint x="420" y="320"/></bd:BPMNEdge>
    </bd:BPMNPlane></bd:BPMNDiagram></definitions>''')
    before=source.read_bytes();dest=tmp_path/'out'
    run(source,dest,ContinuityBackend(incumbent=source,candidate_seconds=10))
    result=dest/'process_08_v23.bpmn'
    assert semantic_equality(source,result) and source.read_bytes()==before
    assert len(read_bpmn(result)[-1]['f'])==2
    assert geometry(result)['routing_safety_passed']
