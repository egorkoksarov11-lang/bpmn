"""Semantic-only local episode planning, followed by measured attachment packing.

A bounded deterministic discrete search chooses horizontal/vertical adjacency
before routing. Its objective is a placement estimate, never a quality claim.
No source DI, reference coordinates, process names or node-ID templates enter it.
"""
from collections import defaultdict, Counter
import heapq, math, random
from bpmn_refkit.model import TAG_TASK
from .patterns import analyze
from .readability import graph_returns
from .scratch_layout import GraphChannelsBackend
from .attachment_axes import attachment_axes
from .skyline_layout import compact_rows


def episode_plan(nodes, seq, member, original, *, rows=2, seed=23, iterations=2400, role_order=None):
    """Return macro slots with fixed role membership and no occupied-slot clash."""
    returns=graph_returns(nodes,seq)
    motifs=analyze(nodes,[e for e in seq if e[0] not in returns],member,original,pair_merges=False,penalize_stops=True)
    owner=motifs['owner'];ids=sorted(motifs['macros']);roles=list(role_order) if role_order is not None else sorted(set(member.values()))
    feedback=returns|set(motifs['feedback_edges'])
    arcs=[(i,owner[u],owner[v]) for i,u,v,_ in seq if owner[u]!=owner[v]]
    forward=[(i,u,v) for i,u,v in arcs if i not in feedback]
    incoming=defaultdict(list);outgoing=defaultdict(list);degree=Counter()
    for _,u,v in forward:incoming[v].append(u);outgoing[u].append(v);degree[v]+=1
    ready=[n for n in ids if not degree[n]];heapq.heapify(ready);order=[]
    while ready:
        u=heapq.heappop(ready);order.append(u)
        for v in outgoing[u]:
            degree[v]-=1
            if not degree[v]:heapq.heappush(ready,v)
    if len(order)!=len(ids):raise ValueError('Episode ranking graph is cyclic')
    main=set(n for c in motifs['components'] for n in c['backbone'])
    slots={};occupied=set()
    for n in order:
        # Cross-role handoffs can share a column; same-role continuations advance.
        x=max((slots[p][0]+(member[p]==member[n]) for p in incoming[n]),default=0)
        y=0 if n in main else min(rows-1,1)
        while (member[n],x,y) in occupied:
            if n not in main and y+1<rows:y+=1
            else:x+=1;y=0 if n in main else min(rows-1,1)
        slots[n]=(x,y);occupied.add((member[n],x,y))
    role_index={l:i for i,l in enumerate(roles)}
    # Each role band has enough estimated space for its local rows. The actual
    # measured envelope packing happens later, after the combinatorial search.
    def objective(plan):
        value=0.;right=max((p[0] for p in plan.values()),default=0)
        for i,u,v in arcs:
            x,y=plan[u];xx,yy=plan[v];dx=xx-x
            dy=(role_index[member[v]]-role_index[member[u]])*(rows*.85+1)+(yy-y)*.7
            length=abs(dx)+abs(dy);turns=0 if dx==0 or abs(dy)<.01 else 1
            weight=.45 if i in feedback else 1.
            value+=weight*(length+turns*1.8)
            if i not in feedback and dx<0:value+=4*abs(dx)+2
            if member[u]==member[v] and y==yy and abs(dx)>1:value+=(abs(dx)-1)*.65
        # Crossing pressure is assessed before routing, in the actual fixed role
        # order. Sharing a macro is legitimate convergence; unrelated collinear
        # handoffs are penalized as heavily as crossings.
        positions={n:(p[0],role_index[member[n]]*(rows*.85+1)+p[1]*.7) for n,p in plan.items()}
        cross=0.
        for index,(eid,u,v) in enumerate(arcs):
            a,b=positions[u],positions[v];rx,ry=b[0]-a[0],b[1]-a[1]
            for fid,w,z in arcs[index+1:]:
                if u in (w,z) or v in (w,z):continue
                c,d=positions[w],positions[z];sx,sy=d[0]-c[0],d[1]-c[1];den=rx*sy-ry*sx
                weight=.4 if eid in feedback or fid in feedback else 1.
                if abs(den)>1e-9:
                    qx,qy=c[0]-a[0],c[1]-a[1];t=(qx*sy-qy*sx)/den;h=(qx*ry-qy*rx)/den
                    if 0<t<1 and 0<h<1:cross+=weight
                elif abs(rx*(c[1]-a[1])-ry*(c[0]-a[0]))<1e-9:
                    if rx:
                        overlap=min(max(a[0],b[0]),max(c[0],d[0]))-max(min(a[0],b[0]),min(c[0],d[0]))
                    else:
                        overlap=min(max(a[1],b[1]),max(c[1],d[1]))-max(min(a[1],b[1]),min(c[1],d[1]))
                    if overlap>0:cross+=weight*1.5
        value+=cross*6.
        value+=right*.65+sum(max((p[1] for n,p in plan.items() if member[n]==l),default=0) for l in roles)*.9
        # Penalize blocked same-row continuations. This estimates routing trouble
        # without pretending that a straight center-to-center line is a route.
        for i,u,v in arcs:
            if member[u]!=member[v] or plan[u][1]!=plan[v][1]:continue
            lo,hi=sorted((plan[u][0],plan[v][0]));row=plan[u][1]
            value+=2.5*sum(member[n]==member[u] and p[1]==row and lo<p[0]<hi for n,p in plan.items())
        return value
    iterations=min(iterations,max(240,len(ids)*80))
    rng=random.Random(seed);current=objective(slots);best=current;best_plan=dict(slots);accepted=0
    for step in range(iterations):
        n=ids[rng.randrange(len(ids))];old=slots[n];neighbours=incoming[n]+outgoing[n]
        anchor=slots[rng.choice(neighbours)][0] if neighbours and rng.random()<.6 else old[0]
        target=(max(0,anchor+rng.choice((-2,-1,0,1,2))),rng.randrange(rows))
        if target==old:continue
        other=next((v for v in ids if v!=n and member[v]==member[n] and slots[v]==target),None)
        slots[n]=target
        if other is not None:slots[other]=old
        proposed=objective(slots);temperature=.7*(1-step/max(1,iterations))**2+.015
        if proposed<current or rng.random()<math.exp(min(0,(current-proposed)/temperature)):
            current=proposed;accepted+=1
            if current<best-1e-9:best=current;best_plan=dict(slots)
        else:
            slots[n]=old
            if other is not None:slots[other]=target
    return best_plan,motifs,{'objective':round(best,4),'accepted_moves':accepted,'iterations':iterations,'rows_per_role':rows,'seed':seed,'feedback_edges':sorted(feedback),'source_geometry_used':False}


