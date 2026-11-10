"""Regressions for topology-driven local composition and exact business freeze."""
from copy import deepcopy
from pathlib import Path
import json
from bpmn_refkit.model import read_bpmn
from bpmn_universal.contract import semantic_equality,NS
from bpmn_v23.episode_layout import episode_plan,episode_proposal,reserve_flow_labels
from bpmn_v23.spine_episodes import spine_proposal
from bpmn_v23.scratch_layout import erase_geometry,ScratchBackend
from bpmn_v23.freeze import equal
from bpmn_v23.pipeline import run,geometry
from bpmn_v23.typography import label_layout

ROOT=Path(__file__).resolve().parents[1]


def motif():
    nodes={n:{'kind':k,'name':name} for n,k,name in [
        ('s','startEvent','Начало'),('a','task','Проверить документы'),('g','exclusiveGateway','Документы полные?'),
        ('b','task','Согласовать'),('c','task','Зарегистрировать решение'),('r','task','Уточнить сведения'),('e','endEvent','Завершено')]}
    seq=[('f0','s','a',''),('f1','a','g',''),('f2','g','b','Да'),('f3','b','c',''),('f4','c','e',''),('f5','g','r','Нет'),('f6','r','a','')]
    member={n:('reviewer' if n=='b' else 'owner') for n in nodes};lanes={'owner':'Инициатор','reviewer':'Согласующий'}
    boxes={n:(100,100,200,76) if o['kind']=='task' else (100,100,50,50) for n,o in nodes.items()}
    boxes.update(owner=(30,65,1000,200),reviewer=(30,265,1000,200))
    return nodes,seq,member,lanes,boxes


def test_episode_search_preserves_graph_and_fixed_roles_with_unique_slots():
    nodes,seq,member,lanes,boxes=motif();before=deepcopy((nodes,seq,member,boxes))
    plan,motifs,report=episode_plan(nodes,seq,member,boxes,iterations=400,role_order=list(lanes))
    assert len({(member[n],*slot) for n,slot in plan.items()})==len(plan)
    assert set(plan)==set(motifs['macros']) and report['source_geometry_used'] is False
    assert (nodes,seq,member,boxes)==before
    assert 'f6' in report['feedback_edges']


def test_spine_keeps_handoff_and_exception_local_without_rewriting_the_model():
    nodes,seq,member,lanes,boxes=motif();before=deepcopy((nodes,seq,member))
    out,report=spine_proposal(nodes,{},seq,[],member,lanes,boxes)
    assert report['spine_episodes'][0]['anchor_count']>=2
    assert set(nodes)<=set(out) and report['source_geometry_used'] is False
    assert all(out[n][2:]==boxes[n][2:] for n in nodes)
    assert (nodes,seq,member)==before
    assert out['g'][0]-out['a'][0]<300


def test_flow_caption_bays_measure_full_conditions_before_routing():
    nodes={'a':{'kind':'task','name':'Проверить'},'b':{'kind':'task','name':'Продолжить'}}
    boxes={'a':(100,150,180,76),'b':(450,150,180,76),'l':(30,65,750,350)}
    seq=[('f','a','b','При подтверждении данных')]
    r=reserve_flow_labels(boxes,{'reserved_captions':{}},nodes,{},seq,{'l':'Роль'})
    assert 'f' in r['reserved_flow_captions']
    assert label_layout(seq[0][3],r['reserved_captions']['f'])['fits']
    assert seq[0][3]=='При подтверждении данных'


def test_new_default_has_exact_semantic_freeze_and_visible_names(tmp_path):
    source=ROOT/'tests/fixtures/straight_pair.bpmn';before=source.read_bytes()
    run(source,tmp_path/'result',ScratchBackend(candidate_seconds=4,search_seconds=15))
    output=tmp_path/'result/process_08_v23.bpmn';assert semantic_equality(source,output) and equal(source,output)
    assert source.read_bytes()==before
    r=json.loads((tmp_path/'result/run_report.json').read_text())
    from bpmn_v23 import __version__
    assert r['version']==__version__ and r['backend_report']['from_scratch']
    assert r['backend_report']['geometry_erasure']['source_positions_used'] is False
    assert r['backend_report']['selection_policy']=='whole-blocks-validated-objective-v2'
    g=geometry(output);assert g['routing_safety_passed'] and not g['label_collision_pairs'] and not g['missing_named_flow_labels']


