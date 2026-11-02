"""Workflow axes first, documents as nearby separate information blocks."""
from lxml import etree as ET
from collections import Counter
from bpmn_universal.contract import Q,BD,DC
from .axis_layout import axis_proposal
from .document_layout import owners_for
from .responsive_labels import gap
from .typography import text_layout,width
from bpmn_refkit.model import TAG_GATE
from bpmn_refkit.geometry import bbox_intersect_seg
import math


def attachment_axes(nodes,docs,seq,assocs,member,lanes,original,gap_size=28,compact_bays=False,overlap_corridors=False):
    owners=owners_for(nodes,docs,assocs,original)
    if len(owners)!=len(docs):raise ValueError('Unanchored document')
    base={n:b for n,b in original.items() if n not in docs}
    counts=dict(Counter(owners.values()));reserves={n:min(2,c) if compact_bays else c for n,c in counts.items()}
    out,report=axis_proposal(nodes,{},seq,[],member,lanes,base,gap_size,1,False,True,reserves,flow_caption_reserve=overlap_corridors)
    for n in out:
        if n not in nodes:
            x,y,w,h=out[n];out[n]=(x,y,w+96,h)
    occupied=[b for n,b in out.items() if n in nodes];captions={}
    for n,o in nodes.items():
        if o['kind']=='startEvent' and o.get('name'):
            x,y,w,h=out[n];lw=140;lh=text_layout(o['name'],lw,1000,(12,),2,1)['required_height']
            cap=(x+w/2-lw/2,y+h+7,lw,lh);captions[n]=cap;occupied.append(cap)
    corridors=[]
    def clear_direct(u,v,a,b):
        return not any(bbox_intersect_seg(box,a,b,clearance=-8) for n,box in out.items() if n in nodes and n not in (u,v))
    for i,u,v,_ in seq:
        a,b=out[u],out[v];ac=(a[0]+a[2]/2,a[1]+a[3]/2);bc=(b[0]+b[2]/2,b[1]+b[3]/2)
        overlap_y=(max(a[1],b[1])+4,min(a[1]+a[3],b[1]+b[3])-4)
        overlap_x=(max(a[0],b[0])+4,min(a[0]+a[2],b[0]+b[2])-4)
        if (abs(ac[1]-bc[1])<.1 or overlap_corridors and overlap_y[1]>overlap_y[0]) and (a[0]+a[2]<=b[0] or b[0]+b[2]<=a[0]):
            left,right=(a,b) if ac[0]<bc[0] else (b,a);cy=(overlap_y[0]+overlap_y[1])/2
            if clear_direct(u,v,(left[0]+left[2],cy),(right[0],cy)):corridors.append((left[0]+left[2],cy-8,right[0]-left[0]-left[2],16))
        elif (abs(ac[0]-bc[0])<.1 or overlap_corridors and overlap_x[1]>overlap_x[0]) and (a[1]+a[3]<=b[1] or b[1]+b[3]<=a[1]):
            top,bottom=(a,b) if ac[1]<bc[1] else (b,a);cx=(overlap_x[0]+overlap_x[1])/2
            if clear_direct(u,v,(cx,top[1]+top[3]),(cx,bottom[1])):corridors.append((cx-8,top[1]+top[3],16,bottom[1]-top[1]-top[3]))
    occupied.extend(corridors)
    def overlap(a,b):return gap(a,b)<8
    external=[n for n,o in nodes.items() if o.get('name') and (o['kind'] in TAG_GATE or o['kind']=='endEvent')]
    for n in sorted(external,key=lambda n:(-len(nodes[n]['name']),n)):
        x,y,w,h=out[n];cx=x+w/2;cy=y+h/2;row=report['axis_rows'][n];lane=out[member[n]]
        half=max(out[v][3]/2 for v in nodes if report['axis_rows'][v]==row);possibilities=[]
        for lw in ((100,140,180) if nodes[n]['kind'] in TAG_GATE else (140,180,100)):
            lh=text_layout(nodes[n]['name'],lw,1000,(12,),2,1)['required_height']
            for offset in (0,-32,32,-64,64,-96,96,-128,128):
                above=(cx-lw/2+offset,cy-half-lh-8,lw,lh);below=(cx-lw/2+offset,cy+half+8,lw,lh)
                for side,b in enumerate((above,below) if nodes[n]['kind'] in TAG_GATE else (below,above)):
                    if b[0]<lane[0]+54 or b[1]<lane[1]+8 or b[0]+b[2]>lane[0]+lane[2]-8 or b[1]+b[3]>lane[1]+lane[3]-8:continue
                    if any(overlap(b,o) for o in occupied):continue
                    possibilities.append((abs(offset)*.15+side*12+lh*.1,b))
        if not possibilities:raise ValueError('No measured external caption bay: '+n)
        cap=min(possibilities,key=lambda p:(p[0],p[1]))[1];captions[n]=cap;occupied.append(cap)
    for d,owner in sorted(owners.items(),key=lambda x:(x[1],x[0])):
        x,y,w,h=out[owner];dw,dh=original[d][2:];name=docs[d].get('name','')
        lw=130;fit=text_layout(name,lw,1000,(12,),2,1);lh=fit['required_height'] if name else 0
        lw=min(lw,math.ceil(max(width(line,12) for line in fit['lines']))+4)
        bw=dw+7+lw;bh=max(dh,lh);candidates=[]
        # Keep the human preferred side as a tie-break, never put an information
        # reference on the sequence axis between two successive operations.
        dx=original[d][0]-original[owner][0];dy=original[d][1]-original[owner][1]
        for distance in (20,28,40,56,84,108):
            for shift in (0,-40,40,-80,80,-100,100,-180,180,-200,200):
                left=max(out[member[owner]][0]+56,x+w/2-bw/2+shift)
                candidates.extend([(left,y-distance-bh,bw,bh),(left,y+h+distance,bw,bh)])
            if distance<=56:
                for delta in (0,-24,24,-48,48):
                    candidates.extend([(x+w+distance,y+h/2-bh/2+delta,bw,bh),(x-distance-bw,y+h/2-bh/2+delta,bw,bh)])
        lane=out[member[owner]]
        def valid(b):return b[0]>=lane[0]+56 and b[1]>=lane[1]+8 and b[0]+b[2]<=lane[0]+lane[2]-8 and b[1]+b[3]<=lane[1]+lane[3]-8 and not any(overlap(b,o) for o in occupied)
        candidates.sort(key=lambda b:(gap(b,out[owner]),0 if (b[1]-y)*dy>=0 else 1,abs(b[0]+bw/2-x-w/2),b))
        block=next((b for b in candidates if valid(b)),None)
        if block is None:raise ValueError(f'No local document bay: {d}, owner={owner}, size={bw,bh}')
        bx,by,_,bh=block;mirror=bx+bw<=x
        out[d]=(bx+bw-dw if mirror else bx,by+(bh-dh)/2,dw,dh)
        if name:captions[d]=(bx if mirror else bx+dw+7,by+(bh-lh)/2,lw,lh)
        occupied.append(block)
    report.update(document_owners=owners,reserved_captions=captions,protected_direct_corridors=corridors,compact_information_bays=compact_bays,external_engine='activity-axes-local-attachments',family='workflow-and-information-blocks',responsive_tasks=True)
    return out,report