def reserve_flow_labels(boxes,report,nodes,docs,seq,lanes):
    """Reserve measured condition bays before routing, without hiding any text."""
    from .typography import text_layout,width
    from .responsive_labels import gap
    caps=dict(report.get('reserved_captions',{}));occupied=[b for n,b in boxes.items() if n in nodes or n in docs]+list(caps.values())
    minx=min(boxes[l][0]+56 for l in lanes);miny=min(boxes[l][1] for l in lanes)+4
    maxx=max(boxes[l][0]+boxes[l][2] for l in lanes)-8;maxy=max(boxes[l][1]+boxes[l][3] for l in lanes)-4
    reserved=[]
    for eid,u,v,name in sorted(seq,key=lambda e:(-len(e[3]),e[0])):
        if not name or len(name)<9:continue
        a,b=boxes[u],boxes[v];ac=(a[0]+a[2]/2,a[1]+a[3]/2);bc=(b[0]+b[2]/2,b[1]+b[3]/2)
        candidates=[]
        for lw in sorted({min(140,max(24,math.ceil(width(name,12))+4)),100,140}):
            lh=text_layout(name,lw,1000,(12,),2,1)['required_height']
            for fraction in (.15,.3,.5,.7,.85):
                x=ac[0]+(bc[0]-ac[0])*fraction;y=ac[1]+(bc[1]-ac[1])*fraction
                candidates.extend([(x+8,y-lh/2,lw,lh),(x-lw-8,y-lh/2,lw,lh),(x-lw/2,y+8,lw,lh),(x-lw/2,y-lh-8,lw,lh)])
        def valid(q):return q[0]>=minx and q[1]>=miny and q[0]+q[2]<=maxx and q[1]+q[3]<=maxy and not any(gap(q,o)<5 for o in occupied)
        candidates=[q for q in candidates if valid(q)]
        if not candidates:continue
        chosen=min(candidates,key=lambda q:(gap(q,a)+gap(q,b)*.25+q[3]*.1,q))
        caps[eid]=chosen;occupied.append(chosen);reserved.append(eid)
    return {**report,'reserved_captions':caps,'reserved_flow_captions':reserved}