def test_multi_input_join_is_not_owned_by_one_arbitrary_preceding_task():
    from bpmn_v23.patterns import analyze
    nodes={'a':{'kind':'task','name':'Первый результат'},'b':{'kind':'task','name':'Второй результат'},'j':{'kind':'parallelGateway','name':''},'c':{'kind':'task','name':'Продолжить'}}
    seq=[('a_j','a','j',''),('b_j','b','j',''),('j_c','j','c','')]
    member={n:'role' for n in nodes};boxes={n:(200,200,180,76) for n in nodes}
    motifs=analyze(nodes,seq,member,boxes,pair_merges=False)
    assert 'j' not in motifs['pairs'].values() and motifs['owner']['j']=='j'
    assert set(motifs['owner'])==set(nodes)


def test_spine_does_not_infer_business_outcome_from_names():
    from bpmn_v23.patterns import analyze
    nodes={n:{'kind':k,'name':name} for n,k,name in [('s','startEvent','Начало'),('g','exclusiveGateway','Продолжить?'),('a','task','Выполнить операцию'),('e','endEvent','Завершено'),('x','task','Отменить поручение'),('y','task','Отменить платеж'),('z','endEvent','Операция прекращена')]}
    seq=[(str(i),u,v,'') for i,(u,v) in enumerate([('s','g'),('g','a'),('a','e'),('g','x'),('x','y'),('y','z')])]
    boxes={n:(200,200,180,76) for n in nodes};member={n:'role' for n in nodes}
    m=analyze(nodes,seq,member,boxes,pair_merges=False,penalize_stops=True)
    changed={n:{**o,'name':('Выполнить' if n in {'x','y','z'} else 'Отменить')} for n,o in nodes.items()}
    assert m['components']==analyze(changed,seq,member,boxes,pair_merges=False,penalize_stops=True)['components']
    assert 'x' in m['components'][0]['backbone']


def test_local_group_drag_shortens_a_dogleg_without_changing_business_xml(tmp_path):
    from bpmn_v23.local_editing import edit_groups
    from bpmn_v23.render import render
    source=ROOT/'tests/fixtures/straight_pair.bpmn';output=tmp_path/'edited.bpmn';svg=output.with_suffix('.svg')
    output.write_bytes(source.read_bytes());render(output,svg)
    result=edit_groups(output,svg,source,seconds=6,max_trials=16)
    assert result['accepted_moves']
    assert result['after'][0]<=result['before'][0] and result['after'][1]<result['before'][1]
    assert result['after'][2]<result['before'][2]
    assert semantic_equality(source,output) and equal(source,output)
    assert geometry(output)['routing_safety_passed']


def test_empty_strip_map_preserves_object_sizes_and_order():
    from bpmn_v23.whitespace import axis_map
    fn,cuts=axis_map([(100,300),(700,900)],minimum_gap=24)
    assert fn(300)-fn(100)==200 and fn(900)-fn(700)==200
    assert fn(700)-fn(300)==24 and fn(100)<fn(300)<fn(700)<fn(900)
    assert sum(c[2] for c in cuts)==376


def test_document_bay_preserves_a_straight_handoff_with_offset_centres():
    from bpmn_v23.attachment_axes import attachment_axes
    from bpmn_v23.responsive_labels import gap
    nodes={'a':{'kind':'task','name':'Проверить'},'g':{'kind':'exclusiveGateway','name':'Готово?'}}
    docs={'d':{'kind':'dataObjectReference','name':'Результат'}};seq=[('f','a','g','')];assocs=[('info','a','d','Output')]
    member={'a':'l1','g':'l2'};lanes={'l1':'Исполнитель','l2':'Проверяющий'}
    original={'a':(100,100,180,76),'g':(100,500,50,50),'d':(150,220,36,50),'l1':(30,65,800,300),'l2':(30,365,800,300)}
    boxes,r=attachment_axes(nodes,docs,seq,assocs,member,lanes,original,overlap_corridors=True)
    assert abs(boxes['a'][0]+90-boxes['g'][0]-25)>1
    assert r['protected_direct_corridors']
    assert all(gap(boxes['d'],corridor)>=8 for corridor in r['protected_direct_corridors'])
    assert boxes['a'][2:]==(180,76) and boxes['g'][2:]==(50,50)


