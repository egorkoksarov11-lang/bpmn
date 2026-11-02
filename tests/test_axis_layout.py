from copy import deepcopy
from bpmn_v23.axis_layout import clusters,semantic_axes,axis_proposal
from bpmn_v23.axis_corridors import interpolator,mapped_routes
from bpmn_v23.adaptive_layout import AdaptiveBackend
from bpmn_v23.human_search import HumanStyleBackend
from bpmn_v23.decision_layout import _valid
import pytest


def test_axis_clusters_cannot_merge_a_chain_of_nearby_but_distant_ends():
    groups=clusters({'a':0,'b':15,'c':30},20)
    assert groups['a']==groups['b'] and groups['a']!=groups['c']


def test_linked_jittered_axes_are_recovered_without_collapsing_a_distant_chain():
    values={'a':100,'b':140,'c':180};initial=clusters(values,20)
    result=semantic_axes(values,initial,[('a','b'),('b','c')],55)
    assert result['a']==result['b'] and result['a']!=result['c']


def test_column_recovery_cannot_place_two_same_row_objects_on_top_of_each_other():
    values={'a':100,'b':140};initial=clusters(values,20)
    assert semantic_axes(values,initial,[('a','b')],55,blocked={'a':'row','b':'row'})['a']!=semantic_axes(values,initial,[('a','b')],55,blocked={'a':'row','b':'row'})['b']


def test_a_jittered_cross_role_handoff_recovers_its_shared_column():
    nodes={'a':{'kind':'task','name':'First'},'b':{'kind':'task','name':'Next'}}
    original={'l1':(30,10,700,300),'l2':(30,310,700,300),'a':(100,100,180,80),'b':(140,380,180,80)}
    boxes,_=axis_proposal(nodes,{},[('f','a','b','')],[],{'a':'l1','b':'l2'},{'l1':'One','l2':'Two'},original)
    assert boxes['a'][0]+boxes['a'][2]/2==boxes['b'][0]+boxes['b'][2]/2


def test_vertical_decision_and_handoff_axes_survive_without_changing_roles():
    nodes={'a':{'kind':'task','name':'First'},'g':{'kind':'exclusiveGateway','name':'Decision'},'b':{'kind':'task','name':'Next'}}
    seq=[('f','a','g',''),('h','g','b','')];member={'a':'l1','g':'l1','b':'l2'}
    original={'l1':(30,10,700,300),'l2':(30,310,700,300),'a':(100,100,180,80),'g':(165,220,50,50),'b':(100,380,180,80)}
    before=deepcopy((nodes,seq,member,original))
    boxes,report=axis_proposal(nodes,{},seq,[],member,{'l1':'One','l2':'Two'},original,gap=24)
    centres=[boxes[n][0]+boxes[n][2]/2 for n in ('a','g','b')]
    assert len(set(centres))==1 and boxes['a'][1]<boxes['g'][1]<boxes['b'][1]
    assert _valid(boxes,nodes,{},member)
    assert (nodes,seq,member,original)==before
    assert report['routing_priority']==['f','h']


def test_corridor_transfer_reanchors_real_boxes_and_retains_short_straight_links():
    nodes={'a':{'kind':'task'},'g':{'kind':'exclusiveGateway'},'b':{'kind':'task'}}
    old={'a':(100,100,180,80),'g':(320,115,50,50),'b':(420,100,180,80)}
    new={'a':(110,110,180,80),'g':(355,125,50,50),'b':(470,110,180,80)}
    paths={'f':[(280,140),(320,140)],'h':[(370,140),(420,140)]};uv={'f':('a','g'),'h':('g','b')};before=deepcopy((old,new,paths))
    report={'mapped_axes':{'x':[[190,200],[345,380],[510,560]],'y':[[140,150]]},'routing_priority':['f','h']}
    result=mapped_routes(report,old,paths,new,nodes,new,uv)
    assert result=={'f':[(290,150),(355,150)],'h':[(405,150),(470,150)]}
    assert (old,new,paths)==before


