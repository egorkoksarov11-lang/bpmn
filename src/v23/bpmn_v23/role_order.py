"""Order visual lanes by their actual handoffs; never change lane membership."""
from itertools import permutations
from bpmn_refkit.geometry import bbox_intersect_seg


def reorder_boxes(boxes,order,nodes,docs,membership,doc_owners):
    result=dict(boxes);delta={};cursor=min(boxes[l][1] for l in order)
    for lane in order:
        x,y,w,h=boxes[lane];delta[lane]=cursor-y;result[lane]=(x,cursor,w,h);cursor+=h
    for n in nodes|docs:
        lane=membership.get(n) if n in nodes else membership.get(doc_owners[n])
        x,y,w,h=boxes[n];result[n]=(x,y+delta[lane],w,h)
    return result


def candidate_orders(boxes,nodes,seq,membership,lanes,limit=2):
    original=tuple(sorted(lanes,key=lambda l:boxes[l][1]));index={l:i for i,l in enumerate(original)}
    centers={n:(boxes[n][0]+boxes[n][2]/2,boxes[n][1]+boxes[n][3]/2) for n in nodes}
    starts={membership[n] for n,o in nodes.items() if o['kind']=='startEvent' and n in membership}
    def cost(order):
        delta={};cursor=min(boxes[l][1] for l in original)
        for lane in order:delta[lane]=cursor-boxes[lane][1];cursor+=boxes[lane][3]
        xy={n:(x,y+delta[membership[n]]) for n,(x,y) in centers.items()}
        rectangles={n:(boxes[n][0],boxes[n][1]+delta[membership[n]],boxes[n][2],boxes[n][3]) for n in nodes}
        edges=[(u,v,xy[u],xy[v]) for _,u,v,_ in seq];crossings=through=0;length=0
        def orient(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        for i,(u,v,a,b) in enumerate(edges):
            length+=abs(a[0]-b[0])+abs(a[1]-b[1])
            for uu,vv,c,d in edges[i+1:]:
                if u in (uu,vv) or v in (uu,vv):continue
                if max(a[0],b[0])<min(c[0],d[0]) or max(c[0],d[0])<min(a[0],b[0]):continue
                if orient(a,b,c)*orient(a,b,d)<-.01 and orient(c,d,a)*orient(c,d,b)<-.01:crossings+=1
            for n,rect in rectangles.items():
                if n in (u,v):continue
                x,y,w,h=rect
                if max(a[0],b[0])<x or min(a[0],b[0])>x+w or max(a[1],b[1])<y or min(a[1],b[1])>y+h:continue
                if bbox_intersect_seg(rect,a,b,clearance=2):through+=1
        movement=sum(abs(i-index[l]) for i,l in enumerate(order))
        start_penalty=sum(order.index(l) for l in starts)*5
        return crossings*30+through*60+length*.01+movement*2+start_penalty
    if len(original)<=7:options=list(permutations(original))
    else:
        options=[original,original[::-1]]
        for i in range(len(original)-1):
            p=list(original);p[i],p[i+1]=p[i+1],p[i];options.append(tuple(p))
    ranked=sorted(((cost(order),order) for order in options),key=lambda p:(p[0],p[1]))
    return [{'order':list(order),'estimated_cost':round(value,3),'method':'handoff crossings and blocked straight-line hints; geometry only'} for value,order in ranked if order!=original][:limit]
