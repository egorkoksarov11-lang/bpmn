from pathlib import Path
import math
import pytest
from lxml import etree as ET
from bpmn_v23.typography import task_layout,label_layout,font,width,balanced_wrap
from bpmn_v23.quality import contacts,segment_overlap,score
from bpmn_v23.document_layout import ray_port,refine_links,owners_for,attachment_metrics
from bpmn_v23.contours import on_contour
from bpmn_v23.labels import place_labels
from bpmn_v23.freeze import equal
from bpmn_universal.contract import semantic_equality,NS
from bpmn_refkit.model import read_bpmn


def test_full_cyrillic_name_fits_actual_ink_with_adaptive_font():
    name='5.2 Проверить необходимость включения документа в личное дело'
    box=(0,0,160,64);layout=task_layout(name,box)
    assert layout['fits'] and 10<=layout['font_size']<=13
    assert ''.join(''.join(layout['lines']).split())==''.join(name.split())
    for line,y in zip(layout['lines'],layout['baselines']):
        b=font(layout['font_size']).getbbox(line,anchor='ls')
        assert y+b[1]>=6-.01 and y+b[3]<=box[3]-6+.01
        assert width(line,layout['font_size'])<=box[2]-12+.01


def test_collapsed_marker_has_reserved_text_space():
    box=(0,0,190,76);layout=task_layout('Организовать проверку документов и результатов операции',box,'callActivity')
    assert layout['fits']
    for line,y in zip(layout['lines'],layout['baselines']):
        assert y+font(layout['font_size']).getbbox(line,anchor='ls')[3]<=box[3]-20+.01


def test_diagonal_contacts_and_collinear_overlap_are_not_hidden():
    uv={'a':('x','y'),'b':('m','n')}
    assert len(contacts({'a':[(0,0),(10,10)],'b':[(0,10),(10,0)]},uv))==1
    assert len(contacts({'a':[(0,0),(10,10)],'b':[(0,5),(10,5)]},uv))==1
    assert segment_overlap((0,0),(10,10),(5,5),(20,20))==pytest.approx(math.sqrt(50))
    assert segment_overlap((0,0),(10,10),(5,6),(20,21))==0
    assert contacts({'a':[(0,0),(10,10)],'b':[(10,10),(15,0)]},{'a':('x','y'),'b':('y','z')})==[]


def test_information_link_cannot_enter_its_own_terminal_shape():
    from bpmn_v23.document_layout import safe_link
    boxes={'a':(0,0,100,60),'d':(200,100,36,50)};uv={'i':('a','d')}
    assert not safe_link('i',[(0,30),(200,125)],boxes,uv,{})
    assert safe_link('i',[(100,60),(200,100)],boxes,uv,{})


def test_smaller_font_keeps_an_ordinary_compound_word_whole():
    layout=label_layout('Лист-заверитель дела',(0,0,100,27))
    assert layout['fits'] and layout['lines']==['Лист-заверитель','дела']


@pytest.mark.parametrize('kind',['task','exclusiveGateway','startEvent'])
def test_information_link_ports_follow_true_contours(kind):
    p=ray_port((10,20,80,60),(180,170),kind)
    assert on_contour(p,(10,20,80,60),kind,tolerance=.01)


def test_caption_can_use_empty_gateway_corner_but_never_overlap_its_ink():
    from bpmn_v23.contours import label_hits_shape
    box=(0,0,50,50)
    assert not label_hits_shape((43,0,30,12),box,'exclusiveGateway',gap=2)
    assert label_hits_shape((24,20,30,12),box,'exclusiveGateway')
    assert label_hits_shape((43,0,30,12),box,'task')


def scene():
    nodes={'a':{'kind':'task'},'b':{'kind':'task'}};docs={'d':{'kind':'dataObjectReference'}}
    boxes={'a':(0,0,100,60),'b':(200,0,100,60),'d':(20,90,36,50)}
    seq=[('f','a','b','')];assocs=[('info','a','d','')]
    paths={'f':[(100,30),(200,30)],'info':[(50,60),(50,80),(38,80),(38,90)]}
    return nodes,docs,boxes,seq,assocs,paths


def test_short_document_link_preserves_workflow_and_improves_without_contacts():
    nodes,docs,boxes,seq,assocs,paths=scene();before={i:list(p) for i,p in paths.items()}
    result,changes=refine_links(nodes,docs,seq,assocs,boxes,paths)
    assert changes==['info'] and len(result['info'])==2
    assert result['f']==paths['f'] and paths==before
    uv={i:(u,v) for i,u,v,_ in seq+assocs}
    assert score(result,uv)<score(paths,uv)


def test_shortcut_is_rejected_if_it_would_cross_another_workflow():
    nodes,docs,boxes,seq,assocs,paths=scene()
    nodes|={'c':{'kind':'task'},'e':{'kind':'task'}}
    boxes|={'c':(-100,50,40,40),'e':(150,50,40,40)}
    seq.append(('g','c','e',''));paths['g']=[(-60,75),(10,75),(10,150),(190,150),(190,90)]
    # Explicit obstacle in the direct ray, while the old elbow avoids it.
    nodes['obstacle']={'kind':'task'};boxes['obstacle']=(39,69,7,8)
    result,changes=refine_links(nodes,docs,seq,assocs,boxes,paths)
    assert changes==[] and result==paths


def test_shared_store_keeps_all_consumers_and_uses_fixed_anchor():
    nodes,docs,boxes,seq,assocs,paths=scene();docs['d']['kind']='dataStoreReference'
    assocs.append(('other','b','d',''));paths['other']=[(220,60),(220,160),(38,160),(38,140)]
    fixed=owners_for(nodes,docs,assocs,boxes);moved={**boxes,'d':(220,90,36,50)}
    assert fixed=={'d':'a'}
    assert owners_for(nodes,docs,assocs,moved)=={'d':'b'}
    report=attachment_metrics(nodes,docs,assocs,moved,paths,fixed)
    assert report['fixed_owners']==fixed and len(report['consumer_links'])==2
    assert report['anchor_gaps']['d']>100


