from bpmn_v23.phase_layout import step_hints,phase_plan
from copy import deepcopy
import pytest


def test_step_numbers_are_hints_and_names_are_never_modified():
 nodes={f'n{i}':{'kind':'task','name':f'3.{i} Operation'} for i in range(1,7)};nodes['r']={'kind':'task','name':'Correct'};seq=[(str(i),f'n{i}',f'n{i+1}','') for i in range(1,6)]+[('fix','n3','r',''),('back','r','n3','')];member={n:'lane' for n in nodes};boxes={n:(i*240,0,200,80) for i,n in enumerate(nodes)};old=deepcopy((nodes,seq,member,boxes))
 slots,labels=phase_plan(nodes,seq,member,boxes);assert labels['r']==3 and slots['n1'][0]<slots['n6'][0];assert (nodes,seq,member,boxes)==old


def test_missing_or_sparse_numbers_do_not_trigger_guessed_stages():
 nodes={'a':{'kind':'task','name':'Approve'},'b':{'kind':'task','name':'2026.11.01 date'}};assert step_hints(nodes)=={}
 with pytest.raises(ValueError):phase_plan(nodes,[],{'a':'l','b':'l'},{'a':(0,0,200,80),'b':(300,0,200,80)})
