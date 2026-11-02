from copy import deepcopy
from bpmn_v23.return_corridors import hints_factory
from bpmn_v23.route_refinement import RouteRefinementBackend
import pytest


def test_corridor_hints_only_target_graph_returns_without_mutation():
    nodes={n:{'kind':'task'} for n in ['a','b','c']}
    seq=[('f','a','b',''),('g','b','c',''),('back','c','b','')]
    boxes={'a':(100,50,100,60),'b':(300,50,100,60),'c':(500,50,100,60)}
    member={n:'lane' for n in nodes};lanes={'lane':(0,0,800,300)}
    before=deepcopy((nodes,seq,boxes,member,lanes))
    hints=hints_factory(nodes,seq,boxes,member,lanes)
    assert hints('f',{})==[] and hints('g',{})==[]
    paths=hints('back',{})
    assert paths and any(len(p)<=4 for p in paths)
    assert all(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(p,p[1:])) for p in paths)
    assert (nodes,seq,boxes,member,lanes)==before


def test_route_only_mode_requires_frozen_seed():
    with pytest.raises(ValueError,match='incumbent'):RouteRefinementBackend()


def test_failed_bend_repair_cannot_publish_unsafe_incumbent(tmp_path,monkeypatch):
    from pathlib import Path
    from bpmn_v23.pipeline import run
    import bpmn_v23.human_search as search
    root=Path(__file__).resolve().parents[1]
    monkeypatch.setattr(search,'refine_paths',lambda *a,**kw:[])
    out=tmp_path/'output';out.mkdir();saved=out/'process_08_v23.bpmn';saved.write_text('previous')
    backend=RouteRefinementBackend(incumbent=root/'examples/process_08_r4.bpmn',candidate_seconds=1)
    with pytest.raises(RuntimeError,match='pathological bends'):
        run(root/'inputs/benchmark/process_08_v4_frozen.bpmn',out,backend)
    assert saved.read_text()=='previous'
