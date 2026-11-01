"""Geometry regressions for the complete task/decision interface."""
from copy import deepcopy
from bpmn_v23.decision_layout import reflow,orient,_valid


def fixture():
    nodes={'a':{'kind':'task'},'g':{'kind':'exclusiveGateway'},'b':{'kind':'task'},'c':{'kind':'task'}}
    docs={'d':{'kind':'dataObjectReference'}};members={'a':'l1','g':'l1','b':'l1','c':'l2'}
    boxes={'l1':(0,0,900,500),'l2':(0,500,900,200),'a':(100,80,200,80),'g':(330,95,50,50),'b':(100,300,200,80),'c':(100,550,200,80),'d':(100,215,40,50)}
    report={'pairs':{'a':'g'},'slots':{'a':[0,0],'b':[0,1],'c':[0,0]},'role_order':['l1','l2'],'document_owners':{'d':'a'}}
    return nodes,docs,members,boxes,report


def test_top_orientation_reflows_following_rows_lanes_and_document_bay():
    nodes,docs,members,boxes,report=fixture();old=deepcopy((nodes,docs,members,boxes,report))
    result=reflow(boxes,report,{'a':'top'},nodes,docs,members)
    assert result['a']==(100,156,200,80) and result['g']==(175,80,50,50)
    assert result['b'][1]==376 and result['l2'][1]==576 and result['c'][1]==626
    assert result['d'][1]==291 and result['l1'][3]==576
    assert (nodes,docs,members,boxes,report)==old
    assert _valid(result,nodes,docs,members)


def test_left_orientation_keeps_original_node_sizes_and_roles():
    nodes,docs,members,boxes,report=fixture();result=reflow(boxes,report,{'a':'left'},nodes,docs,members)
    assert result['a']==(180,80,200,80) and result['g']==(100,95,50,50)
    assert all(result[n][2:]==boxes[n][2:] for n in nodes|docs)
    assert members=={'a':'l1','g':'l1','b':'l1','c':'l2'}


def test_bay_expansion_is_shared_by_all_vertical_pairs_in_one_row():
    nodes,docs,members,boxes,report=fixture()
    nodes['a2']={'kind':'task'};nodes['g2']={'kind':'exclusiveGateway'};members.update(a2='l1',g2='l1');boxes.update(a2=(500,80,200,80),g2=(730,95,50,50));report['pairs']['a2']='g2';report['slots']['a2']=[1,0]
    result=reflow(boxes,report,{'a':'top','a2':'bottom'},nodes,docs,members)
    assert result['l1'][3]==576 and result['b'][1]==376  # one row reserve, not two
    assert result['g2']==(575,186,50,50)


def test_joint_orientation_preserves_all_inputs_and_outputs_and_is_deterministic():
    nodes,docs,members,boxes,report=fixture();seq=[('in','c','a',''),('internal','a','g',''),('yes','g','b','Да'),('no','g','c','Нет')];assocs=[('document','d','a','One')]
    before=deepcopy((nodes,docs,members,boxes,report,seq,assocs))
    a,ra=orient(boxes,report,nodes,docs,seq,assocs,members);b,rb=orient(boxes,report,nodes,docs,seq,assocs,members)
    assert a==b and ra==rb and _valid(a,nodes,docs,members)
    assert set(a)==set(boxes) and (nodes,docs,members,boxes,report,seq,assocs)==before

def test_orientation_search_does_not_make_a_tall_layout_even_taller():
    from bpmn_v23.reference_style import profile
    nodes,docs,members,boxes,report=fixture()
    seq=[('in','c','a',''),('internal','a','g',''),('yes','g','b','Да'),('no','g','c','Нет')]
    def aspect(bs):
        ss=[bs[n] for n in nodes|docs];return (max(b[0]+b[2] for b in ss)-min(b[0] for b in ss))/(max(b[1]+b[3] for b in ss)-min(b[1] for b in ss))
    result,info=orient(boxes,report,nodes,docs,seq,[],members)
    assert aspect(result)+1e-5>=min(aspect(boxes),profile()['aspect_ratio_p10'])


def _two_tasks(path):
    path.write_text('''<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bd="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="defs" targetNamespace="test"><process id="p"><laneSet id="ls"><lane id="l" name="Role"><flowNodeRef>a</flowNodeRef><flowNodeRef>b</flowNodeRef></lane></laneSet><task id="a" name="A"/><task id="b" name="B"/><sequenceFlow id="f" sourceRef="a" targetRef="b"/></process><bd:BPMNDiagram id="d"><bd:BPMNPlane id="plane" bpmnElement="p"><bd:BPMNShape id="sl" bpmnElement="l"><dc:Bounds x="0" y="0" width="900" height="200"/></bd:BPMNShape><bd:BPMNShape id="sa" bpmnElement="a"><dc:Bounds x="100" y="80" width="180" height="80"/></bd:BPMNShape><bd:BPMNShape id="sb" bpmnElement="b"><dc:Bounds x="450" y="80" width="180" height="80"/></bd:BPMNShape><bd:BPMNEdge id="ef" bpmnElement="f"><di:waypoint x="280" y="120"/><di:waypoint x="450" y="120"/></bd:BPMNEdge></bd:BPMNPlane></bd:BPMNDiagram></definitions>''')


def test_verified_incumbent_survives_when_no_new_candidate_completes(tmp_path,monkeypatch):
    import bpmn_v23.human_search as search
    from bpmn_universal.contract import semantic_equality
    from bpmn_v23.freeze import equal
    source=tmp_path/'source.bpmn';_two_tasks(source);before=source.read_bytes()
    monkeypatch.setattr(search,'proposals',lambda *args,**kwargs:iter(()))
    output=tmp_path/'out.bpmn';svg=tmp_path/'out.svg';r=search.HumanStyleBackend(incumbent=source).layout(source,output,svg)
    assert r['selected_candidate']=='verified-incumbent' and source.read_bytes()==before
    assert semantic_equality(source,output) and equal(source,output) and svg.exists()


def test_incumbent_with_other_business_semantics_is_rejected(tmp_path,monkeypatch):
    import pytest
    from lxml import etree as ET
    import bpmn_v23.human_search as search
    source=tmp_path/'source.bpmn';_two_tasks(source);inc=tmp_path/'other.bpmn';tree=ET.parse(str(source));tree.xpath('//*[@id="a"]')[0].set('name','Different');tree.write(str(inc))
    monkeypatch.setattr(search,'proposals',lambda *args,**kwargs:iter(()))
    with pytest.raises(ValueError,match='Incumbent freeze'):search.HumanStyleBackend(incumbent=inc).layout(source,tmp_path/'out.bpmn',tmp_path/'out.svg')


def test_incumbent_with_invalid_edge_geometry_is_rejected(tmp_path,monkeypatch):
    import pytest
    from lxml import etree as ET
    import bpmn_v23.human_search as search
    source=tmp_path/'source.bpmn';_two_tasks(source);inc=tmp_path/'unsafe.bpmn';tree=ET.parse(str(source));tree.xpath('//*[local-name()="waypoint"]')[0].set('x','110');tree.write(str(inc))
    monkeypatch.setattr(search,'proposals',lambda *args,**kwargs:iter(()))
    with pytest.raises(ValueError,match='Incumbent readability or routing'):search.HumanStyleBackend(incumbent=inc).layout(source,tmp_path/'out.bpmn',tmp_path/'out.svg')
