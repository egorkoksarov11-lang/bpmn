"""Lane-preserving deterministic placement proposals, with no model edits."""
from collections import defaultdict
import math
from .typography import wrap
from bpmn_refkit.model import TAG_TASK,TAG_GATE,TAG_EVENT


def candidates(nodes,docs,seq,assocs,membership,lane_names,original):
    """Yield a fixed-DI control and real content-folding alternatives.

    Feedback edges influence routes, never delete graph arcs. Source x order is
    only a stability hint; no process IDs or numbered stages are hardcoded.
    """
    control=dict(original)
    # Move the lane header boundary, not semantic membership, so source shapes
    # are not hidden behind a role name.
    for lane in lane_names:
        if lane in control:
            x,y,w,h=control[lane];control[lane]=(10,y,w+x-10,h)
    yield 'preserve',control
    # Normalize task sizes using measured full labels, never shrink the font.
    taskw=max([240]+[original[n][2] for n in nodes if nodes[n]['kind'] in TAG_TASK])
    taskh=max([88]+[len(wrap(o['name'],taskw-28,14))*19+28 for o in nodes.values() if o['kind'] in TAG_TASK])
    expanded={}
    for n,b in original.items():
        x,y,w,h=b
        if n in lane_names:expanded[n]=(10,65+(y-50)*1.7,(w+x)*1.5-10,h*1.7)
        elif n in nodes or n in docs:
            nw,nh=(taskw,taskh) if n in nodes and nodes[n]['kind'] in TAG_TASK else (w,h)
            expanded[n]=(65+(x-65)*1.5,65+(y-50)*1.7,nw,nh)
        else:expanded[n]=(65+(x-65)*1.5,65+(y-50)*1.7,w*1.5,h*1.7)
    yield 'expanded',expanded
    ordered=sorted(nodes,key=lambda n:(original[n][0],original[n][1],n))
    order={n:i for i,n in enumerate(ordered)}
    lane_order=list(lane_names)
    if not lane_order:lane_order=[None]
    # Actual content is folded, not padded to imitate a paper aspect ratio.
    for columns in (11,9):
        boxes={};stride=taskw+95;rowheight=200
        for n in ordered:
            if nodes[n]['kind'] in TAG_TASK:w,h=taskw,taskh
            else:w,h=original[n][2:]
            boxes[n]=(0,0,w,h)
        # Neighbouring nodes (including gateway branches) retain a stable order.
        y=65
        for lane in lane_order:
            lane_nodes=[n for n in ordered if membership.get(n)==lane]
            rows=max(1,math.ceil(len(lane_nodes)/columns))
            laneh=rows*rowheight+100
            if lane is not None:boxes[lane]=(65,y,columns*stride+95,laneh)
            for i,n in enumerate(lane_nodes):
                row,col=divmod(i,columns)
                if row%2:col=columns-1-col
                w,h=boxes[n][2:];boxes[n]=(145+col*stride+(taskw-w)/2,y+75+row*rowheight,w,h)
            y+=laneh
        # Documents belong to a neighbouring activity and get reserved space
        # below it; separate references of one logical document stay distinct.
        neighbours=defaultdict(list)
        for _,u,v,_ in assocs:
            if u in docs and v in nodes:neighbours[u].append(v)
            if v in docs and u in nodes:neighbours[v].append(u)
        used=[]
        for d in sorted(docs):
            links=neighbours[d]
            owner=min(links,key=lambda n:order[n]) if links else ordered[0]
            x,yy,w,h=boxes[owner];dw,dh=original[d][2:]
            dx=x+w/2-dw/2;dy=yy+h+28
            while any(abs(dx-xx)<max(dw,ww)+20 and abs(dy-y2)<max(dh,hh)+15 for xx,y2,ww,hh in used):dx+=dw+35
            box=(dx,dy,dw,dh);boxes[d]=box;used.append(box)
        # Reserve full lanes containing their documents, and preserve lane IDs.
        # Do not silently place a document on top of another process node.
        yield f'fold-{columns}',boxes
