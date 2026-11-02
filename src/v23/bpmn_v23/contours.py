"""True contour attachment for rectangular, diamond and elliptic BPMN shapes."""
import math
from bpmn_refkit.model import TAG_GATE,TAG_EVENT


def project(point,neighbour,box,kind):
    x,y,w,h=box;cx=x+w/2;cy=y+h/2;px,py=point
    if kind not in TAG_GATE|TAG_EVENT:return point
    if abs(py-neighbour[1])<.01:
        t=min(1,abs((py-cy)/(h/2)))
        factor=1-t if kind in TAG_GATE else math.sqrt(max(0,1-t*t))
        px=cx+(1 if neighbour[0]>=cx else -1)*w/2*factor
    elif abs(px-neighbour[0])<.01:
        t=min(1,abs((px-cx)/(w/2)))
        factor=1-t if kind in TAG_GATE else math.sqrt(max(0,1-t*t))
        py=cy+(1 if neighbour[1]>=cy else -1)*h/2*factor
    return (round(px,2),round(py,2))


def attach(paths,uv,boxes,nodes):
    result={}
    for eid,points in paths.items():
        points=list(points);u,v=uv[eid]
        if u in nodes:points[0]=project(points[0],points[1],boxes[u],nodes[u]['kind'])
        if v in nodes:points[-1]=project(points[-1],points[-2],boxes[v],nodes[v]['kind'])
        result[eid]=points
    return result


def on_contour(point,box,kind,tolerance=.8):
    px,py=point;x,y,w,h=box;cx=x+w/2;cy=y+h/2
    if kind in TAG_GATE:
        return abs(abs(px-cx)/(w/2)+abs(py-cy)/(h/2)-1)<=tolerance/min(w/2,h/2)
    if kind in TAG_EVENT:
        return abs(((px-cx)/(w/2))**2+((py-cy)/(h/2))**2-1)<=2*tolerance/min(w/2,h/2)
    return ((abs(px-x)<tolerance or abs(px-x-w)<tolerance) and y-tolerance<=py<=y+h+tolerance or
            (abs(py-y)<tolerance or abs(py-y-h)<tolerance) and x-tolerance<=px<=x+w+tolerance)


def label_hits_shape(rect,box,kind='',gap=0):
    """Actual diamond/ellipse corners are empty; a bounding-box hit is not ink."""
    x,y,w,h=box;rx,ry,rw,rh=rect;rx-=gap;ry-=gap;rw+=2*gap;rh+=2*gap
    if kind in TAG_GATE|TAG_EVENT:
        cx=x+w/2;cy=y+h/2;px=max(rx,min(rx+rw,cx));py=max(ry,min(ry+rh,cy));dx=abs(px-cx)/(w/2);dy=abs(py-cy)/(h/2)
        return dx+dy<1-1e-6 if kind in TAG_GATE else dx*dx+dy*dy<1-1e-6
    return min(rx+rw,x+w)-max(rx,x)>.01 and min(ry+rh,y+h)-max(ry,y)>.01


def bounding_ports(paths,uv,boxes,nodes):
    paths={eid:list(ps) for eid,ps in paths.items()}
    for eid,ps in paths.items():
        for index,near,n in [(0,1,uv[eid][0]),(-1,-2,uv[eid][1])]:
            if n not in nodes:continue
            x,y,w,h=boxes[n];px,py=ps[index];other=ps[near]
            ps[index]=(x+w if other[0]>x+w/2 else x,py) if abs(py-other[1])<.01 else (px,y+h if other[1]>y+h/2 else y)
    return paths

