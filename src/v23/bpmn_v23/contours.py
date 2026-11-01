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
