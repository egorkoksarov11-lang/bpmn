from copy import deepcopy
from pathlib import Path
import pytest
from bpmn_v23.block_layout import graph_blocks,role_local_proposal
from bpmn_v23.stable_blocks import better,finalize_geometry,geometry_digest,refine_blocks
from bpmn_universal.contract import semantic_equality
from bpmn_refkit.model import read_bpmn
from bpmn_v23.freeze import equal
from bpmn_v23.pipeline import run
from bpmn_v23.scratch_layout import ScratchBackend

ROOT=Path(__file__).resolve().parents[1]

def graph():
    nodes={n:{'kind':('exclusiveGateway' if n in 'gj' else 'task'),'name':'Any'} for n in 'agbcjde'}
    seq=[(str(i),u,v,'') for i,(u,v) in enumerate([('a','g'),('g','b'),('g','c'),('b','j'),('c','j'),('j','d'),('d','e')])]
    member={n:'role' for n in nodes}
    return nodes,seq,member


def test_blocks_cover_graph_and_keep_complete_split_join_without_words():
    nodes,seq,member=graph();before=deepcopy((nodes,seq,member));groups=graph_blocks(nodes,seq,member)
    assert len([n for g in groups for n in g])==len(nodes)
    assert set().union(*map(set,groups))==set(nodes)
    assert any({'g','b','c','j'}<=set(g) for g in groups)
    renamed={n:{**o,'name':f'999.{i} cancel return skip'} for i,(n,o) in enumerate(nodes.items())}
    assert groups==graph_blocks(renamed,[(i,u,v,'999 no reverse') for i,u,v,_ in seq],member)
    assert (nodes,seq,member)==before


def test_block_bound_and_disconnected_graph():
    nodes={str(i):{'kind':'task','name':'n'} for i in range(25)};member={n:'r' for n in nodes}
    seq=[(str(i),str(i),str(i+1),'') for i in range(18)]
    groups=graph_blocks(nodes,seq,member)
    assert max(map(len,groups))<=8
    assert sorted(n for g in groups for n in g)==sorted(nodes)


def test_more_bends_can_buy_a_substantial_compactness_gain():
    before={'contacts':0,'hairpins':0,'score':100.,'area':1000.,'length':100.,'bends':3}
    after={**before,'score':80.,'area':360.,'length':104.,'bends':6}
    assert better(before,after)
    assert not better(before,{**after,'contacts':1})
    assert not better(before,{**after,'hairpins':1})
    assert not better(before,{**after,'length':120})


def test_role_local_constraints_close_holes_and_keep_readable_task_gap():
    from bpmn_v23.block_layout import relax_role_axes
    nodes={n:{'kind':'task','name':n} for n in 'abcd'};member={'a':'R1','b':'R1','c':'R2','d':'R2'}
    lanes={'R1':'First','R2':'Second'};seq=[('ab','a','b',''),('bc','b','c',''),('cd','c','d','')]
    boxes={'R1':(30,65,2000,200),'R2':(30,265,2000,200),'a':(100,100,180,76),'b':(900,100,180,76),'c':(100,300,180,76),'d':(900,300,180,76)}
    new,report=relax_role_axes(nodes,{},seq,[],member,lanes,boxes,{'reserved_captions':{}})
    assert report['role_local_relaxation']['solver']=='HiGHS-L1-envelope-constraints'
    assert report['role_local_relaxation']['center_wire_after']<report['role_local_relaxation']['center_wire_before']*.5
    assert new['b'][0]-(new['a'][0]+180)>=23.99 and new['d'][0]-(new['c'][0]+180)>=23.99
    assert new['a'][1:]==boxes['a'][1:]


@pytest.fixture(scope='module')
def result(tmp_path_factory):
    directory=tmp_path_factory.mktemp('whole-blocks');source=ROOT/'tests/fixtures/straight_pair.bpmn'
    run(source,directory/'out',ScratchBackend(candidate_seconds=4,search_seconds=15))
    return source,directory/'out'


def test_finalization_is_a_fixed_point_and_preserves_business_and_di(result):
    source,directory=result;path=directory/'process_08_v23.bpmn';svg=path.with_suffix('.svg')
    first=finalize_geometry(path,svg);digest=geometry_digest(path);original=path.read_bytes()
    second=finalize_geometry(path,svg)
    assert first['idempotent'] and second['idempotent'] and geometry_digest(path)==digest
    assert path.read_bytes()==original
    assert semantic_equality(source,path) and equal(source,path)