def test_valid_local_external_caption_is_not_rewritten(tmp_path):
    source=Path(__file__).parent/'fixtures/straight_pair.bpmn';out=tmp_path/'copy.bpmn';out.write_bytes(source.read_bytes())
    tree=ET.parse(str(out));shapes=tree.xpath('.//bd:BPMNShape',namespaces=NS)
    # The supplied fixture's existing event labels, when valid, remain identical.
    result=place_labels(out,tmp_path/'out.svg',preserve=True)
    assert not result['unplaced_labels'] and not result['rendering']['text_overflow_ids']
    assert semantic_equality(source,out) and equal(source,out)


def test_variable_task_dimensions_keep_short_task_small():
    from bpmn_v23.axis_layout import axis_proposal
    nodes={'a':{'kind':'task','name':'Проверить'},'b':{'kind':'task','name':'Подготовить и проверить комплект документов перед выполнением операции'}}
    boxes={'a':(100,100,160,64),'b':(300,100,200,76),'lane':(30,60,600,200)}
    out,_=axis_proposal(nodes,{},[('f','a','b','')],[],{'a':'lane','b':'lane'},{'lane':'роль'},boxes,responsive=True)
    assert out['a'][2:]==(160,64) and out['b'][2:]==(200,76)
    assert out['a'][1]+out['a'][3]/2==out['b'][1]+out['b'][3]/2


def test_compound_document_moves_preserve_every_workflow_step_and_link(tmp_path):
    from bpmn_v23.attachment_refinement import compact_attachments
    from bpmn_v23.pipeline import geometry
    source=Path(__file__).resolve().parents[1]/'examples/benchmarks/r8/ref_11/after.bpmn'
    out=tmp_path/'after.bpmn';out.write_bytes(source.read_bytes())
    before=read_bpmn(source);report=compact_attachments(out,tmp_path/'after.svg',source,seconds=5);after=read_bpmn(out)
    assert report['changes'] and report['after']['mean_anchor_gap']<report['before']['mean_anchor_gap']*.7
    assert report['after']['association_length']<report['before']['association_length']
    assert report['sequence_nodes_and_waypoints_preserved']
    assert all(before[-1][i]==after[-1][i] for i,_,_,_ in before[5])
    assert all(before[-2][n]==after[-2][n] for n in before[4])
    assert semantic_equality(source,out) and equal(source,out)
    def named_flow_labels(model):
        return {e.get('bpmnElement') for e in model[1].xpath('.//bd:BPMNEdge[bd:BPMNLabel]',namespaces=NS)}
    assert named_flow_labels(before)<=named_flow_labels(after)
    g=geometry(out)
    assert g['routing_safety_passed'] and g['edge_clearance_passed']
    assert not(g['label_collision_pairs'] or g['label_line_cuts'] or g['task_text_overflows'])


def test_refinement_updates_preserve_original_shape_and_branch_caption_bounds():
    from bpmn_v23.di_geometry import update_geometry
    source=Path(__file__).resolve().parents[1]/'examples/benchmarks/r8/ref_11/after.bpmn'
    m=read_bpmn(source)
    before={e.get('bpmnElement'):[ET.tostring(l) for l in e.xpath('bd:BPMNLabel',namespaces=NS)] for e in m[3]}
    update_geometry(m[1],m[3],m[-2],m[-1])
    after={e.get('bpmnElement'):[ET.tostring(l) for l in e.xpath('bd:BPMNLabel',namespaces=NS)] for e in m[3]}
    assert before==after and any(v for k,v in before.items() if k in {i for i,_,_,name in m[5] if name})


def test_flow_caption_uses_clear_quarter_when_midpoint_is_congested(tmp_path,monkeypatch):
    from bpmn_v23 import responsive_labels as labels
    from bpmn_universal.contract import Q,BD,DC
    from bpmn_refkit.geometry import bbox_intersect_seg
    root=ET.Element('definitions');plane=ET.SubElement(root,Q(BD,'BPMNPlane'))
    edge=ET.SubElement(plane,Q(BD,'BPMNEdge'),bpmnElement='f');label=ET.SubElement(edge,Q(BD,'BPMNLabel'))
    bounds=ET.SubElement(label,Q(DC,'Bounds'),x='470',y='117',width='80',height='24')
    nodes={'s':{'kind':'task'},'t':{'kind':'task'}}
    boxes={'s':(0,50,20,120),'t':(1000,50,100,120),'frame':(0,0,1200,400)}
    wires={str(x):[(x,70),(x,150)] for x in range(350,651,16)}
    paths={'f':[(20,110),(1000,110)],**wires}
    model=(ET.ElementTree(root),root,None,plane,nodes,[('f','s','t','Да')],[],{},{},{},boxes,paths)
    monkeypatch.setattr(labels,'read_bpmn',lambda path:model)
    monkeypatch.setattr(labels,'render',lambda *args:{'text_overflow_ids':[]})
    report=labels.place_responsive_labels(tmp_path/'layout.bpmn',tmp_path/'layout.svg')
    assert report['unplaced_labels']==[]
    b=tuple(float(bounds.get(k)) for k in ('x','y','width','height'))
    assert all(not bbox_intersect_seg(b,a,c,clearance=1) for ps in paths.values() for a,c in zip(ps,ps[1:]))
    assert labels.gap(b,(20,110,980,0))<=32
