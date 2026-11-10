"""Turns at activities, local graph coverage and bounded layout trade-offs."""
import copy
from bpmn_v23.turn_templates import turn_proposals
from bpmn_v23.narrative_planner import interaction_regions,prefer_reading


def state():
    nodes={n:{'kind':'task','name':n} for n in 'abcd'};seq=[(a+b,a,b,'') for a,b in zip('abc','bcd')]
    member={n:'R' for n in nodes};boxes={'R':(30,60,1800,800),**{n:(120+i*300,120,180,76) for i,n in enumerate(nodes)}}
    return [None,None,None,None,nodes,seq,[],{},member,{'R':'Role'},boxes,{}]


def test_turns_keep_every_internal_link_straight_and_anchor_fixed():
    s=state();original=copy.deepcopy(s);region={'kind':'local_strand','nodes':list('abcd')}
    options=list(turn_proposals(region,s));assert len(options)==8
    for name,p in options:
        assert p['a']==s[-2]['a']
        headings=[]
        for u,v in zip('abc','bcd'):
            a,b=p[u],p[v];dx=b[0]+b[2]/2-a[0]-a[2]/2;dy=b[1]+b[3]/2-a[1]-a[3]/2
            assert (abs(dx)<.01)!=(abs(dy)<.01)
            assert min(abs(dx)-180 if dx else 1000,abs(dy)-76 if dy else 1000)>=27.99
            headings.append((dx,dy))
        assert all(a[0]*b[0]+a[1]*b[1]>=0 for a,b in zip(headings,headings[1:]))
    assert s==original


def test_local_subchains_cover_late_steps_and_do_not_infer_text_order():
    nodes={f'n{i}':{'kind':'task','name':str(99-i)} for i in range(15)};ids=list(nodes);seq=[(str(i),a,b,'') for i,(a,b) in enumerate(zip(ids,ids[1:]))];member={n:'R' for n in ids}
    regions=interaction_regions(nodes,seq,member)
    assert any(r['nodes']==ids[-3:] for r in regions)
    changed={n:{**v,'name':'000 cancel first last'} for n,v in nodes.items()}
    assert regions==interaction_regions(changed,seq,member)


def measure():
    return {'score':100,'contacts':0,'hairpins':0,'broken_serial':0,'serial_links':9,'information_length':100,'crowding':0,'area':1000,'length':100,'forward_max_task_units':3}


def test_major_fold_can_spend_one_direct_link_only_for_large_gain():
    a=measure();b={**a,'score':70,'area':500,'length':130,'broken_serial':1}
    assert prefer_reading(a,b)
    assert not prefer_reading(a,{**b,'area':700})
    assert not prefer_reading(a,{**b,'forward_max_task_units':4.5})
    assert not prefer_reading(a,{**b,'broken_serial':2})
    assert not prefer_reading(a,{**b,'contacts':1})
    assert not prefer_reading(a,{**b,'hairpins':1})


def test_nearby_documents_use_absolute_nearness_not_only_relative_growth():
    a=measure();b={**a,'score':90,'area':900,'length':90,'information_length':160,'information_mean_task_units':.3,'information_max_task_units':.6}
    assert prefer_reading(a,b)
    assert not prefer_reading(a,{**b,'information_max_task_units':1.3})


def test_bare_task_reserves_measured_margin_not_100_pixels():
    from bpmn_v23.narrative_refinement import open_draft_bands
    s=state();s[-2]['R']=(30,60,1800,160);boxes,caps,p=open_draft_bands(s,{}, {'a':(120,180,180,76)}, {})
    assert boxes['R'][3]==212


def test_paragraph_fold_preserves_internal_path_ports_and_role_membership():
    from bpmn_v23.paragraph_layout import paragraph_candidates
    nodes={n:{'kind':'task','name':n} for n in 'abcdefgh'};ids=list(nodes);seq=[(a+b,a,b,'') for a,b in zip(ids,ids[1:])]
    member={n:'R1' if i<4 else 'R2' for i,n in enumerate(ids)}
    boxes={'R1':(30,60,2000,220),'R2':(30,280,2000,220),**{n:(100+i*210,100 if i<4 else 330,180,76) for i,n in enumerate(ids)}}
    paths={i:[(boxes[u][0]+180,boxes[u][1]+38),(boxes[v][0],boxes[v][1]+38)] for i,u,v,*_ in seq}
    s=[None,None,None,None,nodes,seq,[],{},member,{'R1':'One','R2':'Two'},boxes,paths]
    # Stub the XML label reader only; this geometry test exercises all actual
    # paragraph ordering, role rebuilding, endpoint translations and fixed paths.
    from lxml import etree as ET
    s[1]=ET.Element('root');before=copy.deepcopy(boxes)
    options=list(paragraph_candidates(s));assert options
    uv={i:(u,v) for i,u,v,*_ in seq}
    for name,new,caps,fixed in options:
        for n in nodes:
            x,y,w,h=new[n];lx,ly,lw,lh=new[member[n]]
            assert lx<=x and ly<=y and x+w<=lx+lw and y+h<=ly+lh
            assert (w,h)==boxes[n][2:]
        for i,pp in fixed.items():
            u,v=uv[i]
            assert pp[0]==(new[u][0]+180,new[u][1]+38)
            assert pp[-1]==(new[v][0],new[v][1]+38)
    assert boxes==before


def test_balanced_paragraph_allows_one_clear_row_transition_not_many_jumps():
    a={**measure(),'width':2000,'forward_max_task_units':1.5,'forward_p90_task_units':.8,'long_forward_count':0}
    b={**a,'score':90,'width':1400,'area':720,'length':144,'broken_serial':1,'forward_max_task_units':3.8,'forward_p90_task_units':.92,'long_forward_count':1}
    assert prefer_reading(a,b)
    assert not prefer_reading(a,{**b,'forward_p90_task_units':2})
    assert not prefer_reading(a,{**b,'long_forward_count':2})
    assert not prefer_reading(a,{**b,'area':900})