def episode_proposal(nodes,docs,seq,assocs,member,lanes,original,*,rows=2,seed=23,vertical=False):
    plan,motifs,detail=episode_plan(nodes,seq,member,original,rows=rows,seed=seed,role_order=list(lanes))
    basis=dict(original);pairs=motifs['pairs'];columns=defaultdict(float);heights=defaultdict(float)
    orientation={}
    for n in sorted(plan):
        w,h=original[n][2:];g=pairs.get(n);gw,gh=original[g][2:] if g else (0,0)
        # A vertical decision is useful when continuation primarily leaves the
        # role. It is an alternative candidate, never an unconditional rewrite.
        successors=[v for _,u,v,_ in seq if u==(g or n)]
        down=bool(g and vertical and any(member[v]!=member[n] for v in successors))
        orientation[n]=down;ww=max(w,gw) if down else w+(gw+28 if g else 0);hh=h+(gh+28 if g and down else 0)
        columns[plan[n][0]]=max(columns[plan[n][0]],ww);heights[(member[n],plan[n][1])]=max(heights[(member[n],plan[n][1])],hh)
    xs={};cursor=120
    for col in sorted(columns):xs[col]=cursor;cursor+=columns[col]+40
    ys={};cursor=100
    for lane in lanes:
        for row in range(rows):ys[lane,row]=cursor;cursor+=heights.get((lane,row),76)+180
        cursor+=80
    for n,(col,row) in plan.items():
        w,h=original[n][2:];x=xs[col];y=ys[member[n],row];basis[n]=(x,y,w,h)
        if n in pairs:
            g=pairs[n];gw,gh=original[g][2:]
            basis[g]=(x+w/2-gw/2,y+h+28,gw,gh) if orientation[n] else (x+w+28,y+h/2-gh/2,gw,gh)
    # Information ownership uses semantic direction, not the reference position.
    from .scratch_layout import semantic_document_owners
    for d,n in semantic_document_owners(nodes,docs,assocs,basis).items():
        x,y,w,h=basis[n];dw,dh=original[d][2:];basis[d]=(x,y+h+24,dw,dh)
    for index,l in enumerate(lanes):basis[l]=(30,65+index*1000,max(1000,cursor),1000)
    out,report=attachment_axes(nodes,docs,seq,assocs,member,lanes,basis,gap_size=32,compact_bays=True,overlap_corridors=True)
    out,report=compact_rows(out,report,nodes,docs,member,lanes,seq)
    report=reserve_flow_labels(out,report,nodes,docs,seq,lanes)
    detail['slots']={n:list(v) for n,v in plan.items()};detail['vertical_decisions']=[n for n,v in orientation.items() if v]
    report.update(episode_planning=detail,external_engine='semantic-episode-search',source_geometry_used=False)
    return out,report


