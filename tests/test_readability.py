from pathlib import Path
import math
from lxml import etree as ET
from bpmn_v23.quality import contacts,edge_score,score
from bpmn_v23.contours import project,on_contour
from bpmn_v23.typography import fits,wrap,width
from bpmn_v23.router import refine_paths
from bpmn_v23.freeze import equal


def test_grid_vertices_do_not_hide_crossings():
    uv={'a':('u','v'),'b':('x','y')}
    original={'a':[(0,10),(20,10)],'b':[(10,0),(10,20)]}
    subdivided={'a':[(0,10),(10,10),(20,10)],'b':[(10,0),(10,10),(10,20)]}
    assert len(contacts(original,uv))==len(contacts(subdivided,uv))==1


def test_true_join_is_not_confused_with_t_junction():
    paths={'a':[(0,10),(10,10)],'b':[(10,10),(10,20)]}
    assert contacts(paths,{'a':('u','v'),'b':('v','w')})==[]
    assert len(contacts(paths,{'a':('u','v'),'b':('x','w')}))==1


def test_offset_gateway_port_attaches_to_diamond():
    box=(100,100,50,50)
    projected=project((150,110),(200,110),box,'exclusiveGateway')
    assert projected==(135,110)
    assert on_contour(projected,box,'exclusiveGateway')
    assert not on_contour((150,110),box,'exclusiveGateway')


def test_measured_wrap_keeps_full_cyrillic_and_long_words():
    name='Проверить технические характеристики сверхдлинноенеразрывноесловопараметров'
    lines=wrap(name,140,14)
    assert ''.join(''.join(lines).split())==''.join(name.split())
    assert all(width(line,14)<=140+.01 for line in lines)
    assert fits(name,(0,0,164,200))
    assert not fits(name,(0,0,164,35))


def test_di_freeze_rejects_non_coordinate_flags(tmp_path):
    source=Path(__file__).resolve().parents[1]/'inputs/benchmark/process_08_v4_frozen.bpmn'
    out=tmp_path/'out.bpmn';tree=ET.parse(str(source))
    shape=tree.xpath('//*[local-name()="BPMNShape"]')[0]
    shape.set('isHorizontal','false');tree.write(str(out))
    assert not equal(source,out)


def test_reroute_never_makes_global_quality_worse():
    boxes={'u':(0,0,40,40),'v':(200,0,40,40),'x':(90,-100,40,40),'y':(90,100,40,40)}
    uv={'a':('u','v'),'b':('x','y')}
    paths={'a':[(40,20),(200,20)],'b':[(110,-60),(110,100)]}
    before=score(paths,uv)
    refine_paths(boxes,uv,paths,rounds=1)
    assert score(paths,uv)<=before


def test_congested_route_stays_inside_validated_obstacle_window():
    import json
    from bpmn_v23.router import astar,overlapping
    from bpmn_universal.engine import good_poly
    source=Path(__file__).parent/'fixtures/congested_route.json'
    d=json.loads(source.read_text())
    result=astar(d['edge'],d['boxes'],d['uv'],d['paths'],d['pairs'])
    assert result is not None
    assert good_poly(d['edge'],result,d['boxes'],d['uv'])
    assert not overlapping(result,d['paths'])


def test_label_spatial_index_never_hides_line_collisions():
    from bpmn_v23.labels import SpatialIndex
    from bpmn_refkit.geometry import bbox_intersect_seg
    segments=[((-200,128),(400,128)),((128,-250),(128,500)),((0,0),(0,256)),((256,-128),(512,-128))]
    index=SpatialIndex()
    for a,b in segments:index.add((min(a[0],b[0]),min(a[1],b[1]),abs(a[0]-b[0]),abs(a[1]-b[1])),(a,b))
    for x in (-150,-4,0,120,127,128,130,250,256,400):
        for y in (-129,-4,0,120,127,128,250):
            rect=(x,y,25,22);query=(x-4,y-4,33,30)
            brute=any(bbox_intersect_seg(rect,a,b,clearance=-3) for a,b in segments)
            indexed=any(bbox_intersect_seg(rect,a,b,clearance=-3) for a,b in index.query(query))
            assert indexed==brute


def test_selected_v4_improves_contacts_and_keeps_complete_text():
    import json
    from bpmn_refkit.model import read_bpmn
    from bpmn_v23.pipeline import geometry
    from bpmn_v23.freeze import equal
    from bpmn_universal.contract import semantic_equality
    root=Path(__file__).resolve().parents[1]
    source=root/'inputs/benchmark/process_08_v4_frozen.bpmn'
    old=root/'tests/fixtures/v4_previous/process_08_v23.bpmn'
    new=root/'output/process_08_v23.bpmn'
    previous=read_bpmn(old);current=read_bpmn(new)
    uv={i:(u,v) for i,u,v,_ in current[5]+current[6]}
    assert score(current[-1],uv)[0]<score(previous[-1],uv)[0]
    assert semantic_equality(source,new) and equal(source,new)
    g=geometry(new)
    assert g['task_sizes_uniform'] and not g['task_text_overflows']
    assert not g['label_line_cuts'] and not g['label_collision_pairs']
    # Every visible task name is preserved, not replaced by ellipses or truncated.
    svg=ET.parse(str(root/'output/process_08_v23.svg'))
    from bpmn_refkit.model import TAG_TASK
    for node,info in current[4].items():
        if info['kind'] not in TAG_TASK:continue
        group=svg.xpath('//*[@data-bpmn-id=$id]',id=node)[0]
        visible=''.join(group.xpath('.//*[local-name()="text"]/text()'))
        assert ''.join(visible.split())==''.join(info['name'].split())


def test_selected_rank_is_best_of_verified_candidates():
    import json
    root=Path(__file__).resolve().parents[1]
    report=json.loads((root/'output/run_report.json').read_text())['backend_report']
    completed=[c for c in report['candidates'] if c['status']=='verified']
    assert completed
    assert report['quality']==min(c['rank'] for c in completed)
