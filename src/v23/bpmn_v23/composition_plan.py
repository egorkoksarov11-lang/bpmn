"""Cheap graph-only composition planning before any line routing.

Names are read only later by the existing measured attachment packer. Source DI
must already have been erased. Document identity comes from explicit data refs.
"""
from collections import defaultdict,Counter
from statistics import median
import math,time
from .block_layout import topology_order
from .lane_ordering import optimize_order,vertical_cost


def strands(nodes,seq,member):
    order,feedback=topology_order(nodes,seq);inc=defaultdict(list);out=defaultdict(list)
    for i,u,v,*_ in seq:
        inc[v].append((i,u));out[u].append((i,v))
    seen=set();chains=[]
    for start in order:
        if start in seen:continue
        chain=[start];seen.add(start);n=start
        while len(out[n])==1:
            eid,v=out[n][0]
            if eid in feedback or v in seen or len(inc[v])!=1 or member[v]!=member[n]:break
            chain.append(v);seen.add(v);n=v
        chains.append(chain)
    return chains,feedback


def logical_links(nodes,docs,assocs):
    groups=defaultdict(set)
    for d,detail in docs.items():groups[detail.get('obj',d)].add(d)
    links=set()
    for refs in groups.values():
        writers={u for _,u,v,*_ in assocs if v in refs and u in nodes}
        readers={v for _,u,v,*_ in assocs if u in refs and v in nodes}
        links|={(u,v) for u in writers for v in readers if u!=v}
    return sorted(links),sorted(len(g) for g in groups.values())


def interaction_order(roles,heights,seq,member):
    weights=defaultdict(float);offsets=defaultdict(float)
    for _,u,v,*_ in seq:
        a,b=member[u],member[v]
        if a==b:continue
        weights[a,b]+=1;weights[b,a]+=1
        offsets[a,b]+=heights[a]/2;offsets[b,a]+=heights[b]/2
    order,value,method=optimize_order(roles,heights,weights,offsets)
    return order,{'method':method,'before':vertical_cost(roles,heights,weights,offsets),'after':value}


