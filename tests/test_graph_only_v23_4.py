from copy import deepcopy
from pathlib import Path
import pytest
from bpmn_v23.graph_topology import recognize
from bpmn_v23.stage_episodes import semantic_stages
from bpmn_v23.patterns import analyze
from bpmn_v23.clearance import safe_poly
from bpmn_v23.contours import attach


def example():
    kinds={'s':'startEvent','a':'task','g':'exclusiveGateway','b':'task','c':'task','j':'exclusiveGateway','e':'endEvent'}
    nodes={n:{'kind':k,'name':'arbitrary'} for n,k in kinds.items()}
    seq=[(str(i),u,v,'arbitrary condition') for i,(u,v) in enumerate([('s','a'),('a','g'),('g','b'),('g','c'),('b','j'),('c','j'),('j','e')])]
    member={n:'L' for n in nodes};boxes={n:(100,100,180,76) for n in nodes}
    return nodes,seq,member,boxes


def test_regions_and_spines_ignore_all_words_and_numbers():
    nodes,seq,member,boxes=example();before=deepcopy((nodes,seq,member,boxes));m,st=semantic_stages(nodes,seq,member,boxes)
    renamed=deepcopy(nodes)
    for i,n in enumerate(renamed):renamed[n]['name']=f'{99-i}.987 Отменить исправить согласовать reject cancel {i}'
    flows=[(i,u,v,'NO reverse cancel 999') for i,u,v,_ in seq]
    mm,ss=semantic_stages(renamed,flows,member,boxes)
    assert st==ss and m['pairs']==mm['pairs'] and m['components']==mm['components'] and m['feedback_edges']==mm['feedback_edges']
    assert m['graph_regions']['split_joins'][0]['strict_single_entry_exit']
    assert (nodes,seq,member,boxes)==before


def test_loop_region_does_not_require_step_numbers():
    nodes,seq,member,boxes=example();seq.append(('back','b','a',''))
    m,st=semantic_stages(nodes,seq,member,boxes)
    assert set(st)==set(m['macros']) and m['graph_regions']['natural_loops']


@pytest.mark.parametrize('kind,box,start',[('exclusiveGateway',(100,100,50,50),(150,110)),('startEvent',(100,100,36,36),(136,110))])
def test_projected_offset_port_is_safe_on_actual_contour(kind,box,start):
    boxes={'g':box,'t':(300,100,180,76)};nodes={'g':{'kind':kind},'t':{'kind':'task'}};uv={'f':('g','t')}
    projected=attach({'f':[start,(300,110)]},uv,boxes,nodes)['f']
    assert safe_poly('f',projected,boxes,uv,nodes=nodes)
    assert not safe_poly('f',projected,boxes,uv)  # Different frame contract.
    obstructed={**boxes,'block':(200,100,30,30)}
    assert not safe_poly('f',projected,obstructed,uv,nodes=nodes)


def test_actual_contour_check_rejects_inward_and_diagonal_terminal_segments():
    boxes={'g':(100,100,50,50),'t':(300,100,180,76)};nodes={'g':{'kind':'exclusiveGateway'},'t':{'kind':'task'}};uv={'f':('g','t')}
    assert not safe_poly('f',[(135,110),(120,110),(120,138),(300,138)],boxes,uv,nodes=nodes)
    assert not safe_poly('f',[(135,110),(300,138)],boxes,uv,nodes=nodes)


def test_group_can_expand_role_and_shift_lower_band_without_changing_membership():
    from bpmn_v23.group_space import repair_space
    nodes={n:{'kind':'task'} for n in 'abc'};member={'a':'L1','b':'L1','c':'L2'};lanes={'L1':'Any name','L2':'Any other name'}
    boxes={'a':(100,100,180,76),'b':(350,100,180,76),'c':(100,350,180,76),'L1':(30,65,900,200),'L2':(30,265,900,250)}
    before=deepcopy((boxes,member));r,reason=repair_space(boxes,{}, {'b':(100,228,180,76),'c':boxes['c']},nodes,{}, {},member,lanes,'a')
    assert reason is None
    new,labels,moved,detail=r
    assert new['L1'][3]>boxes['L1'][3] and new['L2'][1]>boxes['L2'][1]
    assert new['c'][1]-new['L2'][1]==boxes['c'][1]-boxes['L2'][1]
    assert new['b'][1]+76<=new['L1'][1]+new['L1'][3]-8 and detail['expanded_role_bands']>0
    assert (boxes,member)==before and new['a']==boxes['a']


