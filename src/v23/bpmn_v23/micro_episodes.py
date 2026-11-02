"""Compose the inside of a semantic phase, rather than making one tall column.

The main role follows an inline local spine. Requests, replies and repairs are
attached to actual task/gateway ports; phase width follows its real contents.
"""
from collections import Counter,defaultdict,deque
from bpmn_refkit.model import TAG_TASK
from .stage_episodes import semantic_stages
from .scratch_layout import semantic_document_owners
from .attachment_axes import attachment_axes
from .skyline_layout import compact_rows


def micro_proposal(nodes,docs,seq,assocs,member,lanes,original,*,vertical_secondary=True):
    motifs,stages=semantic_stages(nodes,seq,member,original);owner=motifs['owner'];pairs=motifs['pairs']
    primary=Counter(member[n] for n,o in nodes.items() if o['kind'] in TAG_TASK).most_common(1)[0][0]
    backbone=[n for c in motifs['components'] for n in c['backbone']];main_index={n:i for i,n in enumerate(backbone)}
    inc=defaultdict(set);out=defaultdict(set);actual_in=defaultdict(list);actual_out=defaultdict(list)
    for eid,u,v,_ in seq:
        if owner[u]!=owner[v]:
            inc[owner[v]].add(owner[u]);out[owner[u]].add(owner[v]);actual_in[owner[v]].append((u,v));actual_out[owner[u]].append((u,v))
    role_index={l:i for i,l in enumerate(lanes)};orient={};sizes={}
    for n in motifs['macros']:
        w,h=original[n][2:];g=pairs.get(n);orientation='right'
        if g and vertical_secondary and member[n]!=primary:
            predecessors=[u for u,v in actual_in[n] if member[u]!=member[n]]
            # Keep the incoming approach free. A review reached from below
            # puts its decision above; one reached from above puts it below.
            incoming=sum(role_index[member[u]]-role_index[member[n]] for u in predecessors)
            orientation='up' if incoming>0 else 'down'
        orient[n]=orientation
        if g:
            gw,gh=original[g][2:];sizes[n]=(w+28+gw,max(h,gh)) if orientation=='right' else (max(w,gw),h+24+gh)
        else:sizes[n]=(w,h)
    assigned={};phase_reports=[];phase_start=120
    for stage in sorted(set(stages.values())):
        allowed={n for n,s in stages.items() if s==stage};anchors=[n for n in backbone if n in allowed and member[n]==primary]
        if not anchors:
            local_primary=Counter(member[n] for n in allowed).most_common(1)[0][0]
            anchors=sorted((n for n in allowed if member[n]==local_primary),key=lambda n:(main_index.get(n,10**6),nodes[n].get('name',''),n))[:1]
        local={};occupied=defaultdict(list);cursor=0.
        def put(n,x,row):
            ww,hh=sizes[n]
            while any(min(x+ww+12,bx+bw)-max(x-12,bx)>0 for bx,bw in occupied[member[n],row]):row+=1
            local[n]=(x,row);occupied[member[n],row].append((x,ww))
        for n in anchors:put(n,cursor,0);cursor+=sizes[n][0]+28
        def nearest(n,adj):
            todo=deque([(n,0)]);seen={n};found=[];depth=None
            while todo:
                u,d=todo.popleft()
                if depth is not None and d>depth:break
                if u in local:found.append(u);depth=d;continue
                for v in sorted(adj[u]&allowed):
                    if v not in seen:seen.add(v);todo.append((v,d+1))
            return found
        def node_cx(n):
            macro=owner[n];left=local[macro][0]
            if macro!=n and orient[macro]=='right':return left+original[macro][2]+28+original[n][2]/2
            return left+original[macro][2]/2
        remaining=allowed-set(local)
        while remaining:
            n=min(remaining,key=lambda n:(-sum(v in local for v in inc[n]|out[n]),main_index.get(n,10**6),nodes[n].get('name',''),n))
            direct=[u for u,v in actual_in[n] if owner[u] in local]
            following=[v for u,v in actual_out[n] if owner[v] in local]
            if direct:cx=sum(node_cx(u) for u in direct)/len(direct)
            elif following:cx=sum(node_cx(v) for v in following)/len(following)
            else:
                neighbours=nearest(n,inc) or nearest(n,out) or anchors
                cx=sum(local[v][0]+original[v][2]/2 for v in neighbours)/len(neighbours)
            x=cx-original[n][2]/2;row=1 if member[n]==primary else 0
            put(n,x,row);remaining.remove(n)
        left=min(x for x,r in local.values());right=max(x+sizes[n][0] for n,(x,r) in local.items())
        for n,(x,row) in local.items():assigned[n]=(phase_start+x-left,row)
        phase_reports.append({'stage':stage,'macro_count':len(allowed),'inline_anchor_count':len(anchors),'width':right-left,'local_rows':max(r for x,r in local.values())+1})
        phase_start+=right-left+32
    row_heights=defaultdict(float)
    for n,(x,row) in assigned.items():row_heights[member[n],row]=max(row_heights[member[n],row],sizes[n][1])
    ys={};cursor=100
    for l in lanes:
        for row in sorted({r for n,(x,r) in assigned.items() if member[n]==l}):ys[l,row]=cursor;cursor+=row_heights[l,row]+160
        cursor+=80
    basis=dict(original)
    for n,(x,row) in assigned.items():
        w,h=original[n][2:];y=ys[member[n],row]+(original[pairs[n]][3]+24 if n in pairs and orient[n]=='up' else 0);basis[n]=(x,y,w,h)
        if n in pairs:
            g=pairs[n];gw,gh=original[g][2:]
            basis[g]=(x+w+28,y+h/2-gh/2,gw,gh) if orient[n]=='right' else (x+w/2-gw/2,y-gh-24 if orient[n]=='up' else y+h+24,gw,gh)
    for d,n in semantic_document_owners(nodes,docs,assocs,basis).items():
        x,y,w,h=basis[n];dw,dh=original[d][2:];basis[d]=(x,y+h+24,dw,dh)
    for i,l in enumerate(lanes):basis[l]=(30,65+i*1000,phase_start,1000)
    boxes,report=attachment_axes(nodes,docs,seq,assocs,member,lanes,basis,gap_size=28,compact_bays=True,overlap_corridors=True)
    boxes,report=compact_rows(boxes,report,nodes,docs,member,lanes,seq)
    report.update(external_engine='inline-micro-episodes',micro_phases=phase_reports,decision_directions=orient,source_geometry_used=False)
    return boxes,report
