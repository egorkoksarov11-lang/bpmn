from copy import deepcopy
from bpmn_v23.block_optimize import optimize_slots


def fixture():
    slots={'s':(0,0),'a':(1,0),'b':(4,0),'e':(5,0),'r':(2,0)}
    motifs={'components':[{'backbone':['s','a','b','e']}],'owner':{n:n for n in slots}}
    seq=[('f1','s','a',''),('f2','a','b',''),('f3','b','e',''),('f4','b','r',''),('f5','r','a','')]
    return slots,motifs,seq,{n:'lane' for n in slots}


def test_repacking_moves_primary_steps_without_reversing_the_reading_order():
    slots,motifs,seq,members=fixture();before=deepcopy((slots,motifs,seq,members))
    result,report=optimize_slots(slots,motifs,seq,members,['lane'],free_spine=True)
    assert report['spine_moves']>0 and report['final_cost']<report['initial_cost']
    assert [result[n] for n in ['s','a','b','e']]==sorted(result[n] for n in ['s','a','b','e'])
    assert result['s']==slots['s'] and len(set(result.values()))==len(result)
    assert (slots,motifs,seq,members)==before


def test_legacy_mode_keeps_primary_steps_locked():
    slots,motifs,seq,members=fixture();result,_=optimize_slots(slots,motifs,seq,members,['lane'])
    assert all(result[n]==slots[n] for n in ['s','a','b','e'])


def test_repacking_keeps_each_node_in_its_original_lane_slots():
    slots,motifs,seq,members=fixture();members['r']='other';slots['r']=(0,0)
    result,_=optimize_slots(slots,motifs,seq,members,['lane','other'],free_spine=True)
    assert result['r'][1]==0
    assert len({result[n] for n in ['s','a','b','e']})==4
