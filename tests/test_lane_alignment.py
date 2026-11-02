from copy import deepcopy
from bpmn_v23.lane_alignment import offset_options


def test_offsets_are_rigid_and_proposals_do_not_mutate_model():
 nodes={'a':{'kind':'task'},'g':{'kind':'exclusiveGateway'},'b':{'kind':'task'}};seq=[('f','a','g',''),('h','g','b','')];roles={'a':'l1','g':'l1','b':'l2'};boxes={'l1':(0,0,900,200),'l2':(0,200,900,200),'a':(100,60,220,80),'g':(350,75,50,50),'b':(100,260,220,80)};before=deepcopy((nodes,seq,roles,boxes))
 options=offset_options(nodes,seq,roles,boxes,{'l1':'one','l2':'two'})
 assert options and all(min(p['offsets'].values())==0 for p in options)
 assert (nodes,seq,roles,boxes)==before
 assert all(set(p['offsets'])=={'l1','l2'} for p in options)
