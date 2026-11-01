"""Keep wires off object borders; touching the intended terminal is the exception."""
from bpmn_refkit.geometry import bbox_intersect_seg
from bpmn_universal.engine import good_poly


def outward(a,b,box):
    x,y,w,h=box;eps=.05
    return (abs(a[0]-x)<eps and abs(a[1]-b[1])<eps and b[0]<a[0]-.01 or
            abs(a[0]-x-w)<eps and abs(a[1]-b[1])<eps and b[0]>a[0]+.01 or
            abs(a[1]-y)<eps and abs(a[0]-b[0])<eps and b[1]<a[1]-.01 or
            abs(a[1]-y-h)<eps and abs(a[0]-b[0])<eps and b[1]>a[1]+.01)


def segment_blocked(a,b,box,terminal=False,gap=8):
    x,y,w,h=box;eps=.05
    normal=(abs(a[0]-b[0])<eps and x-eps<=a[0]<=x+w+eps and (min(a[1],b[1])>=y+h-eps or max(a[1],b[1])<=y+eps) or
            abs(a[1]-b[1])<eps and y-eps<=a[1]<=y+h+eps and (min(a[0],b[0])>=x+w-eps or max(a[0],b[0])<=x+eps))
    if terminal and normal:
        return bbox_intersect_seg(box,a,b,clearance=0)
    return bbox_intersect_seg(box,a,b,clearance=-gap)


def safe_poly(eid,points,boxes,uv,gap=8):
    if not good_poly(eid,points,boxes,uv):return False
    u,v=uv[eid];last=len(points)-2
    if not outward(points[0],points[1],boxes[u]) or not outward(points[-1],points[-2],boxes[v]):return False
    for i,(a,b) in enumerate(zip(points,points[1:])):
        for n,box in boxes.items():
            if segment_blocked(a,b,box,n==u and i==0 or n==v and i==last,gap):return False
    return True
