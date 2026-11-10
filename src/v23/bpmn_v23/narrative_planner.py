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
    # Maximal interactions are often too large to reshape safely. Add actual
    # serial subchains (including the approach to a decision), not arbitrary
    # BFS chunks. Overlap lets a turn be chosen at different activities.
    local_out={n:[v for v in out[n] if member.get(v)==member.get(n) and len(inc[v])==1] for n in nodes}
    seen_links=set()
    for root in sorted(nodes):
        for nxt in local_out[root]:
            if (root,nxt) in seen_links or len(out[root])!=1:continue
            chain=[root,nxt];seen_links.add((root,nxt))
            while len(out[chain[-1]])==1 and len(local_out[chain[-1]])==1:
                nxt=local_out[chain[-1]][0]
                if nxt in chain:break
                seen_links.add((chain[-1],nxt));chain.append(nxt)
            for size in (3,4,5):
                for start in range(max(0,len(chain)-size+1)):
                    candidates.append(('local_strand',tuple(chain[start:start+size])))
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
    info_lengths=[path_length(paths[i])/tw for i,*_ in assocs]
    bends=sum(physical_bends(paths[i]) for i,*_ in seq);touches=len(contacts(paths,uv))
    out=defaultdict(list);inc=defaultdict(list)
    for i,u,v,*_ in seq:out[u].append(i);inc[v].append(i)
    serial=[i for i,u,v,*_ in seq if nodes[u]['kind'] in TAG_TASK and nodes[v]['kind'] in TAG_TASK and len(out[u])==len(inc[v])==1]
    broken=sum(physical_bends(paths[i])>0 for i in serial);wm=window_metrics(boxes,paths,nodes,seq,member,docs,assocs)
    area=width*height;n=max(1,len(nodes));packing=math.sqrt(area/(n*tw*76))
    feedback=graph_returns(nodes,seq);forward=sorted(path_length(paths[i])/tw for i,*_ in seq if i not in feedback)
    jumps=sum(max(0,v-3)**2 for v in forward)
    span_loss=8*max(0,width/(tw*max(4,math.sqrt(n)*1.25))-1)**2
    loss=8*touches+length/tw+.55*bends+10*packing+3*broken+4*wm['serial_hairpins']+4*len(seq)*wm['parallel_pressure_fixed_units']+.6*jumps+span_loss
    return {'score':loss,'area':area,'width':width,'height':height,'length':length,'information_length':info,'bends':bends,'contacts':touches,
            'serial_links':len(serial),'broken_serial':broken,'hairpins':wm['serial_hairpins'],'crowding':wm['parallel_pressure_fixed_units'],
            'forward_max_task_units':max(forward,default=0),'forward_p90_task_units':forward[min(len(forward)-1,int(len(forward)*.9))] if forward else 0,
            'long_forward_count':sum(v>3 for v in forward),'forward_jump_loss':jumps,
            'information_mean_task_units':sum(info_lengths)/max(1,len(info_lengths)),'information_max_task_units':max(info_lengths,default=0),'horizontal_span_loss':span_loss}


def prefer_reading(before,after):
    # Safety and semantics are audited separately. Never buy a small footprint
    # gain by losing an existing direct continuation or adding a crossing.
    major_fold=((after['area']<=before['area']*.55 and after['length']<=before['length']*1.4
                 or after['area']<=before['area']*.75 and after.get('width',math.inf)<=before.get('width',0)*.75 and after['length']<=before['length']*1.5)
                and (after['broken_serial']<=before['broken_serial']
                     or before.get('serial_links',0)>=8 and after['broken_serial']<=before['broken_serial']+1
                     and after['broken_serial']<=math.floor(before['serial_links']*.2))
                and after.get('forward_max_task_units',math.inf)<=max(4,before.get('forward_max_task_units',0)*1.2)
                and after.get('forward_p90_task_units',0)<=before.get('forward_p90_task_units',0)*1.4+.1
                and after.get('long_forward_count',0)<=before.get('long_forward_count',0)+1)
    return (after['contacts']<=before['contacts'] and after['hairpins']<=before['hairpins']
            and (after['broken_serial']<=before['broken_serial'] or major_fold)
            and (after['information_length']<=before['information_length']*1.15+4
                 or after.get('information_mean_task_units',math.inf)<=.5 and after.get('information_max_task_units',math.inf)<=1)
            and after['crowding']<=before['crowding']*1.15+.005
            and (after['area']<=before['area']*1.005 and after['length']<=before['length']*1.05
                 or after['area']<=before['area']*.8 and after['length']<=before['length']*1.15
                 or after['contacts']<before['contacts'] and after['area']<=before['area']*1.08 and after['length']<=before['length']*1.08 or major_fold)
            and after['score']<before['score']-.1)


def acceptable_trial(initial,incumbent,candidate):
    return prefer_reading(incumbent,candidate) and prefer_reading(initial,candidate)
