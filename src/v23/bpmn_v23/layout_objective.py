"""Shared explicit readability objective; no names, numbers or reference DI."""
import math
from .local_editing import physical_bends
from .quality import path_length,contacts
from .window_metrics import metrics


def wire_cost(points,crossings=0):
    bends=physical_bends(points);length=path_length(points)
    jogs=sum(.01<math.dist(a,b)<12 for a,b in zip(points[1:-2],points[2:-1]))
    return 8*crossings+1.2*bends+length/200+1.5*(bends>=2)+.8*jogs+.15*max(0,length/600-1)**2


def objective(boxes,paths,nodes,seq,member,docs=None,assocs=None,labels=()):
    docs=docs or {};assocs=assocs or [];uv={i:(u,v) for i,u,v,*_ in seq+assocs};count=max(1,len(seq));reading=metrics(boxes,paths,nodes,seq,member,docs,assocs)
    touches=len(contacts(paths,uv));score=8*touches+sum(wire_cost(paths[i]) for i,*_ in seq)
    score+=1.5*count*(1-reading['weighted_simple_window_fraction'])+6*count*reading['parallel_pressure_fixed_units']
    pieces=list(boxes.values())+list(labels);points=[p for path in paths.values() for p in path]
    left=min([b[0] for b in pieces]+[p[0] for p in points]);top=min([b[1] for b in pieces]+[p[1] for p in points]);width=max([b[0]+b[2] for b in pieces]+[p[0] for p in points])-left;height=max([b[1]+b[3] for b in pieces]+[p[1] for p in points])-top
    packing=math.sqrt(width*height/(max(1,len(nodes))*200*80));overspan=max(0,width/(200*math.sqrt(max(1,len(nodes)))*1.8)-1)**2
    score+=count*(.4*packing+.4*overspan)
    return score,{'contacts':touches,'packing':packing,'area':width*height,'window_readability':reading}
