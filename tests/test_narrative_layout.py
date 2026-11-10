"""Interaction structure, elastic geometry and non-regression of committed drafts."""
from pathlib import Path
import copy,math
import pytest
from bpmn_refkit.model import read_bpmn
from bpmn_universal.contract import semantic_equality
from bpmn_v23.freeze import equal
from bpmn_v23.narrative_planner import interaction_regions,reading_measure,acceptable_trial
from bpmn_v23.narrative_refinement import refine_narrative,open_draft_bands,write_trial
from bpmn_v23.orthogonal_compaction import solve_coordinates


def test_interaction_strands_cross_role_boundaries_and_ignore_names():
    nodes={n:{'kind':'task','name':n} for n in 'abcdef'};member={n:('requester' if n in 'acf' else 'executor') for n in nodes}
    edges=[(a+b,a,b,'') for a,b in zip('abcde','bcdef')]
    before=copy.deepcopy((nodes,edges,member));regions=interaction_regions(nodes,edges,member)
    assert any(r['nodes']==list('abcdef') and len(r['roles'])==2 for r in regions)
    assert any(r['kind']=='request_reply' and r['nodes']==list('abc') for r in regions)
    assert any(r['parent_nodes']==list('abcdef') for r in regions if r['nodes']==list('abc'))
    renamed={n:{**v,'name':f'999.{i} cancel return finish'} for i,(n,v) in enumerate(nodes.items())}
    assert regions==interaction_regions(renamed,[(i,a,b,'Yes 001') for i,a,b,_ in edges],member)
    assert (nodes,edges,member)==before


def test_candidate_must_improve_committed_layout_not_only_expanded_draft():
    initial={'score':100,'contacts':0,'hairpins':0,'broken_serial':0,'information_length':100,'crowding':0,'area':1000,'length':100}
    incumbent={**initial,'score':90,'area':900,'length':90}
    poor={**initial,'score':200,'area':1600,'length':150}
    expanded={**poor,'score':300,'area':2000,'length':200}
    assert not acceptable_trial(initial,incumbent,poor)
    assert not acceptable_trial(initial,expanded,poor)
    good={**incumbent,'score':80,'area':800,'length':80}
    assert acceptable_trial(initial,incumbent,good)
    assert not acceptable_trial(initial,incumbent,{**good,'broken_serial':1})
    assert not acceptable_trial(initial,incumbent,{**good,'contacts':1})


@pytest.fixture
def spaced(tmp_path):
    from bpmn_v23.input_formats import to_bpmn
    from bpmn_v23.di_geometry import update_geometry
    from bpmn_v23.labels import place_labels
    model={'schema_version':1,'process':{'id':'P','name':'Synthetic'},'roles':[{'id':'R1','name':'First'},{'id':'R2','name':'Second'}],
           'nodes':[{'id':n,'type':'task','name':n,'role':'R1' if n in 'ab' else 'R2'} for n in 'abcd'],
           'flows':[{'id':a+b,'source':a,'target':b} for a,b in zip('abc','bcd')]}
    source=tmp_path/'source.bpmn';to_bpmn(model,source);s=read_bpmn(source)
    boxes={'R1':(30,65,900,600),'R2':(30,665,900,600),'a':(120,130,180,76),'b':(420,130,180,76),'c':(420,1000,180,76),'d':(650,1000,180,76)}
    paths={'ab':[(300,168),(420,168)],'bc':[(510,206),(510,1000)],'cd':[(600,1038),(650,1038)]}
    update_geometry(s[1],s[3],boxes,paths);s[0].write(str(source),encoding='utf-8',xml_declaration=True)
    result=tmp_path/'result.bpmn';result.write_bytes(source.read_bytes());svg=result.with_suffix('.svg');place_labels(result,svg,preserve=True)
    return source,result,svg


def test_vertical_solver_compacts_roles_and_preserves_sizes_and_ports(spaced):
    from bpmn_v23.pipeline import geometry
    source,path,svg=spaced;s=read_bpmn(path);solution,error=solve_coordinates(s,axis=1,width_weight=1.5)
    assert error is None;boxes,caps,paths=solution
    assert boxes['R1'][1]+boxes['R1'][3]==pytest.approx(boxes['R2'][1],abs=.02)
    assert sum(boxes[n][3] for n in ['R1','R2'])<600
    for n in 'abcd':assert boxes[n][0]==s[-2][n][0] and boxes[n][2:]==s[-2][n][2:]
    write_trial(s,path,svg,boxes,paths,caps)
    assert geometry(path)['routing_safety_passed'] and geometry(path)['edge_clearance_passed']
    assert semantic_equality(source,path) and equal(source,path)


def test_full_draft_pass_is_globally_better_and_semantically_frozen(spaced):
    from bpmn_v23.pipeline import geometry
    source,path,svg=spaced;before=reading_measure(read_bpmn(path));r=refine_narrative(path,svg,source,seconds=6);after=reading_measure(read_bpmn(path))
    assert r['accepted']>=1 and acceptable_trial(before,before,after)
    assert after['broken_serial']==before['broken_serial'] and after['contacts']==0
    assert semantic_equality(source,path) and equal(source,path) and geometry(path)['routing_safety_passed']


def test_draft_band_opening_keeps_document_glyph_dimensions(spaced):
    from bpmn_v23.group_space import repair_space
    source,path,svg=spaced;s=list(read_bpmn(path));s[-2]['doc']=(120,240,36,50);s[7]['doc']={'kind':'dataObjectReference','name':'Document'}
    proposal={'a':(120,130,180,76),'b':(120,500,180,76)};owners={'doc':'a'}
    boxes,caps,proposal=open_draft_bands(s,{},proposal,owners)
    assert boxes['R1'][1]+boxes['R1'][3]<=boxes['R2'][1]+.01
    repaired,error=repair_space(boxes,caps,proposal,s[4],s[7],owners,s[8],s[9],'a',defer_documents=True)
    assert error is None and repaired[0]['doc'][2:]==(36,50)


@pytest.mark.parametrize('budget',[0,-1,float('nan')])
def test_invalid_budget_rejected_before_file_access(tmp_path,budget):
    with pytest.raises(ValueError,match='budget'):refine_narrative(tmp_path/'missing',tmp_path/'none.svg',tmp_path/'source',seconds=budget)
