from pathlib import Path
from copy import deepcopy
import pytest
from bpmn_v23.window_metrics import metrics,through_turn,windows
from bpmn_v23.window_planner import proposals,joint_routes,refine_windows
from bpmn_v23.local_editing import physical_bends


def triple():
    nodes={n:{'kind':'task','name':n} for n in 'abc'};seq=[('ab','a','b',''),('bc','b','c','')];member={n:'l' for n in nodes}
    boxes={'a':(100,100,180,76),'b':(400,100,180,76),'c':(700,100,180,76),'l':(30,65,1000,500)}
    paths={'ab':[(280,138),(400,138)],'bc':[(580,138),(700,138)]}
    return nodes,seq,member,boxes,paths


def test_return_to_requesting_role_is_not_a_spurious_task_hairpin():
    n,s,m,b,p=triple();m={'a':'requester','b':'reviewer','c':'requester'};p={'ab':[(200,176),(200,300)],'bc':[(200,300),(200,176)]}
    r=metrics(b,p,n,s,m)
    assert r['request_reply_windows']==1 and r['serial_hairpins']==0
    m={n:'same' for n in 'abc'};r=metrics(b,p,n,s,m)
    assert r['serial_hairpins']==1


def test_vertical_and_corner_windows_keep_dimensions_and_anchor():
    n,s,m,b,p=triple();w=windows(n,s)[0];before=deepcopy(b);pp=dict(proposals(w,b,m))
    assert 'vertical-down' in pp and 'right-down' in pp
    assert all('a' not in v and v['b'][2:]==b['b'][2:] and v['c'][2:]==b['c'][2:] for v in pp.values())
    assert b==before


def test_two_wires_can_be_routed_as_a_corner_without_extra_bends():
    n,s,m,b,p=triple();b['b']=(308,100,180,76);b['c']=(308,204,180,76)
    q=joint_routes(b,n,s,[],p,{'ab','bc'},('ab','bc'),{k:v for k,v in b.items() if k in n},old_boxes=b)
    assert q is not None and all(physical_bends(q[i])==0 for i in ['ab','bc'])
    assert q['ab'][-1]!=q['bc'][0]


def test_branch_windows_have_balanced_weights():
    n,s,m,b,p=triple();n['b']['kind']='exclusiveGateway';n['d']={'kind':'task','name':'d'};s.append(('bd','b','d',''))
    ww=[w for w in windows(n,s) if w['nodes'][1]=='b']
    assert len(ww)==2 and sum(w['weight'] for w in ww)==1 and not any(w['serial_task'] for w in ww)


def test_whole_window_edit_has_full_semantic_and_di_freeze(tmp_path):
    from lxml import etree as ET
    from bpmn_universal.contract import NS,semantic_equality
    from bpmn_v23.freeze import equal
    from bpmn_v23.render import render
    from bpmn_v23.pipeline import geometry
    source=tmp_path/'source.bpmn'
    source.write_text('''<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bd="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="defs" targetNamespace="test"><process id="p"><laneSet id="ls"><lane id="l" name="Role"><flowNodeRef>a</flowNodeRef><flowNodeRef>b</flowNodeRef><flowNodeRef>c</flowNodeRef></lane></laneSet><task id="a" name="First"/><task id="b" name="Second"/><task id="c" name="Third"/><sequenceFlow id="ab" sourceRef="a" targetRef="b"/><sequenceFlow id="bc" sourceRef="b" targetRef="c"/></process><bd:BPMNDiagram id="d"><bd:BPMNPlane id="plane" bpmnElement="p"><bd:BPMNShape id="sl" bpmnElement="l"><dc:Bounds x="30" y="65" width="1100" height="650"/></bd:BPMNShape><bd:BPMNShape id="sa" bpmnElement="a"><dc:Bounds x="100" y="100" width="180" height="76"/></bd:BPMNShape><bd:BPMNShape id="sb" bpmnElement="b"><dc:Bounds x="420" y="260" width="180" height="76"/></bd:BPMNShape><bd:BPMNShape id="sc" bpmnElement="c"><dc:Bounds x="750" y="420" width="180" height="76"/></bd:BPMNShape><bd:BPMNEdge id="eab" bpmnElement="ab"><di:waypoint x="280" y="138"/><di:waypoint x="350" y="138"/><di:waypoint x="350" y="298"/><di:waypoint x="420" y="298"/></bd:BPMNEdge><bd:BPMNEdge id="ebc" bpmnElement="bc"><di:waypoint x="600" y="298"/><di:waypoint x="680" y="298"/><di:waypoint x="680" y="458"/><di:waypoint x="750" y="458"/></bd:BPMNEdge></bd:BPMNPlane></bd:BPMNDiagram></definitions>''')
    output=tmp_path/'output.bpmn';output.write_bytes(source.read_bytes());svg=output.with_suffix('.svg');render(output,svg);before=source.read_bytes()
    r=refine_windows(output,svg,source,seconds=8,max_windows=2)
    assert r['accepted_windows']>0 and r['after'][1]<r['before'][1]
    assert r['after'][2]<r['before'][2]
    assert semantic_equality(source,output) and equal(source,output) and source.read_bytes()==before
    assert geometry(output)['routing_safety_passed']


def test_decision_can_turn_vertically_before_handoff_to_another_role():
    n,s,m,b,p=triple();n['b']['kind']='exclusiveGateway';m['c']='other';w=windows(n,s)[0]
    choices=list(proposals(w,b,m));vertical=[v for name,v in choices if name=='vertical-decision-handoff']
    assert vertical and any(abs(v['b'][0]+v['b'][2]/2-(b['a'][0]+b['a'][2]/2))<.01 for v in vertical)
    assert all(v['c'][1]==b['c'][1] for v in vertical)


def test_human_window_analysis_ignores_global_translation():
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
    from analyze_window_patterns import relative_edit
    n,s,m,b,p=triple();translated={i:(x+200,y-33,w,h) for i,(x,y,w,h) in b.items()}
    assert relative_edit(b,translated,windows(n,s)[0])==[]
    x,y,w,h=translated['c'];translated['c']=(x+40,y,w,h)
    assert relative_edit(b,translated,windows(n,s)[0])==['c']


def test_measured_document_block_leaves_space_for_direct_control_flow():
    from bpmn_v23.window_planner import repack_documents
    from bpmn_v23.responsive_labels import gap
    nodes={'a':{'kind':'task'},'b':{'kind':'task'}};docs={'d':{'kind':'dataObjectReference'}}
    boxes={'a':(100,100,180,76),'b':(100,400,180,76),'d':(172,210,36,50),'l':(30,65,900,650)}
    labels={'d':(135,265,110,28)};member={'a':'l','b':'l'};seq=[('ab','a','b','')]
    before=deepcopy((boxes,labels))
    result=repack_documents(boxes,labels,{'d'},{'d':'a'},nodes,docs,member,{'l':'Role'},seq,{'ab','info'})
    assert result is not None
    out,caps=result;assert out['d'][2:]==boxes['d'][2:] and caps['d'][2:]==labels['d'][2:]
    corridor=(184,176,12,224)
    assert gap(out['d'],corridor)>=6 and gap(caps['d'],corridor)>=6
    assert (boxes,labels)==before
