"""Graph recognizer checks: do not turn geometry or names into business rules."""
import importlib.util
from pathlib import Path
import copy
P=Path(__file__).resolve().parents[1]/'tools/analyze_layout_patterns.py'
spec=importlib.util.spec_from_file_location('pattern_study',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def graph(types,arcs):
 nodes=dict(types);edges=[(f'e{i}',u,v) for i,(u,v) in enumerate(arcs)];return nodes,edges,{n:'L' for n in nodes}
def test_diamond_finds_true_join():
 n,e,l=graph([('s','startEvent'),('g','exclusiveGateway'),('a','task'),('b','task'),('j','exclusiveGateway'),('z','endEvent')],[('s','g'),('g','a'),('g','b'),('a','j'),('b','j'),('j','z')])
 r=m.recognize(n,e,l);assert r['split_joins'][0]['join']=='j';assert r['split_joins'][0]['strict_single_entry_exit']
def test_different_endings_do_not_get_an_invented_join():
 n,e,l=graph([('g','exclusiveGateway'),('a','task'),('x','endEvent'),('y','endEvent')],[('g','a'),('a','x'),('g','y')]);r=m.recognize(n,e,l)
 assert r['split_joins']==[];assert len(r['terminal_branches'])==2
def test_natural_loop_has_header_and_retains_external_ports():
 n,e,l=graph([('s','startEvent'),('a','task'),('g','exclusiveGateway'),('b','task'),('z','endEvent')],[('s','a'),('a','g'),('g','b'),('b','a'),('g','z')]);before=copy.deepcopy((n,e,l));r=m.recognize(n,e,l)
 loop=r['natural_loops'][0];assert loop['header']=='a';assert set(loop['nodes'])=={'a','g','b'};assert loop['entries']==['e0'] and loop['exits']==['e4'];assert (n,e,l)==before
def test_irreducible_cycle_is_not_a_single_entry_natural_loop():
 n,e,l=graph([('s','startEvent'),('a','task'),('b','task'),('z','endEvent')],[('s','a'),('s','b'),('a','b'),('b','a'),('a','z'),('b','z')]);r=m.recognize(n,e,l)
 assert r['natural_loops']==[];assert r['cyclic_components'][0]['multi_entry']
def test_id_renaming_preserves_loop_and_join_sets():
 n,e,l=graph([('s','startEvent'),('a','task'),('g','exclusiveGateway'),('b','task'),('z','endEvent')],[('s','a'),('a','g'),('g','b'),('b','a'),('g','z')]);rename={k:f'x{4-i}' for i,k in enumerate(n)};rr=m.recognize({rename[k]:v for k,v in n.items()},[(i,rename[u],rename[v]) for i,u,v in e],{rename[k]:v for k,v in l.items()});r=m.recognize(n,e,l)
 assert {frozenset(rename[n] for n in q['nodes']) for q in r['natural_loops']}=={frozenset(q['nodes']) for q in rr['natural_loops']};assert {q['backedge'] for q in r['natural_loops']}=={q['backedge'] for q in rr['natural_loops']}
def test_external_input_prevents_blind_region_contraction():
 n,e,l=graph([('s','startEvent'),('g','exclusiveGateway'),('a','task'),('b','task'),('j','exclusiveGateway'),('z','endEvent')],[('s','g'),('s','a'),('g','a'),('g','b'),('a','j'),('b','j'),('j','z')]);r=m.recognize(n,e,l)
 region=next(q for q in r['split_joins'] if q['split']=='g');assert not region['strict_single_entry_exit'];assert 'e1' in region['external_inputs']
def test_self_loop_and_unreachable_closed_cycle():
 n,e,l=graph([('s','startEvent'),('z','endEvent'),('a','task')],[('s','z'),('a','a')]);r=m.recognize(n,e,l)
 assert r['not_reachable_from_entry']==['a'];assert r['not_reaching_exit']==['a'];assert r['natural_loops']==[];assert r['cyclic_components'][0]['nodes']==['a']
def test_scope_parser_does_not_merge_inner_process(tmp_path):
 p=tmp_path/'nested.bpmn';p.write_text(f'<definitions xmlns="{m.B}"><process id="p"><startEvent id="s"/><subProcess id="sub"><startEvent id="i"/><endEvent id="j"/><sequenceFlow id="f2" sourceRef="i" targetRef="j"/></subProcess><sequenceFlow id="f1" sourceRef="s" targetRef="sub"/></process></definitions>');d=m.parse(p)
 assert set(d['scopes']['p'])=={'s','sub'};assert set(d['scopes']['sub'])=={'i','j'};r=m.diagnostics(d);assert not r['motifs']['natural_loops']
def test_cross_scope_flow_is_rejected(tmp_path):
 import pytest
 p=tmp_path/'invalid.bpmn';p.write_text(f'<definitions xmlns="{m.B}"><process id="p"><startEvent id="s"/><subProcess id="sub"><task id="i"/></subProcess><sequenceFlow id="f" sourceRef="s" targetRef="i"/></process></definitions>')
 with pytest.raises(ValueError,match='Cross-scope'):m.parse(p)
def test_small_loop_signature_is_role_and_id_equivariant():
 n,e,l=graph([('a','task'),('g','exclusiveGateway'),('b','task')],[('a','g'),('g','b'),('b','a')]);l['b']='OTHER';model=dict(nodes=n,edges=e,lanes=l);r={'a':'z','g':'q','b':'x'};renamed=dict(nodes={r[k]:v for k,v in n.items()},edges=[(i,r[u],r[v]) for i,u,v in e],lanes={r[k]:'role1' if v=='L' else 'role2' for k,v in l.items()})
 assert m.small_loop_signature(model,n)==m.small_loop_signature(renamed,renamed['nodes'])
def test_signature_preserves_gateway_type_and_role_partition():
 n,e,l=graph([('a','task'),('g','exclusiveGateway'),('b','task')],[('a','g'),('g','b'),('b','a')]);model=dict(nodes=n,edges=e,lanes=l);original=m.small_loop_signature(model,n);variant=copy.deepcopy(model);variant['nodes']['g']='parallelGateway';assert m.small_loop_signature(variant,n)!=original;variant=copy.deepcopy(model);variant['lanes']['b']='other';assert m.small_loop_signature(variant,n)!=original
def test_split_regions_do_not_depend_on_input_edge_order():
 n,e,l=graph([('g','exclusiveGateway'),('a','task'),('b','task'),('z','endEvent')],[('g','a'),('g','b'),('a','z'),('b','z')]);a=m.recognize(n,e,l);b=m.recognize(n,list(reversed(e)),l)
 assert {frozenset(q['nodes']) for q in a['split_joins']}=={frozenset(q['nodes']) for q in b['split_joins']}
