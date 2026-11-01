from copy import deepcopy
from bpmn_v23.scenario_blocks import discover
from bpmn_v23.block_optimize import optimize_slots


def test_local_cycle_retains_all_external_connections():
    ns=['s','a','g','r','e'];es=[('in','s','a'),('next','a','g'),('fix','g','r'),('back','r','a'),('out','g','e')];old=deepcopy((ns,es))
    groups=discover(ns,es,['s']);assert len(groups)==1
    assert set(groups[0]['nodes'])=={'a','g','r'}
    assert {p['edge'] for p in groups[0]['boundary_ports']}=={'in','out'}
    assert groups[0]['returns']==['back'] and (ns,es)==old


def test_multi_entry_cycle_is_not_forced_into_a_natural_loop_template():
    assert discover(['s','a','b','e'],[('a','s','a'),('b','s','b'),('c','a','b'),('d','b','a'),('e','b','e')],['s'])==[]


def test_large_cycle_is_not_one_oversized_local_block():
    ns=['s']+[str(i) for i in range(8)];es=[('entry','s','0')]+[(str(i),str(i),str((i+1)%8)) for i in range(8)]
    assert discover(ns,es,['s'],max_nodes=6)==[]


def test_group_moves_preserve_input_and_reading_order():
    slots={'s':(0,0),'a':(1,0),'g':(4,0),'r':(2,0),'e':(5,0)};motifs={'owner':{n:n for n in slots},'components':[{'backbone':['s','a','g','e']}]};seq=[('in','s','a',''),('n','a','g',''),('fix','g','r',''),('back','r','a',''),('end','g','e','')];members={n:'lane' for n in slots};old=deepcopy((slots,motifs,seq,members))
    result,report=optimize_slots(slots,motifs,seq,members,['lane'],free_spine=True,scenario_blocks=True)
    assert report['scenario_blocks'] and len(set(result.values()))==len(result)
    assert [result[n] for n in ['s','a','g','e']]==sorted(result[n] for n in ['s','a','g','e'])
    assert (slots,motifs,seq,members)==old