def test_atomic_pass_never_moves_unselected_shapes_or_roles(tmp_path):
    from bpmn_v23.input_formats import to_bpmn
    from bpmn_v23.di_geometry import update_geometry
    from bpmn_universal.contract import NS
    from bpmn_v23.labels import place_labels
    from bpmn_v23.pipeline import geometry
    model={'schema_version':1,'process':{'id':'P','name':'Synthetic'},'roles':[{'id':'R1','name':'First'},{'id':'R2','name':'Other'}],
           'nodes':[{'id':n,'type':'task','name':n,'role':'R1' if n in 'abcd' else 'R2'} for n in 'abcdef'],
           'flows':[{'id':a+b,'source':a,'target':b} for a,b in [('a','b'),('b','c'),('c','d'),('e','f')]]}
    source=tmp_path/'source.bpmn';to_bpmn(model,source);m=read_bpmn(source)
    boxes={'R1':(30,65,2200,200),'R2':(30,300,2200,200)}
    for i,n in enumerate('abcd'):boxes[n]=(100+i*400,100,180,76)
    for i,n in enumerate('ef'):boxes[n]=(100+i*400,335,180,76)
    paths={i:[(boxes[u][0]+180,boxes[u][1]+38),(boxes[v][0],boxes[v][1]+38)] for i,u,v,*_ in m[5]}
    update_geometry(m[1],m[3],boxes,paths);m[0].write(str(source),encoding='utf-8',xml_declaration=True)
    path=tmp_path/'result.bpmn';path.write_bytes(source.read_bytes());svg=tmp_path/'result.svg';place_labels(path,svg,preserve=True)
    before=read_bpmn(path);assert geometry(path)['routing_safety_passed']
    report=refine_blocks(path,svg,source,seconds=10);after=read_bpmn(path)
    assert report['accepted_blocks']>=1
    assert report['after']['length']<report['before']['length']
    for n in ('e','f','R1','R2'):assert after[-2][n]==before[-2][n]
    assert after[-1]['ef']==before[-1]['ef']
    assert semantic_equality(source,path) and equal(source,path)
    assert all(b['outside_nodes_moved']==b['outside_paths_changed']==0 for b in report['blocks'])


def test_track_compaction_shortens_routes_without_new_bends_or_header_cuts(tmp_path):
    from bpmn_v23.input_formats import to_bpmn
    from bpmn_v23.di_geometry import update_geometry
    from bpmn_v23.orthogonal_compaction import compact_orthogonal
    from bpmn_v23.labels import place_labels
    from bpmn_v23.pipeline import geometry
    model={'schema_version':1,'process':{'id':'P','name':'Synthetic'},'roles':[{'id':'R','name':'Role'}],
           'nodes':[{'id':n,'type':'task','name':n,'role':'R'} for n in 'abcd'],
           'flows':[{'id':a+b,'source':a,'target':b} for a,b in zip('abc','bcd')]}
    source=tmp_path/'source.bpmn';to_bpmn(model,source);m=read_bpmn(source)
    boxes={'R':(30,65,2200,200),**{n:(100+i*400,100,180,76) for i,n in enumerate('abcd')}}
    paths={i:[(boxes[u][0]+180,138),(boxes[v][0],138)] for i,u,v,*_ in m[5]}
    update_geometry(m[1],m[3],boxes,paths);m[0].write(str(source),encoding='utf-8',xml_declaration=True)
    path=tmp_path/'result.bpmn';path.write_bytes(source.read_bytes());svg=path.with_suffix('.svg');place_labels(path,svg,preserve=True)
    before=read_bpmn(path);report=compact_orthogonal(path,svg,source);after=read_bpmn(path)
    assert report['accepted'] and report['after']['length']<report['before']['length']*.5
    assert report['after']['bends']==report['before']['bends']
    for n in 'abcd':assert after[-2][n][1:]==before[-2][n][1:]
    for a,b in zip('abc','bcd'):assert after[-2][b][0]-after[-2][a][0]-180>=23.99
    assert geometry(path)['edge_clearance_passed'] and semantic_equality(source,path) and equal(source,path)
