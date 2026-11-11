"""Late selection, complementary candidates and scoped routing work quotas."""
from pathlib import Path
import pytest
from bpmn_v23.portfolio import choose_records
from bpmn_v23.work_budget import routing_work,current_work
from bpmn_v23.scratch_layout import ScratchBackend


def record(name,new,old,signature,family):
    return {'entry':((new,(),0),name,b'',b'',{}),'legacy_rank':(old,(),0),'signature':signature,'family':family,'safe':True}


def test_complementary_champion_is_not_lost_to_early_reading_rank():
    a=record('a',1,9,'shape-a','horizontal');b=record('b',8,1,'shape-b','vertical');c=record('c',2,5,'shape-c','horizontal')
    selected=choose_records([c,b,a],2)
    assert [r['entry'][1] for r in selected]==['a','b']
    assert len(choose_records([a,{**a,'family':'other'}],4))==1
    with pytest.raises(ValueError):choose_records([a],0)


def test_fixed_astar_quota_and_context_are_independent_of_wall_budget():
    from bpmn_v23.router import astar
    boxes={'a':(100,100,180,76),'b':(600,100,180,76)};uv={'f':('a','b')}
    pairs=[((280,138),(600,138)),((190,176),(690,100))]
    with routing_work(fixed=True,astar_nodes=512) as first:
        p=astar('f',boxes,uv,{},pairs,max_seconds=0)
        assert p is not None and first['astar_expansions']<=512
    assert current_work() is None
    with routing_work(fixed=True,astar_nodes=1) as small:
        assert astar('f',boxes,uv,{},pairs,max_seconds=0) is None
        assert small['astar_expansions']==1 and small['astar_quota_hits']==2


def test_pipeline_selects_after_both_candidates_have_been_refined(tmp_path):
    from bpmn_refkit.model import read_bpmn
    from bpmn_v23.di_geometry import update_geometry
    from bpmn_v23.labels import place_labels
    from bpmn_v23.pipeline import run
    from bpmn_universal.contract import semantic_equality
    from bpmn_v23.freeze import equal
    root=Path(__file__).resolve().parents[1];source=root/'tests/fixtures/straight_pair.bpmn';original=source.read_bytes()
    def write(neutral,path,svg,gap):
        s=read_bpmn(neutral);boxes={'lane':(30,65,1500,200),'a':(100,100,180,76),'b':(280+gap,100,180,76)}
        update_geometry(s[1],s[3],boxes,{'f':[(280,138),(280+gap,138)]});s[0].write(str(path),encoding='utf-8',xml_declaration=True);place_labels(path,svg,preserve=True)
    class GeneratedCandidates:
        portfolio_width=2
        def __init__(self,**kwargs):pass
        def layout(self,neutral,path,svg):
            self.finalists=[]
            for name,gap,rank in [('early-winner',80,1),('late-winner',200,2)]:
                write(neutral,path,svg,gap);self.finalists.append(((rank,(),0),name,path.read_bytes(),svg.read_bytes(),{}))
            path.write_bytes(self.finalists[0][2]);svg.write_bytes(self.finalists[0][3])
            return {'selected_candidate':'early-winner','backend':'synthetic-cold-candidates'}
    class ControlledRefinement(ScratchBackend):
        def _finish_candidate(self,neutral,path,svg,backend,result):
            if result['selected_candidate']=='late-winner':write(neutral,path,svg,24)
            return result
    output=tmp_path/'out';run(source,output,ControlledRefinement(graph_backend=GeneratedCandidates))
    import json
    report=json.loads((output/'run_report.json').read_text())['backend_report'];p=report['portfolio_refinement']
    assert p['primary_before_final_refinement']=='early-winner' and p['selected']=='late-winner'
    assert len(p['finalists'])==2 and all(c['valid'] for c in p['finalists'])
    assert semantic_equality(source,output/'process_08_v23.bpmn') and equal(source,output/'process_08_v23.bpmn')
    assert source.read_bytes()==original


def test_fixed_candidate_mode_is_reproducible_on_a_small_complete_case(tmp_path):
    from bpmn_v23.pipeline import run
    from bpmn_v23.stable_blocks import geometry_digest
    source=Path(__file__).resolve().parents[1]/'tests/fixtures/straight_pair.bpmn'
    hashes=[]
    for i in range(2):
        output=tmp_path/str(i);run(source,output,ScratchBackend(candidate_seconds=4,search_seconds=60,candidate_limit=4,portfolio_size=1,staged_windows=False))
        hashes.append(geometry_digest(output/'process_08_v23.bpmn'))
    assert hashes[0]==hashes[1]


@pytest.mark.parametrize('options',[{'candidate_limit':0},{'portfolio_size':0},{'portfolio_size':5},{'astar_nodes':1}])
def test_invalid_budgets_are_rejected(options):
    with pytest.raises(ValueError):ScratchBackend(**options)
