"""Role-local graph blocks. Only topology/types/membership choose the structure."""
from collections import defaultdict, deque
import math
from statistics import median
from .readability import graph_returns
from .graph_topology import recognize


def relax_role_axes(nodes,docs,seq,assocs,member,lanes,boxes,report,iterations=24,movable=None):
    """Close role-local holes; only actual handoffs couple different roles.

    This operates on a newly generated candidate, never supplied source DI.
    Caption/document envelopes move with the activity, preserving measured ink.
    """
    from .scratch_layout import semantic_document_owners
    from .episode_layout import reserve_flow_labels
    owners=semantic_document_owners(nodes,docs,assocs,boxes);caps=report.get('reserved_captions',{})
    pieces={n:[boxes[n]] for n in nodes};group={n:n for n in nodes}
    for d,o in owners.items():pieces[o].append(boxes[d]);group[d]=o
    for n,b in caps.items():
        if n in group:pieces[group[n]].append(b)
    envelopes={n:(min(b[0] for b in ps),min(b[1] for b in ps),max(b[0]+b[2] for b in ps),max(b[1]+b[3] for b in ps)) for n,ps in pieces.items()}
    centers={n:boxes[n][0]+boxes[n][2]/2 for n in nodes};delta={n:0. for n in nodes}
    previous={n:[] for n in nodes};following={n:[] for n in nodes};neighbours={n:[] for n in nodes}
    for i,u,v,*_ in seq:
        neighbours[u].append(v);neighbours[v].append(u)
    for lane in lanes:
        ordered=sorted((n for n in nodes if member[n]==lane),key=lambda n:(envelopes[n][0],n))
        for i,a in enumerate(ordered):
            aa=envelopes[a]
            for b in ordered[i+1:]:
                bb=envelopes[b]
                if min(aa[3],bb[3])-max(aa[1],bb[1])>-.01:
                    previous[b].append(a);following[a].append(b)
    before=sum(abs(centers[u]-centers[v]) for _,u,v,*_ in seq)
    ordering=sorted(nodes,key=lambda n:(centers[n],n))
    solver='coordinate-descent'
    for sweep in range(iterations):
        changed=0
        for n in ordering if sweep%2==0 else reversed(ordering):
            x0,y0,x1,y1=envelopes[n];lane=boxes[member[n]]
            lower=max([lane[0]+60-x0]+[envelopes[p][2]+delta[p]+24-x0 for p in previous[n]])
            upper=min([float('inf')]+[envelopes[p][0]+delta[p]-24-x1 for p in following[n]])
            if lower>upper+.01:continue
            targets=sorted(centers[p]+delta[p] for p in neighbours[n])
            # The lower L1 minimizer closes ties toward the left reading margin;
            # averaging two neighbours preserves unnecessary empty corridors.
            desired=targets[(len(targets)-1)//2]-centers[n] if targets else lower
            value=round(max(lower,min(upper,desired)),2)
            changed+=abs(value-delta[n])>.05;delta[n]=value
        if not changed:break
    try:
        from scipy.optimize import linprog
        from scipy.sparse import lil_matrix
        ids=sorted(nodes);index={n:i for i,n in enumerate(ids)};edges=list(seq);count=len(ids);size=count+len(edges)+1
        constraints=[];rhs=[]
        def add(values,bound):constraints.append(values);rhs.append(bound)
        # Piece-level rather than oversized group-bbox constraints retain useful
        # interlocking caption bays without permitting actual ink collisions.
        for ai,a in enumerate(ids):
            for b in ids[ai+1:]:
                if member[a]!=member[b]:continue
                for ia,aa in enumerate(pieces[a]):
                    for ib,bb in enumerate(pieces[b]):
                        if min(aa[1]+aa[3],bb[1]+bb[3])-max(aa[1],bb[1])<=0:continue
                        separation=24 if ia==ib==0 else 8
                        if aa[0]+aa[2]<=bb[0]+.01:add({index[a]:1,index[b]:-1},bb[0]-centers[b]-(aa[0]+aa[2]-centers[a])-separation)
                        elif bb[0]+bb[2]<=aa[0]+.01:add({index[b]:1,index[a]:-1},aa[0]-centers[a]-(bb[0]+bb[2]-centers[b])-separation)
                        else:
                            # An allowed contour corner is a coupled anchor.
                            diff=centers[a]-centers[b]
                            add({index[a]:1,index[b]:-1},diff+.01);add({index[b]:1,index[a]:-1},-diff+.01)
        for k,(eid,u,v,*_) in enumerate(edges):
            t=count+k;add({index[u]:1,index[v]:-1,t:-1},0);add({index[v]:1,index[u]:-1,t:-1},0)
        for n in ids:add({index[n]:1,size-1:-1},-(envelopes[n][2]-centers[n]))
        matrix=lil_matrix((len(constraints),size))
        for row,values in enumerate(constraints):
            for col,value in values.items():matrix[row,col]=value
        costs=[.03]*count+[1.]*len(edges)+[.3]
        bounds=[]
        for n in ids:
            if movable is not None and n not in movable:bounds.append((centers[n],centers[n]))
            else:
                low=boxes[member[n]][0]+60-(envelopes[n][0]-centers[n])
                high=boxes[member[n]][0]+boxes[member[n]][2]-8-(envelopes[n][2]-centers[n]) if movable is not None else None
                bounds.append((low,high))
        bounds += [(0,None)]*(len(edges)+1)
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore',message='Unrecognized options detected')
            result=linprog(costs,A_ub=matrix.tocsr(),b_ub=rhs,bounds=bounds,method='highs',options={'time_limit':2.,'threads':1})
        if result.success:
            delta={n:round(float(result.x[index[n]])-centers[n],2) for n in nodes};solver='HiGHS-L1-envelope-constraints'
    except ImportError:pass
    if movable is not None:
        delta={n:(delta[n] if n in movable else 0.) for n in nodes}
    after=sum(abs(centers[u]+delta[u]-centers[v]-delta[v]) for _,u,v,*_ in seq)
    old_right=max(b[2] for b in envelopes.values());new_right=max(b[2]+delta[n] for n,b in envelopes.items())
    if after>before*1.02 or after>=before-.5 and new_right>=old_right-.5:
        raise ValueError('Role-local axis relaxation did not improve travel or footprint')
    out=dict(boxes);captions={}
    for n,b in boxes.items():
        if n in group:out[n]=(b[0]+delta[group[n]],b[1],*b[2:])
    for n,b in caps.items():
        if n in group:captions[n]=(b[0]+delta[group[n]],b[1],*b[2:])
    right=max([b[0]+b[2] for n,b in out.items() if n in group]+[b[0]+b[2] for b in captions.values()])+24
    for lane in lanes:
        x,y,w,h=boxes[lane];out[lane]=(x,y,max(100,right-x),h)
    for n in set(boxes)-group.keys()-lanes.keys():
        x,y,w,h=boxes[n];out[n]=(x,y,max(100,right-x),h)
    result={**report,'reserved_captions':captions,'reserved_flow_captions':[],
            'external_engine':'role-local-envelope-relaxation','source_geometry_used':False,
            'role_local_relaxation':{'center_wire_before':before,'center_wire_after':after,'iterations':sweep+1,'solver':solver}}
    return out,reserve_flow_labels(out,result,nodes,docs,seq,lanes)


def topology_order(nodes,seq):
    feedback=graph_returns(nodes,seq);inc={n:0 for n in nodes};out=defaultdict(list)
    for i,u,v,*_ in seq:
        if i not in feedback:out[u].append(v);inc[v]+=1
    ready=sorted(n for n in nodes if not inc[n]);order=[]
    while ready:
        n=ready.pop(0);order.append(n)
        for v in sorted(out[n]):
            inc[v]-=1
            if not inc[v]:ready.append(v);ready.sort()
    return order+sorted(set(nodes)-set(order)),feedback


def graph_blocks(nodes,seq,member,max_size=8):
    order,feedback=topology_order(nodes,seq);rank={n:i for i,n in enumerate(order)}
    regions=recognize({n:o['kind'] for n,o in nodes.items()},[(i,u,v) for i,u,v,*_ in seq],member)
    blocks=[];used=set()
    for region in sorted(regions['split_joins']+regions['natural_loops'],key=lambda r:(len(r['nodes']),tuple(r['nodes']))):
        group=set(region['nodes'])
        if 4<=len(group)<=max_size and not group&used:
            blocks.append(tuple(sorted(group,key=rank.get)));used|=group
    adjacent=defaultdict(set)
    for i,u,v,*_ in seq:
        if i not in feedback and member.get(u)==member.get(v):adjacent[u].add(v);adjacent[v].add(u)
    for n in order:
        if n in used:continue
        group=[];todo=deque([n])
        while todo and len(group)<max_size:
            v=todo.popleft()
            if v in used:continue
            used.add(v);group.append(v);todo.extend(sorted(adjacent[v]-used,key=rank.get))
        blocks.append(tuple(sorted(group,key=rank.get)))
    return sorted(blocks,key=lambda g:min(rank[n] for n in g))


def role_local_proposal(nodes,docs,seq,assocs,member,lanes,original,*,columns=2,vertical_pairs=True,reverse=False):
    from .attachment_axes import attachment_axes
    from .episode_layout import reserve_flow_labels
    from .scratch_layout import semantic_document_owners
    blocks=graph_blocks(nodes,seq,member);order,_=topology_order(nodes,seq);rank={n:i for i,n in enumerate(order)}
    # Regions can span roles. Their per-role pieces retain a common graph block.
    pieces=[]
    for index,block in enumerate(blocks):
        for lane in lanes:
            subset=tuple(n for n in block if member[n]==lane)
            if subset:pieces.append((min(rank[n] for n in subset),index,lane,subset))
    pieces.sort();basis=dict(original);placed={};occupied=defaultdict(list);assigned={};settings={}
    tw=median(original[n][2] for n in nodes);target_width=max(560,tw*4.5);gap=36
    for _,index,lane,group in pieces:
        cap=1 if vertical_pairs and len(group)==2 else min(columns,len(group))
        # Keep dimensions intact; exact glyph/caption envelopes are packed next.
        cellw=max(original[n][2] for n in group)+gap
        cellh=max(original[n][3] for n in group)+110
        local={}
        for j,n in enumerate(group):
            row,col=divmod(j,cap)
            if row%2:col=cap-1-col
            if reverse:col=cap-1-col
            local[n]=(col*cellw,row*cellh,*original[n][2:])
        left=min(b[0] for b in local.values());right=max(b[0]+b[2] for b in local.values());bottom=max(b[1]+b[3] for b in local.values())
        incoming=[(u,v) for _,u,v,*_ in seq if v in local and u in placed]
        prefs=[placed[u][0]+placed[u][2]/2-local[v][0]-local[v][2]/2 for u,v in incoming]
        prefer=median(prefs) if prefs else 100
        candidates={(max(100,prefer),0),(100,0)}
        for x,y,w,h in occupied[lane]:
            candidates.add((x+w+gap,0));candidates.add((max(100,x-(right-left)-gap),0))
            candidates.add((max(100,prefer),y+h+110))
        def valid(p):
            x,y=p;box=(x,y,right-left,bottom)
            return not any(min(x+box[2]+gap,a+c)-max(x-gap,a)>0 and min(y+box[3]+80,b+d)-max(y-80,b)>0 for a,b,c,d in occupied[lane])
        candidates=[p for p in candidates if valid(p)]
        if not candidates:raise ValueError('No role-local block slot')
        def cost(p):
            x,y=p;wire=sum(abs(x+local[v][0]+local[v][2]/2-(placed[u][0]+placed[u][2]/2)) for u,v in incoming)
            maxx=max([x+right-left]+[a+c for a,b,c,d in occupied[lane]])
            maxy=max([y+bottom]+[b+d for a,b,c,d in occupied[lane]])
            return wire+maxx*.2+maxy*.25+max(0,maxx-target_width)*2, maxx*maxy,p
        x,y=min(candidates,key=cost);occupied[lane].append((x,y,right-left,bottom));settings[f'{index}:{lane}']=cap
        for n,b in local.items():
            w,h=b[2:];placed[n]=(x+b[0]-left,y+b[1]+100+list(lanes).index(lane)*2000,w,h);basis[n]=placed[n];assigned[n]=index
    for i,lane in enumerate(lanes):basis[lane]=(30,65+i*2000,4000,1900)
    for d,n in semantic_document_owners(nodes,docs,assocs,basis).items():
        x,y,w,h=basis[n];basis[d]=(x,y+h+24,*original[d][2:])
    boxes,report=attachment_axes(nodes,docs,seq,assocs,member,lanes,basis,gap_size=28,compact_bays=True,overlap_corridors=True)
    report=reserve_flow_labels(boxes,report,nodes,docs,seq,lanes)
    report.update(external_engine='role-local-whole-blocks',source_geometry_used=False,whole_blocks=[list(g) for g in blocks],role_local_columns=settings,
                  names_or_step_numbers_used_for_structure=False,block_assignment=assigned)
    return boxes,report


from .episode_layout import EpisodeGraphBackend


class WholeBlockBackend(EpisodeGraphBackend):
    name='v23.6-role-local-whole-blocks'
    selection_policy='whole-blocks-validated-objective-v2'
    def candidate_rank(self,path,boxes,paths,uv,nodes,docs,seq):
        previous=super().candidate_rank(path,boxes,paths,uv,nodes,docs,seq)
        # Keep the calibrated reading objective. Adding a footprint/contact
        # premium here lost too much continuity in the four-case experiment.
        return previous
    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        old=iter(super().placements(nodes,docs,seq,assocs,member,lanes,original));seen=set()
        def emit(item):
            name,b,r=item;key=(tuple(sorted(b.items())),tuple(sorted(r.get('reserved_captions',{}).items())))
            if key not in seen:seen.add(key);yield item
        # Keep four existing diverse cold seeds before exploring new families.
        def extended(item):
            name,boxes,report=item
            yield from emit(item)
            try:
                b,r=relax_role_axes(nodes,docs,seq,assocs,member,lanes,boxes,report)
                yield from emit(('role-local--'+name,b,r))
            except ValueError:pass
        for _ in range(4):
            item=next(old,None)
            if item is not None:yield from emit(item)
        for columns,pairs,reverse in ((2,True,False),(3,True,False)):
            try:
                boxes,report=role_local_proposal(nodes,docs,seq,assocs,member,lanes,original,columns=columns,vertical_pairs=pairs,reverse=reverse)
                from .lane_ordering import reorder_lanes
                boxes,report=reorder_lanes(boxes,report,nodes,docs,seq,member,lanes,self.role_order or 'auto')
                yield from emit((f'whole-blocks-cols-{columns}-pairs-{int(pairs)}-reverse-{int(reverse)}',boxes,report))
                try:
                    b,r=relax_role_axes(nodes,docs,seq,assocs,member,lanes,boxes,report)
                    yield from emit((f'role-local--whole-blocks-cols-{columns}-pairs-{int(pairs)}-reverse-{int(reverse)}',b,r))
                except ValueError:pass
            except ValueError as error:
                self.placement_failures.append({'family':'whole-blocks','reason':str(error)})
        for item in old:yield from extended(item)
