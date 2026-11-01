from copy import deepcopy
from pathlib import Path
import json,zipfile
from bpmn_v23.patterns import analyze
from bpmn_v23.clearance import safe_poly,segment_blocked
from bpmn_v23.router import astar
from bpmn_v23.quality import score
from bpmn_v23.human_layout import proposals
from bpmn_v23.reference_style import measure_zip


def test_primary_path_survives_leftward_handoff_and_repair_stays_a_branch():
    nodes={'s':{'kind':'startEvent','name':'Старт'},'a':{'kind':'task','name':'Проверить'},'g':{'kind':'exclusiveGateway','name':'Есть замечания?'},'b':{'kind':'task','name':'Провести платеж'},'r':{'kind':'task','name':'Исправить документы'},'e':{'kind':'endEvent','name':'Готово'}}
    boxes={'s':(0,0,36,36),'a':(100,0,180,80),'g':(300,0,50,50),'b':(260,150,180,80),'r':(420,0,180,80),'e':(700,0,36,36)}
    seq=[('f1','s','a',''),('f2','a','g',''),('f3','g','b','Нет'),('f4','g','r','Да'),('f5','r','a',''),('f6','b','e','')];member={n:'lane' for n in nodes};before=deepcopy((nodes,seq,member,boxes))
    m=analyze(nodes,seq,member,boxes)
    assert m['pairs']=={'a':'g'}
    assert m['components'][0]['backbone']==['s','a','b','e']
    assert (nodes,seq,member,boxes)==before


def test_same_kind_in_another_lane_is_not_an_operation_decision_pair():
    nodes={'a':{'kind':'task','name':'Проверить'},'g':{'kind':'exclusiveGateway','name':'Да?'}}
    m=analyze(nodes,[('f','a','g','')],{'a':'first','g':'second'},{'a':(0,0,180,80),'g':(220,200,50,50)})
    assert not m['pairs']


def test_port_margin_can_be_crossed_in_multiple_grid_steps():
    box=(0,0,40,40)
    assert not segment_blocked((40,20),(42,20),box,terminal=True)
    assert not segment_blocked((42,20),(48,20),box,terminal=True)
    assert segment_blocked((42,10),(42,30),box,terminal=True)


def test_wires_cannot_hug_an_unrelated_task_border():
    boxes={'a':(0,0,40,40),'b':(200,0,40,40),'obstacle':(90,25,40,40)};uv={'f':('a','b')}
    assert not safe_poly('f',[(40,20),(200,20)],boxes,uv)
    assert safe_poly('f',[(40,20),(60,20),(60,-20),(180,-20),(180,20),(200,20)],boxes,uv)


def test_joint_port_search_can_choose_both_sides():
    boxes={'a':(0,0,40,40),'b':(240,0,40,40),'obstacle':(80,-30,80,100)};uv={'f':('a','b')}
    pairs=[(s,t) for s in [(40,20),(20,0)] for t in [(240,20),(260,0)]]
    best=astar('f',boxes,uv,{},pairs);first=astar('f',boxes,uv,{},pairs[:1])
    assert best is not None and safe_poly('f',best,boxes,uv)
    assert (best[0],best[-1]) in pairs
    if first is not None:assert score({'f':best},uv)<=score({'f':first},uv)


def test_joint_port_search_handles_a_self_loop_without_retracing():
    boxes={'a':(0,0,40,40)};uv={'f':('a','a')};ports=[(40,20),(20,0)]
    path=astar('f',boxes,uv,{},[(s,t) for s in ports for t in ports])
    assert path is not None and path[0]!=path[-1] and safe_poly('f',path,boxes,uv)


def test_reference_profile_is_measured_from_input_not_hardcoded(tmp_path):
    archive=tmp_path/'references.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for i,(w,h) in enumerate([(160,64),(260,96)]):
            z.writestr(str(i)+'.bpmn',f'''<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"><process id="p"><task id="a"/><task id="b"/><sequenceFlow id="f" sourceRef="a" targetRef="b"/></process><bpmndi:BPMNDiagram id="d"><bpmndi:BPMNPlane id="plane"><bpmndi:BPMNShape id="sa" bpmnElement="a"><dc:Bounds x="100" y="100" width="{w}" height="{h}"/></bpmndi:BPMNShape><bpmndi:BPMNShape id="sb" bpmnElement="b"><dc:Bounds x="{140+w}" y="100" width="{w}" height="{h}"/></bpmndi:BPMNShape></bpmndi:BPMNPlane></bpmndi:BPMNDiagram></definitions>''')
    result=measure_zip(archive)
    assert result['models_measured']==2 and result['tasks_measured']==4
    assert result['task_width_p75']==260 and result['task_width_median']==210
    assert result['aligned_gap_median']==40


def test_human_blocks_keep_every_node_inside_its_actual_lane():
    from bpmn_refkit.model import read_bpmn
    root=Path(__file__).resolve().parents[1]
    parsed=read_bpmn(root/'inputs/benchmark/process_08_v4_frozen.bpmn')
    nodes,seq,assocs,docs,member,lanes,original=[parsed[i] for i in [4,5,6,7,8,9,10]]
    untouched=deepcopy(original)
    name,boxes,report=next(proposals(nodes,docs,seq,assocs,member,lanes,original))
    assert original==untouched
    assert report['paired_decisions']>0 and report['source_reference_models']==32
    for n in nodes:
        x,y,w,h=boxes[n];lx,ly,lw,lh=boxes[member[n]]
        assert lx<=x and ly<=y and x+w<=lx+lw and y+h<=ly+lh
    assert {'T510c','T511a','T511b'}.issubset(report['main_macros'])


def test_di_lane_reorder_does_not_reassign_executors():
    from bpmn_v23.role_order import reorder_boxes
    nodes={'a':{'kind':'task'},'b':{'kind':'task'}};member={'a':'first','b':'second'}
    boxes={'first':(0,0,500,200),'second':(0,200,500,300),'a':(100,50,200,80),'b':(100,250,200,80)}
    old=deepcopy((boxes,member));changed=reorder_boxes(boxes,['second','first'],nodes,{},member,{})
    assert (boxes,member)==old
    assert changed['second'][1]==0 and changed['first'][1]==300
    assert changed['a'][1]==350 and changed['b'][1]==50
