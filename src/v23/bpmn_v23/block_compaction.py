"""Fold short generated same-role chains, then pack measured occupied space.

Only geometry changes. Labels and information glyphs travel with their owner;
all task sizes and all graph identities remain intact. Routing follows packing.
"""
from collections import defaultdict,Counter
from bpmn_refkit.model import TAG_TASK,TAG_GATE
from .readability import graph_returns
from .typography import text_layout,width


def compact_blocks(boxes,report,nodes,docs,seq,member,lanes,gap=24,stack=True,task_pairs_only=False,secondary_checks=False):
    out=dict(boxes);caps=dict(report.get('reserved_captions',{}));owners=report['document_owners'];by_owner=defaultdict(list)
    for d,n in owners.items():by_owner[n].append(d)
    cy=lambda n:boxes[n][1]+boxes[n][3]/2
    cx=lambda n:boxes[n][0]+boxes[n][2]/2
    # Rows come from the generated candidate, never from the original input DI.
    rows={n:tuple(v) for n,v in report['axis_rows'].items()};row_nodes=defaultdict(list)
    for n in nodes:row_nodes[rows[n]].append(n)
    returns=graph_returns(nodes,seq);forward={(u,v) for i,u,v,_ in seq if i not in returns};incoming=defaultdict(set);outgoing=defaultdict(set)
    for u,v in forward:
        if member[u]==member[v]:outgoing[u].add(v);incoming[v].add(u)
    primary=Counter(member[n] for n in nodes if nodes[n]['kind'] in TAG_TASK).most_common(1)[0][0]
    groups=[];node_group={};node_row={};folded=[]
    for row,ids in sorted(row_nodes.items()):
        ordered=sorted(ids,key=lambda n:(cx(n),n));pairs=[];i=0
        while i<len(ordered):
            a=ordered[i];pair=[a]
            if stack and i+1<len(ordered):
                b=ordered[i+1]
                suitable=(a,b) in forward and len(outgoing[a])==1 and (len(incoming[b])==1 or secondary_checks and nodes[a]['kind'] in TAG_TASK and nodes[b]['kind'] in TAG_TASK) and nodes[a]['kind'] in TAG_TASK|TAG_GATE and nodes[b]['kind'] in TAG_TASK|TAG_GATE
                if task_pairs_only:suitable=suitable and (nodes[a]['kind'] in TAG_TASK and nodes[b]['kind'] in TAG_TASK or secondary_checks and member[a]!=primary and nodes[a]['kind'] in TAG_TASK and nodes[b]['kind'] in TAG_GATE)
                if suitable:pair.append(b);i+=1
            pairs.append(pair);i+=1
        current=0.
        for pair in pairs:
            gid=len(groups);anchor=cx(pair[0]);positions={pair[0]:current};direction=1
            if len(pair)==2:
                a,b=pair;step=(boxes[a][3]+boxes[b][3])/2+gap
                direction=1 if current<=0 else -1;positions[b]=current+direction*step;current=positions[b]
                folded.append({'nodes':pair,'direction':'down' if direction==1 else 'up'})
            groups.append({'row':row,'anchor':anchor,'nodes':pair,'pieces':[]})
            for at,n in enumerate(pair):
                node_group[n]=gid;node_row[n]=row;old=boxes[n];x=anchor-old[2]/2;y=positions[n]-old[3]/2;out[n]=(x,y,old[2],old[3])
                first_side=-direction if at==0 else direction
                # Keep the connector between stacked nodes free. Captions and
                # data sit beyond the two ends of the short vertical chain.
                if n in caps:
                    ow=boxes[n];oldcap=report['reserved_captions'][n]
                    side=first_side if len(pair)==2 else (-1 if oldcap[1]+oldcap[3]/2<cy(n) else 1)
                    w,h=oldcap[2:];caps[n]=(anchor-w/2,y-h-7 if side<0 else y+old[3]+7,w,h)
                bounds=[out[n]]+([caps[n]] if n in caps else [])
                top=min(b[1] for b in bounds);bottom=max(b[1]+b[3] for b in bounds)
                for index,d in enumerate(sorted(by_owner[n])):
                    db=boxes[d];dc=caps.get(d);rects=[db]+([dc] if dc else [])
                    left=min(b[0] for b in rects);right=max(b[0]+b[2] for b in rects);up=min(b[1] for b in rects);down=max(b[1]+b[3] for b in rects)
                    side=first_side if len(pair)==2 else (-1 if index%2==0 else 1);nx=anchor-(right-left)/2;ny=top-12-(down-up) if side<0 else bottom+12
                    out[d]=(nx+db[0]-left,ny+db[1]-up,db[2],db[3])
                    if dc:caps[d]=(nx+dc[0]-left,ny+dc[1]-up,dc[2],dc[3])
                    if side<0:top=ny
                    else:bottom=ny+down-up
                pieces=[('box',n,out[n])]
                if n in caps:pieces.append(('caption',n,caps[n]))
                for d in by_owner[n]:
                    pieces.append(('box',d,out[d]))
                    if d in caps:pieces.append(('caption',d,caps[d]))
                groups[gid]['pieces'].extend(pieces)
    # Internal labelled vertical links need a real local text bay before
    # routing. This avoids spending their short connector on a long caption.
    reserved_flows=[]
    for i,u,v,name in seq:
        if not name or node_group[u]!=node_group[v]:continue
        group=groups[node_group[u]];a,b=out[u],out[v]
        if abs(a[0]+a[2]/2-b[0]-b[2]/2)>.01:continue
        w=min(140,max(80,width(name,12)*.55));h=text_layout(name,w,1000,(12,),2,1)['required_height']
        x=group['anchor']+max(a[2],b[2])/2+8;y=(a[1]+a[3]/2+b[1]+b[3]/2)/2-h/2
        caps[i]=(x,y,w,h);group['pieces'].append(('caption',i,caps[i]));reserved_flows.append(i)
    # Pack rows by their true occupied rectangles. Disjoint parts of a role
    # may share height; no blanket empty row is inserted between them.
    cursor=min(boxes[l][1] for l in lanes);role_order=sorted(lanes,key=lambda l:boxes[l][1]);rows_pieces=defaultdict(list)
    for group in groups:rows_pieces[group['row']].extend(group['pieces'])
    translated={}
    for role in role_order:
        top=cursor;placed=[]
        role_rows=sorted((r for r in rows_pieces if r[0]==role),key=lambda r:min(cy(n) for n in row_nodes[r]))
        for row in role_rows:
            pieces=rows_pieces[row];bounds=[top+16-min(b[1] for _,_,b in pieces)]
            for _,_,b in pieces:
                for q in placed:
                    if min(b[0]+b[2]+8,q[0]+q[2])-max(b[0]-8,q[0])>0:bounds.append(q[1]+q[3]+12-b[1])
            dy=max(bounds);translated[row]=dy;placed.extend((x,y+dy,w,h) for _,_,(x,y,w,h) in pieces)
        bottom=max((y+h for x,y,w,h in placed),default=top+76);cursor=max(top+108,bottom+16);x,_,w,_=boxes[role];out[role]=(x,top,w,cursor-top)
    for group in groups:
        dy=translated[group['row']]
        for kind,n,(x,y,w,h) in group['pieces']:
            value=(x,y+dy,w,h)
            if kind=='box':out[n]=value
            else:caps[n]=value
    # Global column constraints retain reading order, but remove every unused
    # horizontal gap. Rectangles sharing height impose actual separation.
    columns=defaultdict(list)
    for group in groups:
        key=round(group['anchor'],3)
        for kind,n,_ in group['pieces']:
            b=out[n] if kind=='box' else caps[n];columns[key].append((kind,n,b))
    anchors=sorted(columns);position={};left=min(boxes[l][0] for l in lanes)+56
    named_constraints=defaultdict(list)
    for i,u,v,name in seq:
        if not name or member[u]!=member[v] or node_group[u]==node_group[v]:continue
        if task_pairs_only and not (len(name)>10 and len(groups[node_group[u]]['nodes'])==2 and nodes[u]['kind'] in TAG_GATE):continue
        a=round(groups[node_group[u]]['anchor'],3);b=round(groups[node_group[v]]['anchor'],3)
        if a>=b:continue
        rw=max(q[0]+q[2]-a for _,_,q in columns[a]);lw=min(q[0]-b for _,_,q in columns[b])
        label_width=min(130,max(24,width(name,12)*.55))
        named_constraints[b].append((a,rw-lw+label_width+16))
    for index,key in enumerate(anchors):
        pieces=columns[key];limits=[left-min(b[0]-key for _,_,b in pieces)]
        if index:limits.append(position[anchors[index-1]])
        for previous in anchors[:index]:
            for _,_,b in pieces:
                for _,_,a in columns[previous]:
                    if min(a[1]+a[3]+8,b[1]+b[3])-max(a[1]-8,b[1])>0:
                        limits.append(position[previous]+a[0]+a[2]-previous-(b[0]-key)+gap)
        limits.extend(position[a]+distance for a,distance in named_constraints[key])
        position[key]=max(limits)
    for key,pieces in columns.items():
        dx=position[key]-key
        for kind,n,(x,y,w,h) in pieces:
            if kind=='box':out[n]=(x+dx,y,w,h)
            else:caps[n]=(x+dx,y,w,h)
    right=max([b[0]+b[2] for n,b in out.items() if n in nodes or n in docs]+[b[0]+b[2] for b in caps.values()])+24
    top=min(out[l][1] for l in lanes)
    for n,b in list(out.items()):
        if n in nodes or n in docs:continue
        if n in lanes:out[n]=(b[0],b[1],right-b[0],b[3])
        else:out[n]=(b[0],top,right-b[0],cursor-top)
    before_width=max(boxes[l][2] for l in lanes);before_height=sum(boxes[l][3] for l in lanes)
    detail={'method':'local two-node vertical chains; owner envelopes; occupied-space row and column constraints','folded_chains':folded,'gap':gap,'before_width':before_width,'after_width':right-min(out[l][0] for l in lanes),'before_height':before_height,'after_height':cursor-top,'node_sizes_preserved':True}
    return out,{**report,'reserved_captions':caps,'local_block_compaction':detail,'reserved_flow_captions':reserved_flows}
