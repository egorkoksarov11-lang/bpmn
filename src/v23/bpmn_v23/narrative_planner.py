"""Interaction regions and measured reading quality, independent of wording.

Regions overlap and may nest: a handoff is not cut at a role boundary. IDs are
opaque deterministic tie breakers; neither captions nor step numbers are parsed.
"""
from collections import defaultdict
from statistics import median
import math
from bpmn_refkit.model import TAG_TASK
from .graph_topology import recognize
from .readability import graph_returns
from .local_editing import physical_bends
from .quality import path_length,contacts
from .window_metrics import metrics as window_metrics
from .window_planner import extract_labels


def interaction_regions(nodes,seq,member):
    returns=graph_returns(nodes,seq);out=defaultdict(list);inc=defaultdict(list)
    for i,u,v,*_ in seq:
        if i not in returns:out[u].append(v);inc[v].append(u)
    graph=recognize({n:o['kind'] for n,o in nodes.items()},[(i,u,v) for i,u,v,*_ in seq],member)
    candidates=[]
    for r in graph['split_joins']+graph['natural_loops']:
        if 3<=len(r['nodes'])<=16:candidates.append((r['type'],tuple(r['nodes'])))
    for root in sorted(nodes):
        if len(inc[root])==len(out[root])==1:continue
        for nxt in sorted(out[root]):
            chain=[root,nxt]
            while len(out[chain[-1]])==len(inc[chain[-1]])==1:
                nxt=out[chain[-1]][0]
                if nxt in chain:break
                chain.append(nxt)
                if len(chain)>=12:break
            if len(chain)>=3:candidates.append(('strand',tuple(chain)))
    # A request/reply often straddles a split/join. Keep it as an overlapping
    # opportunity rather than assigning every activity to exactly one chunk.
    for b in sorted(nodes):
        for a in inc[b]:
            for c in out[b]:
                if member.get(a)==member.get(c) and member.get(a)!=member.get(b) and a!=c:
                    candidates.append(('request_reply',(a,b,c)))
    unique={}
    for kind,ids in candidates:
        key=frozenset(ids)
        if key not in unique:unique[key]={'kind':kind,'nodes':list(ids),'roles':sorted({member[n] for n in ids})}
    result=list(unique.values())
    for r in result:
        ss=set(r['nodes']);parents=[p for p in result if ss<set(p['nodes'])]
        r['parent_nodes']=min((p['nodes'] for p in parents),key=lambda p:(len(p),p),default=None)
        r['boundary_edges']=[i for i,u,v,*_ in seq if (u in ss)!=(v in ss)]
    return result


def reading_measure(state):
    _,root,_,_,nodes,seq,assocs,docs,member,lanes,boxes,paths=state
    labels=extract_labels(root);rects=[b for n,b in boxes.items() if n in nodes or n in docs]
    rects += [b for n,b in labels.items() if not(n in nodes and nodes[n]['kind'] in TAG_TASK)]
    points=[p for ps in paths.values() for p in ps]
    width=max([b[0]+b[2] for b in rects]+[p[0] for p in points])-min([b[0] for b in rects]+[p[0] for p in points])
    height=max([b[1]+b[3] for b in rects]+[p[1] for p in points])-min([b[1] for b in rects]+[p[1] for p in points])
    tw=median([boxes[n][2] for n in nodes if nodes[n]['kind'] in TAG_TASK] or [180]);length=sum(path_length(paths[i]) for i,*_ in seq)
    info=sum(path_length(paths[i]) for i,*_ in assocs);uv={i:(u,v) for i,u,v,*_ in seq+assocs}
    bends=sum(physical_bends(paths[i]) for i,*_ in seq);touches=len(contacts(paths,uv))
    out=defaultdict(list);inc=defaultdict(list)
    for i,u,v,*_ in seq:out[u].append(i);inc[v].append(i)
    serial=[i for i,u,v,*_ in seq if nodes[u]['kind'] in TAG_TASK and nodes[v]['kind'] in TAG_TASK and len(out[u])==len(inc[v])==1]
    broken=sum(physical_bends(paths[i])>0 for i in serial);wm=window_metrics(boxes,paths,nodes,seq,member,docs,assocs)
    area=width*height;n=max(1,len(nodes));packing=math.sqrt(area/(n*tw*76))
    loss=8*touches+length/tw+.55*bends+10*packing+3*broken+4*wm['serial_hairpins']+4*len(seq)*wm['parallel_pressure_fixed_units']
    return {'score':loss,'area':area,'width':width,'height':height,'length':length,'information_length':info,'bends':bends,'contacts':touches,
            'serial_links':len(serial),'broken_serial':broken,'hairpins':wm['serial_hairpins'],'crowding':wm['parallel_pressure_fixed_units']}


def prefer_reading(before,after):
    # Safety and semantics are audited separately. Never buy a small footprint
    # gain by losing an existing direct continuation or adding a crossing.
    return (after['contacts']<=before['contacts'] and after['hairpins']<=before['hairpins']
            and after['broken_serial']<=before['broken_serial']
            and after['information_length']<=before['information_length']*1.15+4
            and after['crowding']<=before['crowding']*1.15+.005
            and (after['area']<=before['area']*1.005 and after['length']<=before['length']*1.05
                 or after['area']<=before['area']*.8 and after['length']<=before['length']*1.15
                 or after['contacts']<before['contacts'] and after['area']<=before['area']*1.08 and after['length']<=before['length']*1.08)
            and after['score']<before['score']-.1)


def acceptable_trial(initial,incumbent,candidate):
    return prefer_reading(incumbent,candidate) and prefer_reading(initial,candidate)