def test_nonmonotone_corridor_mapping_is_rejected():
    with pytest.raises(ValueError,match='Nonmonotone'):interpolator([[10,50],[20,40]])


def test_contact_count_is_not_hidden_by_a_nicer_synthetic_score(monkeypatch):
    candidate=AdaptiveBackend(candidate_seconds=1)
    monkeypatch.setattr(HumanStyleBackend,'candidate_rank',lambda *a:(.1,(2,5,100),4))
    crossing=candidate.candidate_rank()
    monkeypatch.setattr(HumanStyleBackend,'candidate_rank',lambda *a:(99,(1,40,1000),8))
    safer=candidate.candidate_rank()
    assert safer<crossing


def test_named_start_caption_has_an_actual_bay_above_the_full_row():
    nodes={'s':{'kind':'startEvent','name':'An operation begins here'},'a':{'kind':'task','name':'First'}}
    original={'lane':(30,10,700,300),'s':(100,100,36,36),'a':(250,78,180,80)}
    boxes,r=axis_proposal(nodes,{},[('f','s','a','')],[],{'s':'lane','a':'lane'},{'lane':'Role'},original,start_above=True)
    x,y,w,h=r['reserved_captions']['s']
    assert y>=boxes['lane'][1] and y+h<min(boxes[n][1] for n in nodes)


def test_cold_adaptive_pipeline_bootstraps_and_preserves_business_xml(tmp_path):
    from pathlib import Path
    from bpmn_v23.pipeline import run
    from bpmn_universal.contract import semantic_equality
    source=Path(__file__).parent/'fixtures/straight_pair.bpmn';before=source.read_bytes()
    backend=AdaptiveBackend(candidate_seconds=2)
    run(source,tmp_path/'out',backend)
    assert semantic_equality(source,tmp_path/'out/process_08_v23.bpmn')
    assert source.read_bytes()==before and backend.incumbent is None


def test_mismatched_incumbent_is_rejected_before_scoring_and_state_is_restored(tmp_path):
    from pathlib import Path
    from bpmn_v23.pipeline import run
    source=Path(__file__).parent/'fixtures/straight_pair.bpmn'
    wrong=tmp_path/'wrong.bpmn';wrong.write_text(source.read_text().replace('name="First"','name="Different logic"'))
    backend=AdaptiveBackend(incumbent=wrong,candidate_seconds=1)
    with pytest.raises(ValueError,match='freeze'):run(source,tmp_path/'out',backend)
    assert backend.incumbent==wrong and backend._baseline_limits is None


def test_lower_crossing_count_cannot_hide_a_large_navigation_regression(monkeypatch):
    import bpmn_v23.adaptive_layout as module
    import bpmn_v23.pipeline as pipeline
    candidate=AdaptiveBackend(candidate_seconds=1)
    candidate._baseline_limits={'length':1000,'extent_area':1000,'forward_hop_excess':.2,'parallel_crowding_per_flow':0,'hotspot_excess':0}
    monkeypatch.setattr(HumanStyleBackend,'candidate_rank',lambda *a:(.1,(0,2,900),4))
    monkeypatch.setattr(pipeline,'geometry',lambda *a:{'extent':{'width':100,'height':10}})
    monkeypatch.setattr(module,'reading_metrics',lambda *a:{'forward_hop_excess':2,'parallel_crowding_per_flow':0,'hotspot_excess':0})
    jumping=candidate.candidate_rank(None,{}, {},{}, {},{},[])
    monkeypatch.setattr(HumanStyleBackend,'candidate_rank',lambda *a:(1,(1,5,1000),4))
    monkeypatch.setattr(module,'reading_metrics',lambda *a:{'forward_hop_excess':.2,'parallel_crowding_per_flow':0,'hotspot_excess':0})
    continuous=candidate.candidate_rank(None,{}, {},{}, {},{},[])
    assert continuous<jumping
