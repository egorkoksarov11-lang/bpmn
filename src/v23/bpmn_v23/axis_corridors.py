"""Monotone transfer of current input wire corridors to the solved axes.

The business XML is never interpreted through or rewritten from these hints.
Every transferred edge must satisfy the current shape/clearance audit.
"""
from bisect import bisect_right
from statistics import median
from bpmn_refkit.geometry import compress
from .contours import bounding_ports
from .clearance import safe_poly
from .router import overlapping


def interpolator(anchors):
    values={}
    for old,new in anchors:values.setdefault(old,[]).append(new)
    pairs=sorted((old,median(new)) for old,new in values.items())
    if not pairs:raise ValueError('Empty axes')
    if any(b[1]<=a[1] for a,b in zip(pairs,pairs[1:])):raise ValueError('Nonmonotone target axes')
    def transform(v):
        if len(pairs)==1:return v-pairs[0][0]+pairs[0][1]
        k=max(0,min(len(pairs)-2,bisect_right([a for a,b in pairs],v)-1))
        a,b=pairs[k:k+2]
        return a[1]+(v-a[0])*(b[1]-a[1])/(b[0]-a[0])
    return transform


def mapped_routes(report,original,paths,boxes,nodes,obstacles,uv):
    fx=interpolator(report['mapped_axes']['x']);fy=interpolator(report['mapped_axes']['y'])
    bounds=bounding_ports(paths,uv,original,nodes);retained={}
    for eid in report['routing_priority']:
        if eid not in bounds:continue
        old=bounds[eid];u,v=uv[eid];p=[(round(fx(x),2),round(fy(y),2)) for x,y in old]
        a,b=boxes[u],boxes[v]
        if len(old)==2:
            if abs(old[0][0]-old[-1][0])<.01:
                lo=max(a[0],b[0])+3;hi=min(a[0]+a[2],b[0]+b[2])-3
                if lo>hi:continue
                x=max(lo,min(hi,p[0][0]));p=[(x,a[1]+a[3] if old[-1][1]>old[0][1] else a[1]),(x,b[1] if old[-1][1]>old[0][1] else b[1]+b[3])]
            elif abs(old[0][1]-old[-1][1])<.01:
                lo=max(a[1],b[1])+3;hi=min(a[1]+a[3],b[1]+b[3])-3
                if lo>hi:continue
                y=max(lo,min(hi,p[0][1]));p=[(a[0]+a[2] if old[-1][0]>old[0][0] else a[0],y),(b[0] if old[-1][0]>old[0][0] else b[0]+b[2],y)]
            else:continue
        else:
            for end,near,n in ((0,1,u),(-1,-2,v)):
                x,y,w,h=boxes[n]
                if abs(old[end][0]-old[near][0])<.01:
                    cx=max(x+3,min(x+w-3,p[end][0]));cy=y+h if old[near][1]>old[end][1] else y
                    p[end]=(cx,cy);p[near]=(cx,p[near][1])
                else:
                    cy=max(y+3,min(y+h-3,p[end][1]));cx=x+w if old[near][0]>old[end][0] else x
                    p[end]=(cx,cy);p[near]=(p[near][0],cy)
        p=compress(p)
        if len(p)>1 and safe_poly(eid,p,obstacles,uv) and not overlapping(p,retained):retained[eid]=p
    return retained