def test_perpendicular_ports_produce_a_one_bend_diagonal_handoff():
    from bpmn_v23.router import route_graph
    nodes={'a':{'kind':'task','name':'Запросить'},'b':{'kind':'task','name':'Ответить'}}
    boxes={'a':(100,100,180,76),'b':(400,300,180,76)};seq=[('f','a','b','')]
    paths,_=route_graph(boxes,nodes,seq,[],{}, {'f':[(200,200),(200,200)]},rounds=0,avoid_crowding=True,routing_policy={'crossing_penalty':1500,'bend_penalty':140})
    assert len(paths['f'])==3
    from bpmn_v23.quality import path_length
    assert path_length(paths['f'])<=320
    from bpmn_v23.clearance import safe_poly
    assert safe_poly('f',paths['f'],boxes,{'f':('a','b')})


def test_cold_guard_targets_dense_long_doglegs_not_every_model():
    from bpmn_v23.cold_guard import needs_guard
    assert needs_guard((80,150,80000),100)
    assert needs_guard((72,147,55000),93)
    assert not needs_guard((10,130,32000),100)
    assert not needs_guard((5,29,13500),100)


def test_internal_guard_constructs_from_erased_input_and_preserves_full_xml(tmp_path,monkeypatch):
    import bpmn_v23.cold_guard as guard
    import bpmn_v23.scratch_layout as scratch
    from bpmn_v23.di_geometry import update_geometry
    from bpmn_v23.render import render
    source=ROOT/'tests/fixtures/straight_pair.bpmn';neutral=tmp_path/'neutral.bpmn';erase_geometry(source,neutral);before=neutral.read_bytes()
    output=tmp_path/'generated.bpmn';output.write_bytes(source.read_bytes());svg=output.with_suffix('.svg');render(output,svg)
    calls=[]
    class InternalControl:
        def __init__(self,**kwargs):pass
        def layout(self,erased,destination,preview):
            m=read_bpmn(erased);calls.append(erased)
            assert {(b[0]+b[2]/2,b[1]+b[3]/2) for n,b in m[-2].items() if n in m[4]}=={(200,200)}
            new={'a':(100,140,180,76),'b':(350,140,180,76),'lane':(30,65,600,240)}
            update_geometry(m[1],m[3],new,{'f':[(280,178),(350,178)]});m[0].write(str(destination),encoding='utf-8',xml_declaration=True);render(destination,preview)
            return {'selected_candidate':'synthetic-cold-control'}
    monkeypatch.setattr(guard,'needs_guard',lambda *args:True);monkeypatch.setattr(scratch,'GraphChannelsBackend',InternalControl)
    report,adopted=guard.protect_cold_result(neutral,output,svg,candidate_seconds=2)
    assert calls==[neutral] and report['selected'] and adopted
    assert report['candidate_quality'][1]<report['before'][1]
    assert semantic_equality(neutral,output) and equal(neutral,output) and neutral.read_bytes()==before


def test_cold_guard_bounds_compactness_trade_instead_of_ignoring_regressions():
    from bpmn_v23.cold_guard import prefer_control
    assert prefer_control((50,180,60000),(55,185,45000),.75)[0]
    assert not prefer_control((50,180,60000),(80,185,45000),.75)[0]
    assert not prefer_control((50,180,60000),(55,230,45000),.75)[0]


def test_cold_guard_exposes_and_bounds_crossing_vs_bend_trade():
    from bpmn_v23.cold_guard import prefer_control
    accepted,reason=prefer_control((70,150,55000),(54,170,50000),.9)
    assert accepted and reason=='bounded_wire_readability_trade'
    assert not prefer_control((70,150,55000),(54,190,50000),.9)[0]
    assert not prefer_control((70,150,55000),(54,170,62000),.9)[0]
    assert not prefer_control((70,150,55000),(54,170,50000),1.2)[0]
