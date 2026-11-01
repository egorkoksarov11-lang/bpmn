"""Geometric path quality, including ambiguous contacts missed by strict crossings."""
from collections import defaultdict
from bpmn_refkit.geometry import segment_overlap


def intersection(a,b,c,d):
    """Inclusive orthogonal intersection (a grid subdivision must not hide it)."""
    eps=1e-5
    if abs(a[1]-b[1])<eps and abs(c[0]-d[0])<eps:
        if min(a[0],b[0])-eps<=c[0]<=max(a[0],b[0])+eps and min(c[1],d[1])-eps<=a[1]<=max(c[1],d[1])+eps:return (c[0],a[1])
    elif abs(a[0]-b[0])<eps and abs(c[1]-d[1])<eps:
        if min(c[0],d[0])-eps<=a[0]<=max(c[0],d[0])+eps and min(a[1],b[1])-eps<=c[1]<=max(a[1],b[1])+eps:return (a[0],c[1])
    return None


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
    return (len(touches),sum(max(0,len(ps)-2) for ps in paths.values()),round(sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for ps in paths.values() for a,b in zip(ps,ps[1:])),2))


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
    return (count,max(0,len(ps)-2),sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(ps,ps[1:])))