def grid(chains,seq,member,columns,vertical,dependencies,growth_weight=6):
    neighbours=defaultdict(list)
    for _,u,v,*_ in seq:neighbours[u].append((v,1.));neighbours[v].append((u,1.))
    for u,v in dependencies:neighbours[u].append((v,.3));neighbours[v].append((u,.3))
    placed={};occupied=defaultdict(set);bottom=defaultdict(int);turns=[]
    for chain in chains:
        lane=member[chain[0]];cap=1 if vertical and len(chain)==2 else min(columns,len(chain))
        shape={n:((j%cap if (j//cap)%2==0 else cap-1-j%cap),j//cap) for j,n in enumerate(chain)}
        w=max(x for x,y in shape.values())+1;h=max(y for x,y in shape.values())+1
        known=[(n,p,weight) for n in chain for p,weight in neighbours[n] if p in placed]
        trials=[]
        for y in range(bottom[lane]+2):
            for x in range(columns-w+1):
                cells={(x+a,y+b) for a,b in shape.values()}
                if cells&occupied[lane]:continue
                travel=sum(weight*(abs(x+shape[n][0]-placed[p][0])+.7*abs(y+shape[n][1]-placed[p][1])) for n,p,weight in known)
                # Lane growth affects the whole pool, not just this chain.
                growth=max(bottom[lane],y+h)-bottom[lane]
                cost=travel+growth*growth_weight+x*.08+y*.25
                trials.append((cost,y,x,cells))
        if not trials:raise ValueError('No finite chain slot')
        _,y,x,cells=min(trials,key=lambda t:t[:3]);occupied[lane]|=cells;bottom[lane]=max(bottom[lane],y+h)
        for n,(a,b) in shape.items():placed[n]=(x+a,y+b)
        turns.extend(v for u,v in zip(chain,chain[1:]) if shape[u][1]!=shape[v][1])
    return placed,bottom,turns


def estimate(slots,order,heights,seq,member,feedback,dependencies,cw,ch):
    top={};cursor=0.
    for l in order:top[l]=cursor;cursor+=heights[l]
    pos={n:(x*cw,top[member[n]]+80+y*ch) for n,(x,y) in slots.items()}
    travel=0.;jumps=0.;elbows=0;segments=[];handoffs=[]
    for eid,u,v,*_ in seq:
        a,b=pos[u],pos[v];length=abs(a[0]-b[0])+abs(a[1]-b[1]);weight=.4 if eid in feedback else 1.
        travel+=weight*length/cw;elbows+=weight*(a[0]!=b[0] and a[1]!=b[1])
        if eid not in feedback:jumps+=max(0,length/cw-3)**2
        segments.append((u,v,a,b,weight))
        if member[u]!=member[v]:handoffs.append({'edge':eid,'column_delta':abs(slots[u][0]-slots[v][0])})
    crossings=0
    for k,(u,v,a,b,wa) in enumerate(segments):
        rx,ry=b[0]-a[0],b[1]-a[1]
        for s,t,c,d,wb in segments[k+1:]:
            if {u,v}&{s,t}:continue
            sx,sy=d[0]-c[0],d[1]-c[1];den=rx*sy-ry*sx
            if abs(den)<1e-8:continue
            qx,qy=c[0]-a[0],c[1]-a[1];ta=(qx*sy-qy*sx)/den;tb=(qx*ry-qy*rx)/den
            if 0<ta<1 and 0<tb<1:crossings+=min(wa,wb)
    width=(max(x for x,y in slots.values())+1)*cw
    info=sum((abs(pos[u][0]-pos[v][0])+abs(pos[u][1]-pos[v][1]))/cw for u,v in dependencies)
    packing=width*cursor/(cw*ch*max(1,len(slots)))
    aspect=width/max(1,cursor)
    loss=travel+1.5*elbows+.6*jumps+2*crossings+12*packing+.2*info+12*max(0,1.3-aspect)**2+3*max(0,aspect-3)**2
    return loss,{'proxy_score':round(loss,4),'estimated_width':width,'estimated_height':cursor,'estimated_area':width*cursor,'proxy_crossings':round(crossings,3),'logical_document_travel':round(info,3),'handoffs':handoffs}


def grid_plan(nodes,docs,seq,assocs,member,lanes,canonical):
    started=time.monotonic();chains,feedback=strands(nodes,seq,member);dependencies,groups=logical_links(nodes,docs,assocs)
    roles=sorted(lanes);cw=max(canonical[n][2] for n in nodes)+44;ch=max(canonical[n][3] for n in nodes)+130
    plans=[];seen=set()
    for columns in (8,12,16):
        for growth_weight in (6,20):
            for vertical in (False,True):
                for use_logical in (False,True):
                    slots,rows,turns=grid(chains,seq,member,columns,vertical,dependencies if use_logical else [],growth_weight)
                    heights={l:100+max(1,rows[l])*ch for l in roles}
                    adjusted,rd=interaction_order(roles,heights,seq,member)
                    signature=tuple(sorted(slots.items())),tuple(adjusted)
                    if signature in seen:continue
                    seen.add(signature)
                    loss,estimate_detail=estimate(slots,adjusted,heights,seq,member,feedback,dependencies,cw,ch)
                    plans.append({'columns':columns,'growth_weight':growth_weight,'vertical_pairs':vertical,'logical_alignment':use_logical,'slots':slots,'role_order':adjusted,'rows':dict(rows),'turn_nodes':turns,'role_cost':rd,'proxy':estimate_detail,'score':loss,'cell_width':cw,'cell_height':ch})
    plans.sort(key=lambda p:(p['score'],p['columns'],p['vertical_pairs'],p['logical_alignment']))
    # Distinct physical spans, rather than two nearly identical column caps.
    chosen=plans[:1]
    if chosen:
        w=chosen[0]['proxy']['estimated_width']
        broad=[p for p in plans[1:] if p['proxy']['estimated_width']>=w*1.3]
        others=broad or [p for p in plans[1:] if p['proxy']['estimated_width']<=w*.8] or plans[1:]
        if others:chosen.append(min(others,key=lambda p:p['score']))
    return chosen,{'method':'graph-only chain grid, exact role ordering and cheap composition proxies','seconds':round(time.monotonic()-started,6),'node_count':len(nodes),'chain_count':len(chains),'multi_node_chains':sum(len(c)>1 for c in chains),'logical_document_group_sizes':groups,'logical_dependency_pairs':len(dependencies),'feedback_edges':len(feedback),'evaluated_plans':len(plans),'chosen_plans':[{k:p[k] for k in ('columns','growth_weight','vertical_pairs','logical_alignment','role_order','rows','turn_nodes','role_cost','proxy')} for p in chosen],'source_geometry_used':False,'names_or_numbers_used_for_structure':False,'proxy_is_not_a_route_audit':True}


def grid_materialize(p,nodes,docs,seq,assocs,member,lanes,canonical):
    from .attachment_axes import attachment_axes
    from .episode_layout import reserve_flow_labels
    from .scratch_layout import semantic_document_owners
    order=p['role_order'];basis=dict(canonical);cw=p['cell_width'];ch=p['cell_height']
    for n,(x,y) in p['slots'].items():
        w,h=canonical[n][2:];basis[n]=(110+x*cw+(cw-w)/2,100+order.index(member[n])*10000+y*ch,w,h)
    for j,l in enumerate(order):basis[l]=(30,65+j*10000,(p['columns']+1)*cw,9900)
    for d,n in semantic_document_owners(nodes,docs,assocs,basis).items():
        x,y,w,h=basis[n];basis[d]=(x,y+h+24,*canonical[d][2:])
    ordered_lanes={l:lanes[l] for l in order}
    degree=Counter(u for _,u,v,*_ in seq)+Counter(v for _,u,v,*_ in seq)
    corridor_gap=max(32,min(64,16+8*max(degree.values(),default=1)))
    boxes,report=attachment_axes(nodes,docs,seq,assocs,member,ordered_lanes,basis,gap_size=corridor_gap,compact_bays=True,overlap_corridors=True)
    from .skyline_layout import compact_rows
    boxes,report=compact_rows(boxes,report,nodes,docs,member,ordered_lanes,seq)
    report=reserve_flow_labels(boxes,report,nodes,docs,seq,ordered_lanes)
    # Existing axis packer protects straight handoffs and caption/document bays.
    # Reserve empty outer tracks for feedback without changing any business edge.
    _,feedback=strands(nodes,seq,member);counts=Counter(member[u] for i,u,v,*_ in seq if i in feedback)
    owners=report['document_owners'];flow_owner={i:u for i,u,v,*_ in seq};shift={};cursor=65;corridors={}
    for l in order:
        x,y,w,h=boxes[l];pad=20+min(80,counts[l]*8);shift[l]=cursor+pad-y;boxes[l]=(x,cursor,w,h+pad+12);corridors[l]=(x+56,cursor+8,w-64,max(0,pad-8));cursor+=h+pad+12
    for n,b in list(boxes.items()):
        if n in nodes or n in docs:
            lane=member[owners.get(n,n)];boxes[n]=(b[0],b[1]+shift[lane],*b[2:])
        elif n not in lanes:boxes[n]=(b[0],65,b[2],cursor-65)
    report['reserved_captions']={n:(x,y+shift[member[flow_owner.get(owners.get(n,n),owners.get(n,n))]],w,h) for n,(x,y,w,h) in report.get('reserved_captions',{}).items()}
    report.update(external_engine='early-composition-plan',candidate_family='early-plan',early_composition={'columns':p['columns'],'vertical_pairs':p['vertical_pairs'],'logical_alignment':p['logical_alignment'],'proxy':p['proxy'],'turn_nodes':p['turn_nodes'],'feedback_track_bands':corridors,'corridor_gap':corridor_gap},source_geometry_used=False)
    return boxes,report



def phase_plans(nodes,docs,seq,assocs,member,lanes,canonical):
    from .phase_plan import phase_slots
    started=time.monotonic();chains,feedback=strands(nodes,seq,member)
    dependencies,groups=logical_links(nodes,docs,assocs);roles=sorted(lanes);plans=[];seen=set()
    for columns in (6,8,12,len(nodes)):
        for attach_next in (False,True):
            bases,motifs,components=phase_slots(nodes,docs,seq,assocs,member,lanes,canonical,columns=columns,attach_next=attach_next)
            rows={l:{row:i for i,row in enumerate(sorted({r for n,(c,r) in bases.items() if member[n]==l}))} for l in roles}
            slots={n:(c,rows[member[n]][r]) for n,(c,r) in bases.items()}
            for n,g in motifs['pairs'].items():
                x,y=slots[n];slots[g]=(x+.7,y)
            cw=max(canonical[n][2]+(canonical[motifs['pairs'][n]][2]+28 if n in motifs['pairs'] else 0) for n in bases)+44
            ch=max(canonical[n][3] for n in nodes)+130;heights={l:100+max(1,len(rows[l]))*ch for l in roles};order,detail=interaction_order(roles,heights,seq,member)
            signature=tuple(sorted(slots.items())),tuple(order)
            if signature in seen:continue
            seen.add(signature);score,proxy=estimate(slots,order,heights,seq,member,feedback,dependencies,cw,ch)
            plans.append({'columns':columns,'mode':('unfolded-phase' if columns==len(nodes) else 'whole-phase-band'),'attach_next':attach_next,'proxy':proxy,'score':score,'role_order':order,'slots':slots,'rows':{l:len(r) for l,r in rows.items()},'role_cost':detail,'components':components})
    plans.sort(key=lambda p:(p['score'],p['columns'],p['attach_next']))
    chosen=plans[:1]
    if chosen:
        alt=[p for p in plans[1:] if p['columns']!=chosen[0]['columns']] or plans[1:]
        if alt:chosen.append(alt[0])
    return plans,{'method':'graph spine phase bands and coupled role transfers before measured geometry','seconds':round(time.monotonic()-started,6),'evaluated_plans':len(plans),'logical_document_group_sizes':groups,'logical_dependency_pairs':len(dependencies),'chain_count':len(chains),'feedback_edges':len(feedback),'source_geometry_used':False,'names_or_numbers_used_for_structure':False,'proxy_is_not_a_route_audit':True,'chosen_plans':[{k:p[k] for k in ['columns','mode','attach_next','proxy','score','role_order','rows','role_cost']} for p in chosen]}


def phase_materialize(p,nodes,docs,seq,assocs,member,lanes,canonical):
    from .phase_plan import phase_proposal
    from .episode_layout import reserve_flow_labels
    ordered={l:lanes[l] for l in p['role_order']}
    boxes,r=phase_proposal(nodes,docs,seq,assocs,member,ordered,canonical,columns=p['columns'],attach_next=p['attach_next'])
    r=reserve_flow_labels(boxes,r,nodes,docs,seq,ordered)
    r.update(candidate_family='early-plan',external_engine='early-phase-bands',early_composition={'mode':'whole-phase-band','columns':p['columns'],'attach_next':p['attach_next'],'proxy':p['proxy']},source_geometry_used=False)
    return boxes,r


def plan(nodes,docs,seq,assocs,member,lanes,canonical):
    started=time.monotonic();args=(nodes,docs,seq,assocs,member,lanes,canonical)
    phase,phase_report=phase_plans(*args);grids,grid_report=grid_plan(*args)
    for p in grids:p['mode']='role-grid'
    all_plans=sorted(phase+grids,key=lambda p:(p['score'],p['mode'],p['columns']))
    control=min((p for p in phase if p['mode']=='unfolded-phase' and not p['attach_next']),key=lambda p:p['score'])
    ref=control['proxy'];pool=[];rejections=[]
    for p in all_plans:
        q=p['proxy']
        acceptable=(q['proxy_crossings']<=max(ref['proxy_crossings']+2,ref['proxy_crossings']*1.2)
                    and q['estimated_area']<=ref['estimated_area']*1.25 and p['score']<=control['score']*1.1)
        if acceptable or p is control:pool.append(p)
        else:rejections.append({'mode':p['mode'],'columns':p['columns'],'proxy_score':p['score'],'proxy_crossings':q['proxy_crossings']})
    chosen=pool[:1]
    if chosen:
        best=chosen[0]
        other=[p for p in pool[1:] if p['mode']!=best['mode'] and p['score']<=best['score']*1.15]
        if other:chosen.append(other[0])
        elif len(pool)>1:chosen.append(pool[1])
    report={'method':'early role-grid and whole-phase plans; complementary high-level families before routing','seconds':round(time.monotonic()-started,6),'evaluated_plans':phase_report['evaluated_plans']+grid_report['evaluated_plans'],'logical_document_group_sizes':phase_report['logical_document_group_sizes'],'logical_dependency_pairs':phase_report['logical_dependency_pairs'],'source_geometry_used':False,'names_or_numbers_used_for_structure':False,'proxy_is_not_a_route_audit':True,'chosen_plans':[{k:p[k] for k in ['columns','mode','score','role_order','rows','proxy']} for p in chosen],'proxy_control':control['proxy'],'proxy_guard_rejections':rejections,'proxy_guard_policy':{'crossings_ratio':1.2,'extra_crossings':2,'area_ratio':1.25,'score_ratio':1.1},'families':{'phase':phase_report,'grid':grid_report}}
    return chosen,report


def materialize(p,nodes,docs,seq,assocs,member,lanes,canonical):
    if p['mode'] in ('whole-phase-band','unfolded-phase'):return phase_materialize(p,nodes,docs,seq,assocs,member,lanes,canonical)
    return grid_materialize(p,nodes,docs,seq,assocs,member,lanes,canonical)
