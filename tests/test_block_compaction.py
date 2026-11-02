from copy import deepcopy
from bpmn_v23.block_compaction import compact_blocks
from bpmn_refkit.geometry import bbox_intersect_seg


def scene(named=False):
    nodes={n:{'kind':'task','name':n} for n in 'abcd'};docs={'form':{'kind':'dataObjectReference','name':'Form'}};member={n:'l' for n in nodes};lanes={'l':'Role'}
    boxes={'l':(0,0,1900,600),**{n:(100+i*400,160,180,76) for i,n in enumerate(nodes)},'form':(100,280,36,50)}
    report={'axis_rows':{n:['l',0] for n in nodes},'document_owners':{'form':'a'},'reserved_captions':{'form':(143,285,120,36)}}
    seq=[('f','a','b','Condition text' if named else ''),('g','b','c',''),('h','c','d','')]
    return boxes,report,nodes,docs,seq,member,lanes


def test_folding_preserves_sizes_and_connects_successive_short_blocks():
    data=scene();before=deepcopy(data);boxes,report,nodes,docs,seq,member,lanes=data
    out,r=compact_blocks(*data)
    assert data==before and set(out)==set(boxes)
    assert all(out[n][2:]==boxes[n][2:] for n in nodes|docs)
    assert len(r['local_block_compaction']['folded_chains'])==2
    centre=lambda n:(out[n][0]+out[n][2]/2,out[n][1]+out[n][3]/2)
    assert centre('a')[0]==centre('b')[0] and centre('c')[0]==centre('d')[0]
    assert centre('b')[1]==centre('c')[1]
    assert out['l'][2]<boxes['l'][2] and out['l'][3]<boxes['l'][3]
    # Documents and captions must not occupy the new vertical connector.
    a,b=centre('a'),centre('b');a=(a[0],a[1]+out['a'][3]/2);b=(b[0],b[1]-out['b'][3]/2)
    assert not bbox_intersect_seg(out['form'],a,b,clearance=1)
    assert not bbox_intersect_seg(r['reserved_captions']['form'],a,b,clearance=1)


def test_named_vertical_link_reserves_a_real_caption_bay():
    data=scene(named=True);out,r=compact_blocks(*data)
    assert 'f' in r['reserved_flow_captions'] and 'f' in r['reserved_captions']
    b=r['reserved_captions']['f'];assert b[2]>0 and b[3]>0
    for n in data[2]|data[3]:
        a=out[n];assert min(a[0]+a[2],b[0]+b[2])<=max(a[0],b[0]) or min(a[1]+a[3],b[1]+b[3])<=max(a[1],b[1])


def test_branching_tasks_are_not_folded_as_an_unconditional_chain():
    boxes,report,nodes,docs,seq,member,lanes=scene();seq=[('f','a','b',''),('g','a','c',''),('h','b','d','')]
    out,r=compact_blocks(boxes,report,nodes,docs,seq,member,lanes)
    assert not any(c['nodes'][0]=='a' for c in r['local_block_compaction']['folded_chains'])


def test_operation_only_mode_does_not_stack_a_task_with_a_gateway():
    boxes,report,nodes,docs,seq,member,lanes=scene();nodes['b']['kind']='exclusiveGateway';boxes['b']=(500,173,50,50)
    out,r=compact_blocks(boxes,report,nodes,docs,seq,member,lanes,task_pairs_only=True)
    assert [c['nodes'] for c in r['local_block_compaction']['folded_chains']]==[['c','d']]
    assert out['a'][1]+out['a'][3]/2==out['b'][1]+out['b'][3]/2


def test_flow_caption_moves_with_its_role_after_reordering():
    from bpmn_v23.lane_ordering import reorder_lanes
    boxes={'A':(0,0,1000,200),'B':(0,200,1000,100),'a':(100,50,100,50),'b':(300,50,100,50),'c':(100,220,100,50)}
    nodes={n:{'kind':'task'} for n in 'abc'};seq=[('f','a','b','yes')];member={'a':'A','b':'A','c':'B'};report={'document_owners':{},'reserved_captions':{'f':(210,80,50,20)}}
    out,r=reorder_lanes(boxes,report,nodes,{},seq,member,{'A':'A','B':'B'},['B','A'])
    assert r['reserved_captions']['f'][1]-80==out['a'][1]-50==100


def test_reserved_flow_caption_is_saved_on_edge_not_as_a_shape():
    from lxml import etree as ET
    from bpmn_universal.contract import Q,BD,DC,NS
    from bpmn_v23.axis_labels import seed_captions
    root=ET.Element('definitions');plane=ET.SubElement(root,Q(BD,'BPMNPlane'));edge=ET.SubElement(plane,Q(BD,'BPMNEdge'),bpmnElement='f')
    seed_captions(root,{'f':(10,20,110,44)})
    assert edge.find(Q(BD,'BPMNLabel')).find(Q(DC,'Bounds')).get('height')=='44'
    assert not root.xpath('.//bd:BPMNShape',namespaces=NS)


def test_hybrid_stacks_secondary_checks_and_keeps_main_decisions_horizontal():
    boxes,report,nodes,docs,seq,member,lanes=scene();nodes['b']['kind']='exclusiveGateway';boxes['b']=(500,173,50,50)
    nodes.update(x={'kind':'task','name':'Check'},y={'kind':'exclusiveGateway','name':'Ready?'})
    boxes.update(other=(0,600,1900,400),x=(100,700,180,76),y=(500,713,50,50));member.update(x='other',y='other');lanes['other']='Other'
    report['axis_rows'].update(x=['other',0],y=['other',0]);report['reserved_captions']['y']=(475,780,100,40);seq=seq+[('check','x','y','')]
    out,r=compact_blocks(boxes,report,nodes,docs,seq,member,lanes,task_pairs_only=True,secondary_checks=True)
    chains=[c['nodes'] for c in r['local_block_compaction']['folded_chains']]
    assert ['x','y'] in chains and ['c','d'] in chains and ['a','b'] not in chains


def test_optional_merge_input_does_not_prevent_a_short_vertical_operation_pair():
    boxes,report,nodes,docs,seq,member,lanes=scene();seq=[('f','a','b',''),('alternative','c','b',''),('next','b','d','')]
    old=deepcopy(seq);out,r=compact_blocks(boxes,report,nodes,docs,seq,member,lanes,task_pairs_only=True,secondary_checks=True)
    assert ['a','b'] in [c['nodes'] for c in r['local_block_compaction']['folded_chains']]
    assert seq==old
