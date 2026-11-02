"""Workflow axes first, documents as nearby separate information blocks."""
from lxml import etree as ET
from collections import Counter
from bpmn_universal.contract import Q,BD,DC
from .axis_layout import axis_proposal
from .document_layout import owners_for
from .responsive_labels import gap
from .typography import text_layout,width
import math


def attachment_axes(nodes,docs,seq,assocs,member,lanes,original,gap_size=28,compact_bays=False):
    owners=owners_for(nodes,docs,assocs,original)
    if len(owners)!=len(docs):raise ValueError('Unanchored document')
    base={n:b for n,b in original.items() if n not in docs}
    counts=dict(Counter(owners.values()));reserves={n:min(2,c) if compact_bays else c for n,c in counts.items()}
    out,report=axis_proposal(nodes,{},seq,[],member,lanes,base,gap_size,1,False,True,reserves)
    for n in out:
        if n not in nodes:
            x,y,w,h=out[n];out[n]=(x,y,w+96,h)
    occupied=[b for n,b in out.items() if n in nodes];captions={}
    for n,o in nodes.items():
        if o['kind']=='startEvent' and o.get('name'):
            x,y,w,h=out[n];lw=140;lh=text_layout(o['name'],lw,1000,(12,),2,1)['required_height']
            cap=(x+w/2-lw/2,y+h+7,lw,lh);captions[n]=cap;occupied.append(cap)
    corridors=[]
    for i,u,v,_ in seq:
        a,b=out[u],out[v];ac=(a[0]+a[2]/2,a[1]+a[3]/2);bc=(b[0]+b[2]/2,b[1]+b[3]/2)
        if abs(ac[1]-bc[1])<.1 and (a[0]+a[2]<=b[0] or b[0]+b[2]<=a[0]):
            left,right=(a,b) if ac[0]<bc[0] else (b,a);corridors.append((left[0]+left[2],ac[1]-8,right[0]-left[0]-left[2],16))
        elif abs(ac[0]-bc[0])<.1 and (a[1]+a[3]<=b[1] or b[1]+b[3]<=a[1]):
            top,bottom=(a,b) if ac[1]<bc[1] else (b,a);corridors.append((ac[0]-8,top[1]+top[3],16,bottom[1]-top[1]-top[3]))
    occupied.extend(corridors)
    def overlap(a,b):return gap(a,b)<8
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
        lane=out[member[owner]]
        def valid(b):return b[0]>=lane[0]+56 and b[1]>=lane[1]+8 and b[0]+b[2]<=lane[0]+lane[2]-8 and b[1]+b[3]<=lane[1]+lane[3]-8 and not any(overlap(b,o) for o in occupied)
        candidates.sort(key=lambda b:(gap(b,out[owner]),0 if (b[1]-y)*dy>=0 else 1,abs(b[0]+bw/2-x-w/2),b))
        block=next((b for b in candidates if valid(b)),None)
        if block is None:raise ValueError(f'No local document bay: {d}, owner={owner}, size={bw,bh}')
        bx,by,_,bh=block;out[d]=(bx,by+(bh-dh)/2,dw,dh)
        if name:captions[d]=(bx+dw+7,by+(bh-lh)/2,lw,lh)
        occupied.append(block)
    report.update(document_owners=owners,reserved_captions=captions,protected_direct_corridors=corridors,compact_information_bays=compact_bays,external_engine='activity-axes-local-attachments',family='workflow-and-information-blocks',responsive_tasks=True)
    return out,report
