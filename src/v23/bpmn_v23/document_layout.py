"""Local information attachments; never use a document as a workflow column.

One immutable semantic reference may serve several activities. Keep a fixed
nearest linked activity as its anchor and measure the other links separately.
"""
import math
from bpmn_refkit.model import TAG_GATE,TAG_EVENT
from bpmn_refkit.geometry import bbox_intersect_seg
from .quality import segment_overlap,contacts,path_length


def box_gap(a,b):
    return math.hypot(max(a[0]-b[0]-b[2],b[0]-a[0]-a[2],0),max(a[1]-b[1]-b[3],b[1]-a[1]-a[3],0))


def owners_for(nodes,docs,assocs,boxes):
    result={}
    for d in docs:
        linked={v if u==d else u for _,u,v,_ in assocs if d in (u,v)}&nodes.keys()
        if linked:result[d]=min(linked,key=lambda n:(box_gap(boxes[d],boxes[n]),n))
    return result


def attachment_metrics(nodes,docs,assocs,boxes,paths,owners=None):
    owners=owners if owners is not None else owners_for(nodes,docs,assocs,boxes)
    gaps={d:round(box_gap(boxes[d],boxes[n]),3) for d,n in owners.items()}
    return {'fixed_owners':owners,'anchor_gaps':gaps,'mean_anchor_gap':sum(gaps.values())/max(1,len(gaps)),
            'association_bends':sum(max(0,len(paths[i])-2) for i,_,_,_ in assocs),
            'association_length':sum(path_length(paths[i]) for i,_,_,_ in assocs),
            'consumer_links':[{'id':i,'gap':round(box_gap(boxes[u],boxes[v]),3)} for i,u,v,_ in assocs]}


def ray_port(box,target,kind=''):
    x,y,w,h=box;cx=x+w/2;cy=y+h/2;dx=target[0]-cx;dy=target[1]-cy
    if not dx and not dy:raise ValueError('Coincident information association terminals')
    if kind in TAG_GATE:t=1/(abs(dx)/(w/2)+abs(dy)/(h/2))
    elif kind in TAG_EVENT:t=1/math.hypot(dx/(w/2),dy/(h/2))
    else:t=min(w/2/abs(dx) if dx else math.inf,h/2/abs(dy) if dy else math.inf)
    return (round(cx+t*dx,4),round(cy+t*dy,4))


def straight_link(u,v,boxes,nodes):
    centre=lambda n:(boxes[n][0]+boxes[n][2]/2,boxes[n][1]+boxes[n][3]/2)
    return [ray_port(boxes[u],centre(v),nodes.get(u,{}).get('kind','')),ray_port(boxes[v],centre(u),nodes.get(v,{}).get('kind',''))]


def safe_link(eid,points,boxes,uv,others,headers=(),nodes=None):
    u,v=uv[eid];a,b=points
    if math.dist(a,b)<1:return False
    from .contours import on_contour
    nodes=nodes or {}
    def inside(p,n):
        x,y,w,h=boxes[n];dx=(p[0]-x-w/2)/(w/2);dy=(p[1]-y-h/2)/(h/2);kind=nodes.get(n,{}).get('kind','')
        if kind in TAG_GATE:return abs(dx)+abs(dy)<1-1e-5
        if kind in TAG_EVENT:return dx*dx+dy*dy<1-1e-5
        return abs(dx)<1-1e-5 and abs(dy)<1-1e-5
    fraction=min(.01,.1/math.dist(a,b))
    for p,q,n in ((a,b,u),(b,a,v)):
        if not on_contour(p,boxes[n],nodes.get(n,{}).get('kind','')) or inside((p[0]+(q[0]-p[0])*fraction,p[1]+(q[1]-p[1])*fraction),n):return False
    for n,box in boxes.items():
        if n not in (u,v) and bbox_intersect_seg(box,a,b,clearance=-2 if str(n).startswith('__text_') else -8):return False
    if any(bbox_intersect_seg(h,a,b,clearance=0) for h in headers):return False
    if any(segment_overlap(a,b,c,d)>.01 for ps in others.values() for c,d in zip(ps,ps[1:])):return False
    return True


def refine_links(nodes,docs,seq,assocs,boxes,paths,headers=()):
    uv={i:(u,v) for i,u,v,_ in seq+assocs};result={i:list(ps) for i,ps in paths.items()};changes=[]
    obstacles={n:b for n,b in boxes.items() if n in nodes or n in docs}
    for i,u,v,_ in assocs:
        # Only information links incident to an actual document/store qualify.
        if u not in docs and v not in docs:continue
        candidate=straight_link(u,v,boxes,nodes);others={j:ps for j,ps in result.items() if j!=i}
        if not safe_link(i,candidate,obstacles,uv,others,headers,nodes):continue
        old=result[i]
        before=len(contacts({**others,i:old},uv));after=len(contacts({**others,i:candidate},uv))
        if after<=before and path_length(candidate)<=path_length(old)+.01 and (len(candidate)<len(old) or path_length(candidate)<path_length(old)-.1):
            result[i]=candidate;changes.append(i)
    return result,changes
