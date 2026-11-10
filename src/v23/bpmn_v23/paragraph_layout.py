"""Fold a complete graph suffix as a new paragraph, preserving local geometry.

Breaks are chosen from the generated graph/geometry, never from step names or
supplied DI. Unlike moving one chain, later interactions move together.
"""
from collections import defaultdict
from .scratch_layout import semantic_document_owners
from .window_planner import extract_labels
from .readability import graph_returns
from .quality import path_length
from bpmn_refkit.model import TAG_TASK


def paragraph_candidates(state):
    nodes,seq,assocs,docs,member,lanes,boxes,paths=state[4:];caps=extract_labels(state[1]);owners=semantic_document_owners(nodes,docs,assocs,boxes)
    xs=sorted({round(boxes[n][0],1) for n in nodes});returns=graph_returns(nodes,seq);ranked=[]
    for cut in xs[1:-1]:
        moving={n for n in nodes if boxes[n][0]>=cut-1}
        if min(len(moving),len(nodes)-len(moving))<4:continue
        # No invented ordering of cyclic graphs: require a forward separation
        # of the acyclic backbone, allowing only explicit feedback across it.
        if any(u in moving and v not in moving for i,u,v,*_ in seq if i not in returns):continue
        boundary=[i for i,u,v,*_ in seq if (u in moving)!=(v in moving)]
        if len(boundary)>10:continue
        ranked.append((len(boundary),abs(len(moving)-len(nodes)*.5),cut,moving))
    for _,_,cut,moving in sorted(ranked,key=lambda r:r[:3])[:8]:
        new=dict(boxes);labels=dict(caps);delta={};left=max(boxes[l][0]+60 for l in lanes);dx=left-min(boxes[n][0] for n in moving)
        def pieces(n):
            out=[boxes[n]]+([caps[n]] if n in caps else [])
            for d,o in owners.items():
                if o==n:out.append(boxes[d]);out.extend([caps[d]] if d in caps else [])
            return out
        for lane in lanes:
            first=[b for n in nodes if member[n]==lane and n not in moving for b in pieces(n)]
            second=[b for n in moving if member[n]==lane for b in pieces(n)]
            if not second:continue
            dy=max((b[1]+b[3] for b in first),default=boxes[lane][1]+8)+28-min(b[1] for b in second) if first else 0
            for n in moving:
                if member[n]!=lane:continue
                delta[n]=(dx,dy)
        for n in nodes.keys()|docs.keys():
            owner=owners.get(n,n);dd=delta.get(owner,(0,0));b=boxes[n];new[n]=(b[0]+dd[0],b[1]+dd[1],*b[2:])
            if n in labels:b=labels[n];labels[n]=(b[0]+dd[0],b[1]+dd[1],*b[2:])
        # Rebuild role bands from measured pieces. Prefix activities in lower
        # roles follow the shift too, without losing their local connectors.
        cursor=min(boxes[l][1] for l in lanes)
        for lane in sorted(lanes,key=lambda l:(boxes[l][1],l)):
            ids=[n for n in nodes.keys()|docs.keys() if member.get(owners.get(n,n))==lane]
            rects=[new[n] for n in ids]+[labels[n] for n in ids if n in labels]
            top=min(b[1] for b in rects);bottom=max(b[1]+b[3] for b in rects);shift=cursor+16-top
            for n in ids:
                b=new[n];new[n]=(b[0],b[1]+shift,*b[2:])
                if n in labels:b=labels[n];labels[n]=(b[0],b[1]+shift,*b[2:])
            x,y,w,h=boxes[lane];height=max(96,bottom-top+32);new[lane]=(x,cursor,w,height);cursor+=height
        right=max(new[n][0]+new[n][2] for n in nodes.keys()|docs.keys())+32
        for lane in lanes:x,y,w,h=new[lane];new[lane]=(x,y,max(100,right-x),h)
        for n in set(boxes)-nodes.keys()-docs.keys()-lanes.keys():x,y,w,h=boxes[n];new[n]=(x,y,max(100,right-x),cursor-y)
        shifts={n:(new[n][0]-boxes[n][0],new[n][1]-boxes[n][1]) for n in nodes.keys()|docs.keys()}
        fixed={};uv={i:(u,v) for i,u,v,*_ in seq+assocs}
        for i,(u,v) in uv.items():
            if shifts[u]==shifts[v]:
                sx,sy=shifts[u];fixed[i]=[(x+sx,y+sy) for x,y in paths[i]]
                if i in labels:b=labels[i];labels[i]=(b[0]+sx,b[1]+sy,*b[2:])
        yield f'paragraph-cut-{cut:g}',new,labels,fixed