def test_neighbor_can_move_to_release_requested_pattern_with_attachments():
    from bpmn_v23.group_space import repair_space
    from bpmn_v23.responsive_labels import gap
    nodes={n:{'kind':'task'} for n in 'abcd'};member={n:'L' for n in nodes}
    boxes={'a':(100,100,180,76),'b':(300,100,180,76),'c':(800,100,180,76),'d':(520,100,180,76),'doc':(550,220,36,50),'L':(30,65,1100,420)}
    caps={'doc':(590,220,110,35)};r,reason=repair_space(boxes,caps,{'b':boxes['d'],'c':boxes['c']},nodes,{'doc':{'kind':'dataObjectReference'}},{'doc':'d'},member,{'L':'Role'},'a')
    assert reason is None
    new,labels,moved,detail=r
    assert detail['neighbor_roots_moved'] and new['d']!=boxes['d']
    dx,dy=new['d'][0]-boxes['d'][0],new['d'][1]-boxes['d'][1]
    assert new['doc'][:2]==(boxes['doc'][0]+dx,boxes['doc'][1]+dy)
    assert labels['doc'][:2]==(caps['doc'][0]+dx,caps['doc'][1]+dy)
    assert gap(new['d'],new['b'])>=5


def test_role_names_and_disconnected_scenario_names_are_not_ordering_signals():
    from bpmn_v23.scratch_layout import semantic_role_order,independent_scenarios
    nodes,seq,member,boxes=example();member={n:'R1' if n in 'sag' else 'R2' for n in nodes};lanes={'R1':'999 Zzz','R2':'1 Aaa'}
    first=semantic_role_order(nodes,seq,member,lanes)
    assert first==semantic_role_order({n:{**o,'name':'0.1 cancel'} for n,o in nodes.items()},seq,member,{k:('AAAA' if k=='R1' else 'ZZZZ') for k in lanes})
    empty=[];a=independent_scenarios(nodes,empty,{},[])
    assert a==independent_scenarios({n:{**o,'name':str(100-i)} for i,(n,o) in enumerate(nodes.items())},empty,{},[])


def test_joint_routing_includes_real_document_association():
    from bpmn_v23.window_planner import joint_routes
    from bpmn_v23.document_layout import straight_link,safe_link
    nodes={n:{'kind':'task'} for n in 'abc'}
    boxes={'a':(100,100,180,76),'b':(308,100,180,76),'c':(308,204,180,76),'d':(100,300,36,50)}
    seq=[('ab','a','b',''),('bc','b','c','')];assocs=[('ad','a','d','')];uv={i:(u,v) for i,u,v,_ in seq+assocs}
    old={'ab':[(280,138),(308,138)],'bc':[(398,176),(398,204)],'ad':straight_link('a','d',boxes,nodes)}
    routed=joint_routes(boxes,nodes,seq,assocs,old,set(uv),('ab','bc'),boxes,old_boxes=boxes)
    assert routed is not None and set(routed)==set(uv)
    assert safe_link('ad',routed['ad'],boxes,uv,{i:p for i,p in routed.items() if i!='ad'},nodes=nodes)


