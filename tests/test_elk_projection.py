from bpmn_v23.elk_layout import pack_layers,handoff_groups
from copy import deepcopy


def test_handoffs_never_merge_two_operations_from_the_same_role():
 macros=['a','b','c','d'];edges=[('f','a','b'),('g','b','c'),('h','c','d')];roles={'a':'first','b':'second','c':'first','d':'third'}
 before=deepcopy((macros,edges,roles));groups=handoff_groups(macros,edges,roles)
 for g in set(groups.values()):
  ns=[n for n in macros if groups[n]==g];assert len({roles[n] for n in ns})==len(ns)
 assert (macros,edges,roles)==before and groups['a']==groups['b']


def test_layer_projection_keeps_roles_and_uses_distinct_cells():
 items=[{'id':'a','layer':0,'y':0},{'id':'b','layer':0,'y':30},{'id':'c','layer':1,'y':0}];roles={'a':'r','b':'r','c':'s'};old=deepcopy((items,roles))
 slots,bands=pack_layers(items,roles,{'c':['a']});assert slots['a']!=slots['b'] and slots['c'][0]>slots['a'][0];assert (items,roles)==old


def test_fold_does_not_jump_to_opposite_edge_at_band_boundary():
 items=[{'id':str(i),'layer':i,'y':0} for i in range(4)];roles={str(i):'r' for i in range(4)}
 slots,_=pack_layers(items,roles,{},wrap=2);assert slots['1'][0]==slots['2'][0] and slots['2'][1]>slots['1'][1]
