from copy import deepcopy
from bpmn_v23.readability import metrics,parallel_nearness,graph_returns
from bpmn_v23.router import astar,choice_score,overlapping
from bpmn_v23.clearance import safe_poly


def model():
    nodes={n:{'kind':'task'} for n in ['a','b','c','d']}
    boxes={'a':(0,0,100,60),'b':(500,0,100,60),'c':(0,200,100,60),'d':(500,200,100,60)}
    seq=[('f','a','b',''),('g','c','d','')]
    return nodes,boxes,seq


def test_parallel_bundle_is_distinguished_without_any_crossing():
    nodes,boxes,seq=model()
    bundled={'f':[(100,90),(500,90)],'g':[(100,95),(500,95)]}
    spaced={'f':[(100,90),(500,90)],'g':[(100,125),(500,125)]}
    a=metrics(boxes,bundled,nodes,seq);b=metrics(boxes,spaced,nodes,seq)
    assert a['parallel_crowding_per_flow']>b['parallel_crowding_per_flow']==0
    assert parallel_nearness((0,0),(100,0),(0,5),(100,5),12)>0
    assert parallel_nearness((0,0),(100,0),(0,15),(100,15),12)==0


def test_long_navigation_route_is_penalized_more_than_a_short_successor():
    nodes,boxes,seq=model();short={'f':[(100,90),(300,90)],'g':[(100,200),(300,200)]};long={'f':[(100,90),(900,90)],'g':short['g']}
    assert metrics(boxes,long,nodes,seq)['forward_hop_excess']>metrics(boxes,short,nodes,seq)['forward_hop_excess']


def test_metrics_are_invariant_to_translation_and_uniform_coordinate_scale():
    nodes,boxes,seq=model();paths={'f':[(100,90),(500,90)],'g':[(100,95),(500,95)]};before=deepcopy((nodes,boxes,paths,seq));a=metrics(boxes,paths,nodes,seq)
    scaled={n:(x*2-300,y*2+110,w*2,h*2) for n,(x,y,w,h) in boxes.items()};pp={i:[(x*2-300,y*2+110) for x,y in ps] for i,ps in paths.items()};b=metrics(scaled,pp,nodes,seq)
    for key in ['parallel_crowding_per_flow','hotspot_excess','forward_hop_excess','peak_flow_load','bends_per_flow']:assert a[key]==b[key]
    assert (nodes,boxes,paths,seq)==before


def test_return_detection_is_graph_only_and_does_not_mark_every_leftward_edge():
    nodes={'s':{'kind':'startEvent'},'a':{'kind':'task'},'g':{'kind':'exclusiveGateway'},'b':{'kind':'task'},'e':{'kind':'endEvent'}}
    seq=[('start','s','a',''),('next','a','g',''),('repair','g','b',''),('return','b','a',''),('end','g','e','')]
    assert graph_returns(nodes,seq)=={'return'}


def test_route_choice_prefers_space_between_parallel_wires():
    uv={'f':('a','b'),'g':('c','d')};others={'g':[(0,0),(200,0)]};near=[(0,5),(200,5)];clear=[(0,25),(200,25)]
    assert choice_score('f',clear,others,uv,True)<choice_score('f',near,others,uv,True)


def test_crowding_aware_astar_preserves_clearance_and_distinct_channels():
    boxes={'a':(0,0,40,40),'b':(240,0,40,40),'obstacle':(80,-30,80,100)};uv={'f':('a','b'),'g':('x','y')};others={'g':[(0,-48),(280,-48)]}
    pairs=[(s,t) for s in [(40,20),(20,0)] for t in [(240,20),(260,0)]]
    ps=astar('f',boxes,uv,others,pairs,avoid_crowding=True)
    assert ps is not None and safe_poly('f',ps,boxes,uv) and not overlapping(ps,others)


def test_simplifying_one_wire_cannot_trade_hard_bend_safety_for_fewer_contacts(monkeypatch):
    from bpmn_v23 import router
    # Isolate acceptance from proposal generation: both proposals are clear,
    # but the lower-contact proposal exceeds the eight-bend readability limit.
    safe=[(10*((i+1)//2),10*(i//2)) for i in range(10)]
    tangled=[(10*((i+1)//2),10*(i//2)) for i in range(11)]
    monkeypatch.setattr(router,'burdens',lambda *args:{'f':1})
    monkeypatch.setattr(router,'quick_routes',lambda *args:[tangled])
    monkeypatch.setattr(router,'orthogonal_shortcuts',lambda *args:[])
    monkeypatch.setattr(router,'safe_poly',lambda *args:True)
    monkeypatch.setattr(router,'overlapping',lambda *args:False)
    monkeypatch.setattr(router,'astar',lambda *args,**kwargs:None)
    monkeypatch.setattr(router,'choice_score',lambda eid,p,*args:(0,0,0) if p==tangled else (1,0,0))
    paths={'f':safe}
    router.refine_paths({}, {'f':('a','b')},paths,rounds=1,simplify=True)
    assert paths['f']==safe
