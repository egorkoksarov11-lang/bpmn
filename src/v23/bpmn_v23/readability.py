"""Scale-normalized corridor crowding and continuity of consecutive steps.

The policy is an explicit engineering choice, not learned user preferences.
True graph returns are down-weighted, never removed from the BPMN model.
"""
from collections import defaultdict
from statistics import median
import math
from bpmn_refkit.model import TAG_TASK

POLICY={'name':'balanced-readability-v1','contacts_per_flow':4.0,'parallel_crowding_per_flow':8.0,'hotspot_excess':1.2,'forward_hop_excess':.8,'bends_per_flow':.35,'style_penalty_scale':.001}


def parallel_nearness(a,b,c,d,gap):
    """Length-weighted proximity of distinct parallel segments; zero otherwise."""
    eps=1e-5
    if abs(a[1]-b[1])<eps and abs(c[1]-d[1])<eps:
        distance=abs(a[1]-c[1]);overlap=max(0,min(max(a[0],b[0]),max(c[0],d[0]))-max(min(a[0],b[0]),min(c[0],d[0])))
    elif abs(a[0]-b[0])<eps and abs(c[0]-d[0])<eps:
        distance=abs(a[0]-c[0]);overlap=max(0,min(max(a[1],b[1]),max(c[1],d[1]))-max(min(a[1],b[1]),min(c[1],d[1])))
    else:return 0.0
    return overlap*max(0,1-distance/gap) if gap>0 else 0.0


def edge_crowding(points,others,gap):
    return sum(parallel_nearness(a,b,c,d,gap) for a,b in zip(points,points[1:]) for ps in others.values() for c,d in zip(ps,ps[1:]))


def graph_returns(nodes,seq):
    out={n:set() for n in nodes};inc={n:set() for n in nodes}
    for _,u,v,*_ in seq:out[u].add(v);inc[v].add(u)
    roots={n for n in nodes if nodes[n]['kind']=='startEvent' or not inc[n]};seen=set();todo=list(roots)
    while todo:
        n=todo.pop()
        if n not in seen:seen.add(n);todo.extend(out[n]-seen)
    dom={n:({n} if n in roots else set(seen)) for n in seen};changed=True
    while changed:
        changed=False
        for n in sorted(seen-roots):
            pred=inc[n]&seen;value={n}|(set.intersection(*(dom[p] for p in pred)) if pred else set())
            if value!=dom[n]:dom[n]=value;changed=True
    return {i for i,u,v,*_ in seq if v in dom.get(u,set())}


def _trim(points,amount):
    lengths=[math.dist(a,b) for a,b in zip(points,points[1:])];total=sum(lengths);lo=amount;hi=total-amount;segments=[];cursor=0
    if hi<=lo:return []
    for a,b,length in zip(points,points[1:],lengths):
        left=max(lo,cursor);right=min(hi,cursor+length)
        if length and right>left:
            def point(t):return (a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t)
            segments.append((point((left-cursor)/length),point((right-cursor)/length)))
        cursor+=length
    return segments


def metrics(boxes,paths,nodes,seq):
    tasks=[boxes[n] for n,o in nodes.items() if o['kind'] in TAG_TASK];tw=median(b[2] for b in tasks) if tasks else 160;th=median(b[3] for b in tasks) if tasks else 80
    gap=th*.15;cell=th;trim=th*.15;segments={i:_trim(paths[i],trim) for i,*_ in seq};pairs=list(segments.items());near=0.0
    for index,(i,ss) in enumerate(pairs):
        for j,tt in pairs[index+1:]:
            near+=sum(parallel_nearness(a,b,c,d,gap) for a,b in ss for c,d in tt)
    originx=min(b[0] for b in boxes.values());originy=min(b[1] for b in boxes.values());peaks=[];excesses=[]
    for offset in (0,.5):
        bins=defaultdict(set)
        for i,ss in segments.items():
            for a,b in ss:
                # Sequence flows are orthogonal in verified layouts. Bounding
                # cells also conservatively support diagnostics of diagonals.
                x0=math.floor((min(a[0],b[0])-originx)/cell-offset);x1=math.floor((max(a[0],b[0])-originx)/cell-offset)
                y0=math.floor((min(a[1],b[1])-originy)/cell-offset);y1=math.floor((max(a[1],b[1])-originy)/cell-offset)
                for x in range(x0,x1+1):
                    for y in range(y0,y1+1):bins[x,y].add(i)
        loads=[len(v) for v in bins.values()];peaks.append(max(loads,default=0));excesses.append(sum(max(0,n-4)**2 for n in loads)/max(1,len(loads)))
    returns=graph_returns(nodes,seq);hop=0;long=[];bends=0;n=max(1,len(seq))
    for i,*_ in seq:
        ps=paths[i];length=sum(math.dist(a,b) for a,b in zip(ps,ps[1:]));excess=max(0,length/tw-2)
        hop+=excess**1.4*(.25 if i in returns else 1);bends+=max(0,len(ps)-2)
        if excess and i not in returns:long.append(i)
    return {'policy':POLICY['name'],'parallel_crowding_per_flow':round(near/(tw*n),6),'hotspot_excess':round(sum(excesses)/len(excesses),6),'peak_flow_load':max(peaks,default=0),'forward_hop_excess':round(hop/n,6),'long_forward_hops':len(long),'long_forward_hop_ids':long,'bends_per_flow':round(bends/n,6),'graph_return_count':len(returns),'normalization_task_width':tw,'wire_gap_diagnostic':gap,'hotspot_cell_size':cell,'notes':'soft diagnostics; legitimate convergence may create unavoidable density; thresholds are engineering settings'}


def cost(reading,contacts,flow_count,style_penalty):
    p=POLICY
    return (p['contacts_per_flow']*contacts/max(1,flow_count)+sum(p[k]*reading[k] for k in ('parallel_crowding_per_flow','hotspot_excess','forward_hop_excess','bends_per_flow'))+style_penalty*p['style_penalty_scale'])
