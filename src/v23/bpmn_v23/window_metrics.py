"""Reading diagnostics for two-edge windows, distinct from semantic correctness.

Request/reply U-turns across a role boundary are classified separately: a return
to the requesting role is legitimate. Diagnostic opportunities are not proofs of
an avoidable defect: other wire ports and caption placement may constrain them.
"""
from collections import defaultdict,Counter
import math
from bpmn_refkit.model import TAG_TASK
from .readability import graph_returns,parallel_nearness
from .quality import path_length,contacts
from .local_editing import physical_bends


def windows(nodes,seq):
    returns=graph_returns(nodes,seq);incoming=defaultdict(list);outgoing=defaultdict(list)
    for edge in seq:
        if edge[0] in returns:continue
        incoming[edge[2]].append(edge);outgoing[edge[1]].append(edge)
    result=[]
    for b in sorted(nodes):
        pairs=[(a,c) for a in incoming[b] for c in outgoing[b] if a[1]!=c[2]]
        for first,last in pairs:
            result.append({'nodes':(first[1],b,last[2]),'edges':(first[0],last[0]),'serial_task':nodes[b]['kind'] in TAG_TASK and len(incoming[b])==len(outgoing[b])==1,'weight':1/max(1,len(pairs))})
    return result


def headings(points):
    vv=[(b[0]-a[0],b[1]-a[1]) for a,b in zip(points,points[1:]) if math.dist(a,b)>.01]
    def unit(v):
        size=math.hypot(*v);return (v[0]/size,v[1]/size)
    return (unit(vv[0]),unit(vv[-1])) if vv else ((0,0),(0,0))


def through_turn(first,last):
    a=headings(first)[1];b=headings(last)[0];dot=a[0]*b[0]+a[1]*b[1]
    return 'hairpin' if dot<-.9 else 'through' if dot>.9 else 'quarter_turn'


def bbox_gap(a,b):return max(0,b[0]-a[0]-a[2],a[0]-b[0]-b[2])+max(0,b[1]-a[1]-a[3],a[1]-b[1]-b[3])


def metrics(boxes,paths,nodes,seq,member,docs=None,assocs=None):
    docs=docs or {};assocs=assocs or [];ww=windows(nodes,seq);serial=[w for w in ww if w['serial_task']];turns=Counter();replies=Counter();detours=[];hairpins=0;compact_replies=0;reply_spans=[]
    for w in serial:
        a,b,c=w['nodes'];i,j=w['edges'];kind=through_turn(paths[i],paths[j]);reply=member.get(a)==member.get(c) and member.get(a)!=member.get(b)
        (replies if reply else turns)[kind]+=1
        if kind=='hairpin' and not reply:hairpins+=1
        if reply:
            gap=bbox_gap(boxes[a],boxes[c]);reply_spans.append(gap/200)
            compact_replies+=gap<=80
    for i,u,v,*_ in seq:
        gap=bbox_gap(boxes[u],boxes[v]);detours.append(max(0,path_length(paths[i])-gap)/200)
    short_jogs=0
    for i,*_ in seq:
        ps=paths[i]
        for index in range(1,len(ps)-2):
            if .01<math.dist(ps[index],ps[index+1])<12:short_jogs+=1
    flow_ids=[e[0] for e in seq];near=0.;tight_pairs=0
    for index,i in enumerate(flow_ids):
        for j in flow_ids[index+1:]:
            value=sum(parallel_nearness(a,b,c,d,12) for a,b in zip(paths[i],paths[i][1:]) for c,d in zip(paths[j],paths[j][1:]))
            if value>20:tight_pairs+=1
            near+=value
    spans=sorted(path_length(paths[i]) for i,*_ in seq);n=max(1,len(seq))
    weights=sum(w['weight'] for w in ww);uv={i:(u,v) for i,u,v,*_ in seq+assocs};control=set(flow_ids)
    contact_types=Counter('control_control' if i in control and j in control else 'control_information' if i in control or j in control else 'information_information' for i,j,_ in contacts({i:p for i,p in paths.items() if i in uv},uv))
    return {'weighted_simple_window_fraction':sum(w['weight'] for w in ww if all(physical_bends(paths[i])<=1 for i in w['edges']))/max(1,weights),'contact_types':dict(contact_types),'flow_length_p90_task_units':spans[min(len(spans)-1,int(len(spans)*.9))]/200 if spans else 0,'excess_wire_p90_task_units':sorted(detours)[min(len(detours)-1,int(len(detours)*.9))] if detours else 0,'window_count':len(ww),'serial_task_windows':len(serial),'serial_through':turns['through'],'serial_quarter_turn':turns['quarter_turn'],'serial_hairpins':hairpins,'request_reply_windows':sum(replies.values()),'request_reply_turns':dict(replies),'request_reply_compact':compact_replies,'request_reply_gap_mean_task_units':sum(reply_spans)/max(1,len(reply_spans)),
            'excess_wire_mean_task_units':sum(detours)/n,'short_internal_jogs':short_jogs,'tight_parallel_pairs':tight_pairs,'parallel_pressure_fixed_units':near/(200*n),'long_flow_count':sum(v>600 for v in spans),'simple_window_fraction':sum(physical_bends(paths[w['edges'][0]])<=1 and physical_bends(paths[w['edges'][1]])<=1 for w in serial)/max(1,len(serial)),
            'interpretation':'reading diagnostics, not business correctness or percentage human similarity; reversals and request/reply spacing are contextual, not defects to minimize'}


def local_loss(paths,uv,seq,window,member):
    # Do not penalize raw direction reversals: human examples use them for
    # compact folding. Evaluate the wires themselves, in fixed physical units.
    i,j=window['edges']
    return sum(physical_bends(paths[e])*1.5+path_length(paths[e])/200 for e in (i,j))
