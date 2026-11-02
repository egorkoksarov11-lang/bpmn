"""Geometric path quality, including ambiguous contacts missed by strict crossings."""
from collections import defaultdict
import math
from bpmn_refkit.geometry import segment_overlap as orthogonal_overlap


def intersection(a,b,c,d):
    """Inclusive orthogonal intersection (a grid subdivision must not hide it)."""
    eps=1e-5
    if abs(a[1]-b[1])<eps and abs(c[0]-d[0])<eps:
        if min(a[0],b[0])-eps<=c[0]<=max(a[0],b[0])+eps and min(c[1],d[1])-eps<=a[1]<=max(c[1],d[1])+eps:return (c[0],a[1])
    elif abs(a[0]-b[0])<eps and abs(c[1]-d[1])<eps:
        if min(c[0],d[0])-eps<=a[0]<=max(c[0],d[0])+eps and min(a[1],b[1])-eps<=c[1]<=max(a[1],b[1])+eps:return (a[0],c[1])
    # General segment intersection is required for the short diagonal
    # information associations used in the human references.
    if (abs(a[0]-b[0])<eps or abs(a[1]-b[1])<eps) and (abs(c[0]-d[0])<eps or abs(c[1]-d[1])<eps):return None
    rx,ry=b[0]-a[0],b[1]-a[1];sx,sy=d[0]-c[0],d[1]-c[1];den=rx*sy-ry*sx
    if abs(den)<1e-9:return None
    qx,qy=c[0]-a[0],c[1]-a[1];t=(qx*sy-qy*sx)/den;u=(qx*ry-qy*rx)/den
    if -1e-8<=t<=1+1e-8 and -1e-8<=u<=1+1e-8:return (round(a[0]+t*rx,5),round(a[1]+t*ry,5))
    return None


def segment_overlap(a,b,c,d):
    if (a[0]==b[0] or a[1]==b[1]) and (c[0]==d[0] or c[1]==d[1]):return orthogonal_overlap(a,b,c,d)
    dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
    if length<1e-8:return 0
    if abs(dx*(c[1]-a[1])-dy*(c[0]-a[0]))>1e-5*length or abs(dx*(d[1]-a[1])-dy*(d[0]-a[0]))>1e-5*length:return 0
    project=lambda p:((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length
    low,high=sorted((project(c),project(d)));return max(0,min(length,high)-max(0,low))


def path_length(points):return sum(math.dist(a,b) for a,b in zip(points,points[1:]))


def overlap_pairs(paths):
    return [(i,j) for k,(i,p) in enumerate(paths.items()) for j,q in list(paths.items())[k+1:] if any(segment_overlap(a,b,c,d)>.01 for a,b in zip(p,p[1:]) for c,d in zip(q,q[1:]))]


def contacts(paths,uv):
    found=[];items=list(paths.items())
    for i,(eid,ps) in enumerate(items):
        for other,qs in items[i+1:]:
            points=set()
            for a,b in zip(ps,ps[1:]):
                for c,d in zip(qs,qs[1:]):
                    p=intersection(a,b,c,d)
                    if p is None:continue
                    # Only a common semantic node AND a common terminal is a legitimate join.
                    shared=set(uv[eid])&set(uv[other])
                    terminal_ps={ps[0]:uv[eid][0],ps[-1]:uv[eid][1]}
                    terminal_qs={qs[0]:uv[other][0],qs[-1]:uv[other][1]}
                    if p in terminal_ps and p in terminal_qs and terminal_ps[p]==terminal_qs[p] and terminal_ps[p] in shared:continue
                    points.add(p)
            for p in sorted(points):found.append((eid,other,p))
    return found


def score(paths,uv):
    touches=contacts(paths,uv)
    return (len(touches),sum(max(0,len(ps)-2) for ps in paths.values()),round(sum(path_length(ps) for ps in paths.values()),2))


def burdens(paths,uv):
    result=defaultdict(int)
    for a,b,_ in contacts(paths,uv):result[a]+=1;result[b]+=1
    return result


def edge_score(eid,ps,others,uv):
    count=0
    terminals={ps[0]:uv[eid][0],ps[-1]:uv[eid][1]}
    for other,qs in others.items():
        points=set();other_terminals={qs[0]:uv[other][0],qs[-1]:uv[other][1]}
        for a,b in zip(ps,ps[1:]):
            for c,d in zip(qs,qs[1:]):
                p=intersection(a,b,c,d)
                if p is not None:
                    if p in terminals and p in other_terminals and terminals[p]==other_terminals[p]:continue
                    points.add(p)
        count+=len(points)
    return (count,max(0,len(ps)-2),path_length(ps))