class EpisodeGraphBackend(GraphChannelsBackend):
    name='v23.2-semantic-episodes'
    selection_policy='human-episodes-balanced-v2'
    candidate_refine_rounds=0
    overlap_corridors=True
    local_episode_editing=True
    routing_policy={'crossing_penalty':1500,'bend_penalty':140}
    def candidate_rank(self,path,boxes,paths,uv,nodes,docs,seq):
        from .quality import score,path_length
        from .readability import metrics
        from .local_editing import physical_bends
        from bpmn_universal.contract import NS
        from lxml import etree as ET
        quality=score(paths,uv);reading=metrics(boxes,paths,nodes,seq);count=max(1,len(seq))
        bends=sum(physical_bends(paths[i]) for i,*_ in seq)/count
        length=sum(path_length(paths[i]) for i,*_ in seq)/(200*count)
        rects=list(boxes.values())+[tuple(float(b.get(k)) for k in ('x','y','width','height')) for b in ET.parse(str(path)).xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS)]
        points=[p for ps in paths.values() for p in ps]
        width=max([b[0]+b[2] for b in rects]+[p[0] for p in points])-min([b[0] for b in rects]+[p[0] for p in points])
        height=max([b[1]+b[3] for b in rects]+[p[1] for p in points])-min([b[1] for b in rects]+[p[1] for p in points])
        packing=math.sqrt(width*height/(max(1,len(nodes))*200*80))
        overspan=max(0,width/(200*math.sqrt(max(1,len(nodes)))*1.8)-1)**2
        # Fixed physical normalization prevents larger task boxes from getting
        # an artificial density reward. The weights are explicit engineering
        # choices; no metric is presented as a human similarity percentage.
        value=8*quality[0]/count+1.2*bends+length+.4*packing+.4*overspan+6*reading['parallel_crowding_per_flow']+1.2*reading['hotspot_excess']+.25*reading['forward_hop_excess']
        return (round(value,6),quality,round(packing,6))

    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        seen=set()
        for name,boxes,report in self._placements(nodes,docs,seq,assocs,member,lanes,original):
            signature=(tuple((n,tuple(round(v,3) for v in b)) for n,b in sorted(boxes.items())),tuple(sorted(report.get('reserved_captions',{}).items())))
            if signature in seen:continue
            seen.add(signature)
            yield name,boxes,report

    def _placements(self,nodes,docs,seq,assocs,member,lanes,original):
        # These Y coordinates belong to the erased neutral model: they encode
        # graph distance from starts, never the teacher's visual role order.
        lanes={l:lanes[l] for l in sorted(lanes,key=lambda l:(original[l][1],l))}
        from .micro_episodes import micro_proposal
        for vertical in (True,False):
            try:
                boxes,report=micro_proposal(nodes,docs,seq,assocs,member,lanes,original,vertical_secondary=vertical)
                report=reserve_flow_labels(boxes,report,nodes,docs,seq,lanes)
                yield f'inline-episodes-secondary-vertical-{int(vertical)}',boxes,report
                from .lane_ordering import reorder_lanes
                changed,detail=reorder_lanes(boxes,report,nodes,docs,seq,member,lanes,self.role_order or 'auto')
                yield f'inline-episodes-secondary-vertical-{int(vertical)}-roles',changed,detail
            except ValueError:continue
        from .human_search import HumanStyleBackend
        # Preserve the previous cold constructor as a genuine graph-only
        # candidate. It is not an archived layout or an external incumbent.
        for name,boxes,report in HumanStyleBackend.placements(self,nodes,docs,seq,assocs,member,lanes,original):
            yield 'legacy-cold-'+name,boxes,report
        from .stage_episodes import stage_proposal
        try:
            boxes,report=stage_proposal(nodes,docs,seq,assocs,member,lanes,original)
            from .block_compaction import compact_blocks
            packed,packed_report=compact_blocks(boxes,report,nodes,docs,seq,member,lanes,gap=32,stack=False)
            packed_report=reserve_flow_labels(packed,packed_report,nodes,docs,seq,lanes)
            yield 'numbered-episodes-packed',packed,packed_report
            report=reserve_flow_labels(boxes,report,nodes,docs,seq,lanes)
            yield 'numbered-episodes',boxes,report
            from .lane_ordering import reorder_lanes
            changed,detail=reorder_lanes(packed,packed_report,nodes,docs,seq,member,lanes,self.role_order or 'auto')
            yield 'numbered-episodes-roles',changed,detail
        except ValueError:pass
        from .spine_episodes import spine_proposal
        for wrap,attach_next in ((False,False),):
            try:
                boxes,report=spine_proposal(nodes,docs,seq,assocs,member,lanes,original,wrap=wrap,attach_next=attach_next)
                if self.role_order is not None:
                    from .lane_ordering import reorder_lanes
                    boxes,report=reorder_lanes(boxes,report,nodes,docs,seq,member,lanes,self.role_order)
                yield f'role-spine-wrap-{int(wrap)}-next-{int(attach_next)}',boxes,report
                if self.role_order is None:
                    from .lane_ordering import reorder_lanes
                    changed,detail=reorder_lanes(boxes,report,nodes,docs,seq,member,lanes,'auto')
                    yield f'role-spine-wrap-{int(wrap)}-next-{int(attach_next)}-roles',changed,detail
            except ValueError:continue
        # Role order starts from graph distance; XML listing has no visual meaning.
        for rows,seed,vertical in ((2,23,False),(3,71,True)):
            try:
                boxes,report=episode_proposal(nodes,docs,seq,assocs,member,lanes,original,rows=rows,seed=seed,vertical=vertical)
                if self.role_order is not None:
                    from .lane_ordering import reorder_lanes
                    boxes,report=reorder_lanes(boxes,report,nodes,docs,seq,member,lanes,self.role_order)
                yield f'episode-rows-{rows}-seed-{seed}-vertical-{int(vertical)}',boxes,report
            except ValueError:continue
        # Existing cold placements remain available; no external incumbent or
        # source coordinates may be used as a fallback.
        from .block_compaction import compact_blocks
        from .lane_ordering import reorder_lanes
        for name,boxes,report in super().placements(nodes,docs,seq,assocs,member,lanes,original):
            if not name.startswith('semantic-'):continue
            # Packing may share empty space between unrelated local rows, while
            # preserving the chosen chain orientation and all measured labels.
            boxes,report=reorder_lanes(boxes,report,nodes,docs,seq,member,lanes,self.role_order or 'auto')
            try:
                packed,detail=compact_blocks(boxes,report,nodes,docs,seq,member,lanes,gap=32,stack=False)
                detail=reserve_flow_labels(packed,detail,nodes,docs,seq,lanes)
                yield name+'-episode-packed',packed,detail
            except ValueError:pass
            report=reserve_flow_labels(boxes,report,nodes,docs,seq,lanes)
            yield name+'-role-stable',boxes,report