def test_role_reordering_rebuilds_lines_and_keeps_full_model(tmp_path):
    from lxml import etree as ET
    from bpmn_universal.contract import NS,Q,B,BD,DC,DI,semantic_equality
    from bpmn_v23.role_refinement import refine_roles
    from bpmn_v23.render import render
    from bpmn_v23.freeze import equal
    from bpmn_v23.pipeline import geometry
    source=tmp_path/'source.bpmn';tree=ET.parse(str(Path(__file__).parent/'fixtures/straight_pair.bpmn'));root=tree.getroot()
    lane=root.xpath('.//b:lane',namespaces=NS)[0];lane.remove(lane.xpath('b:flowNodeRef[text()="b"]',namespaces=NS)[0]);ls=lane.getparent()
    ET.SubElement(ls,Q(B,'lane'),id='idle',name='999 Does not imply order')
    other=ET.SubElement(ls,Q(B,'lane'),id='other',name='1 Does not imply order');ET.SubElement(other,Q(B,'flowNodeRef')).text='b'
    plane=root.xpath('.//bd:BPMNPlane',namespaces=NS)[0]
    for ident,y,h in [('lane',100,180),('idle',280,300),('other',580,180)]:
        shapes=plane.xpath('bd:BPMNShape[@bpmnElement=$id]',namespaces=NS,id=ident)
        shape=shapes[0] if shapes else ET.SubElement(plane,Q(BD,'BPMNShape'),id='shape_'+ident,bpmnElement=ident)
        bound=shape.find(Q(DC,'Bounds'))
        if bound is None:bound=ET.SubElement(shape,Q(DC,'Bounds'))
        for k,v in zip(('x','y','width','height'),(100,y,800,h)):bound.set(k,str(v))
    for ident,x,y in [('a',150,140),('b',420,620)]:
        bound=plane.xpath('bd:BPMNShape[@bpmnElement=$id]/dc:Bounds',namespaces=NS,id=ident)[0];bound.set('x',str(x));bound.set('y',str(y))
    edge=plane.xpath('bd:BPMNEdge',namespaces=NS)[0]
    for child in list(edge):edge.remove(child)
    for x,y in [(350,180),(390,180),(390,660),(420,660)]:ET.SubElement(edge,Q(DI,'waypoint'),x=str(x),y=str(y))
    tree.write(str(source),encoding='utf-8',xml_declaration=True);output=tmp_path/'out.bpmn';output.write_bytes(source.read_bytes());svg=output.with_suffix('.svg');render(output,svg)
    r=refine_roles(output,svg,source,seconds=8)
    assert r['accepted'] and r['vertical_distance_proposed']<r['vertical_distance_before']
    assert r['objective_proposed']<r['objective_before']
    assert semantic_equality(source,output) and equal(source,output)
    assert geometry(output)['routing_safety_passed']


def test_whole_layout_guard_uses_shared_objective_with_bounded_tradeoffs():
    from bpmn_v23.cold_guard import prefer_control
    accepted,reason=prefer_control((51,188,58000),(58,145,49800),.94,.9)
    assert accepted and reason=='bounded_shared_objective_trade'
    assert not prefer_control((51,188,58000),(80,145,49800),.94,.9)[0]
    assert not prefer_control((51,188,58000),(58,145,49800),1.3,.9)[0]
    assert not prefer_control((51,188,58000),(58,145,49800),.94,1.01)[0]


def test_shortcut_and_backedge_do_not_cut_the_long_complete_forward_path():
    nodes={n:{'kind':('startEvent' if n=='s' else 'exclusiveGateway' if n=='g' else 'endEvent' if n in {'e','z'} else 'task'),'name':'No lexical meaning'} for n in ['s','g','a','b','c','d','e','z']}
    arcs=[('s','g'),('g','a'),('g','d'),('g','z'),('a','b'),('b','c'),('c','d'),('d','a'),('d','e')]
    seq=[(u+v,u,v,'') for u,v in arcs];member={n:'L' for n in nodes};boxes={n:(100,100,180,76) for n in nodes}
    result=analyze(nodes,seq,member,boxes,pair_merges=False)
    assert result['components'][0]['backbone']==['s','g','a','b','c','d','e']
    assert 'cd' not in result['feedback_edges'] and 'da' in result['feedback_edges']
