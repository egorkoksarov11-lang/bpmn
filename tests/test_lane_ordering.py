from collections import defaultdict
from itertools import permutations
import math,random
from bpmn_v23.lane_ordering import optimize_order,reorder_lanes


def test_exact_order_matches_independent_exhaustive_endpoint_distances():
    rng=random.Random(9);roles=list('abcde');h={r:rng.randint(80,400) for r in roles};w=defaultdict(float);offsets=defaultdict(float);links=[]
    for _ in range(18):
        a,b=rng.sample(roles,2);ya=rng.uniform(0,h[a]);yb=rng.uniform(0,h[b]);links.append((a,ya,b,yb));w[a,b]+=1;w[b,a]+=1;offsets[a,b]+=ya;offsets[b,a]+=yb
    def actual(order):
        y=0;top={}
        for r in order:top[r]=y;y+=h[r]
        return sum(abs(top[a]+ya-top[b]-yb) for a,ya,b,yb in links)
    order,value,method=optimize_order(roles,h,w,offsets)
    assert math.isclose(actual(order),min(actual(p) for p in permutations(roles)),abs_tol=1e-4)
    assert math.isclose(value,actual(order),abs_tol=1e-4)
    assert 'exact' in method


def test_whole_lane_move_keeps_membership_local_geometry_and_caption_distance():
    nodes={n:{'kind':'task'} for n in 'abc'};docs={'d':{'kind':'dataObjectReference'}};member={'a':'A','b':'B','c':'C'};lanes={'A':'A','B':'B','C':'C'}
    boxes={'A':(0,0,1000,400),'B':(0,400,1000,150),'C':(0,550,1000,200),'a':(100,80,180,76),'b':(100,430,180,76),'c':(400,600,180,76),'d':(310,85,36,50)}
    seq=[('f'+str(i),'a','c','') for i in range(6)]+[('g','a','b','')];report={'document_owners':{'d':'a'},'reserved_captions':{'d':(355,90,110,28)}}
    out,r=reorder_lanes(boxes,report,nodes,docs,seq,member,lanes)
    assert r['lane_order_optimization']['after']<=r['lane_order_optimization']['before']
    assert r['lane_order_optimization']['order_ids']!=['A','B','C']
    actual=sum(abs(out[u][1]+out[u][3]/2-out[v][1]-out[v][3]/2) for _,u,v,_ in seq)
    assert actual==r['lane_order_optimization']['after']
    for n,l in member.items():assert out[n][1]-out[l][1]==boxes[n][1]-boxes[l][1]
    assert out['d'][1]-out['a'][1]==boxes['d'][1]-boxes['a'][1]
    assert r['reserved_captions']['d'][1]-out['d'][1]==report['reserved_captions']['d'][1]-boxes['d'][1]
    assert set(out)==set(boxes)
