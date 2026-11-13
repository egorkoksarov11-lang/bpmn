"""Bounded orthogonal route rehearsal; no A*, no source DI, no business edits."""
from collections import Counter,defaultdict
from statistics import median
import math
from bpmn_refkit.model import TAG_TASK
from bpmn_refkit.geometry import compress
from .clearance import segment_blocked,outward
from .labels import SpatialIndex
from .quality import intersection,segment_overlap,path_length


def port(box,side,f):
    x,y,w,h=box
    return {'R':((x+w,y+h*f),(1,0)),'L':((x,y+h*f),(-1,0)),
            'T':((x+w*f,y),(0,-1)),'B':((x+w*f,y+h),(0,1))}[side]


def candidates(u,v,boxes,member,lanes):
    a,b=boxes[u],boxes[v];dx=b[0]+b[2]/2-a[0]-a[2]/2;dy=b[1]+b[3]/2-a[1]-a[3]/2
    horizontal=('R','L') if dx>=0 else ('L','R');vertical=('B','T') if dy>=0 else ('T','B')
    pairs=[horizontal,vertical,(horizontal[0],vertical[1]),(vertical[0],horizontal[1])]
    channels=[]
    for n in (u,v):
        if member.get(n) in lanes:
            x,y,w,h=boxes[member[n]];channels.extend((y+12,y+h-12))
    seen=set();paths=[]
    for f in (.5,.3,.7):
        for source_side,target_side in pairs:
            s,sd=port(a,source_side,f);t,td=port(b,target_side,f)
            so=(s[0]+sd[0]*16,s[1]+sd[1]*16);to=(t[0]+td[0]*16,t[1]+td[1]*16)
            variants=[[s,(t[0],s[1]),t],[s,(s[0],t[1]),t],
                      [s,so,(so[0],to[1]),to,t],[s,so,(to[0],so[1]),to,t]]
            # Distinct lane-edge tracks give returns an explicit cheap escape.
            if f==.5:
                for cy in sorted(set(channels)):
                    variants.append([s,so,(so[0],cy),(to[0],cy),to,t])
            for raw in variants:
                p=compress([(round(x,2),round(y,2)) for x,y in raw]);key=tuple(p)
                if key in seen or len(p)<2:continue
                seen.add(key)
                if not outward(p[0],p[1],a) or not outward(p[-1],p[-2],b):continue
                paths.append(p)
    return sorted(paths,key=lambda p:(len(p),path_length(p),p))


def build_options(nodes,docs,seq,assocs,member,lanes,boxes,report):
    obstacles={n:b for n,b in boxes.items() if n in nodes or n in docs}
    obstacles.update({'__text_'+n:b for n,b in report.get('reserved_captions',{}).items()})
    obstacles.update({'__header_'+l:(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes})
    index=SpatialIndex()
    for n,(x,y,w,h) in obstacles.items():
        gap=2 if n.startswith('__text_') else 8;index.add((x-gap,y-gap,w+2*gap,h+2*gap),(n,(x,y,w,h),gap))
    options={};fallback={};tested=0
    for eid,u,v,*_ in seq+assocs:
        good=[];all_paths=candidates(u,v,boxes,member,lanes);fallback[eid]=all_paths[0] if all_paths else []
        for p in all_paths:
            tested+=1;blocked=False
            for k,(a,b) in enumerate(zip(p,p[1:])):
                query=(min(a[0],b[0]),min(a[1],b[1]),abs(a[0]-b[0]),abs(a[1]-b[1]))
                for name,box,gap in index.query(query):
                    if name==u and k==0 or name==v and k==len(p)-2:continue
                    if segment_blocked(a,b,box,False,gap):blocked=True;break
                if blocked:break
            if not blocked:good.append(p)
            if len(good)==6:break
        options[eid]=good
    return options,fallback,tested


def incremental(eid,p,chosen,uv,tw):
    contacts=0;overlap=0.;pressure=0.;port_conflicts=0
    u,v=uv[eid]
    for fid,q in chosen.items():
        points=set();a,b=uv[fid]
        for n,point in ((u,p[0]),(v,p[-1])):
            if n==a and point==q[0] or n==b and point==q[-1]:port_conflicts+=1
        for s,t in zip(p,p[1:]):
            for x,y in zip(q,q[1:]):
                meet=intersection(s,t,x,y)
                if meet is not None:
                    common=(meet==p[0] and u in (a,b) and (meet==q[0] and u==a or meet==q[-1] and u==b) or meet==p[-1] and v in (a,b) and (meet==q[0] and v==a or meet==q[-1] and v==b))
                    if not common:points.add(meet)
                overlap+=segment_overlap(s,t,x,y)
                if s[1]==t[1] and x[1]==y[1]:
                    gap=abs(s[1]-x[1]);span=min(max(s[0],t[0]),max(x[0],y[0]))-max(min(s[0],t[0]),min(x[0],y[0]))
                elif s[0]==t[0] and x[0]==y[0]:
                    gap=abs(s[0]-x[0]);span=min(max(s[1],t[1]),max(x[1],y[1]))-max(min(s[1],t[1]),min(x[1],y[1]))
                else:continue
                if 0<gap<12 and span>0:pressure+=span/tw*(1-gap/12)
        contacts+=len(points)
    length=path_length(p);bends=max(0,len(p)-2)
    return 16*contacts+32*overlap/tw+8*pressure+40*port_conflicts+length/tw+.55*bends


def rehearse(nodes,docs,seq,assocs,member,lanes,boxes,report,fail_first=False,precomputed=None):
    options,fallback,tested=precomputed or build_options(nodes,docs,seq,assocs,member,lanes,boxes,report)
    uv={i:(u,v) for i,u,v,*_ in seq+assocs};seqids={i for i,*_ in seq};degree=Counter(n for _,u,v,*_ in seq for n in (u,v))
    tw=median([boxes[n][2] for n in nodes if nodes[n]['kind'] in TAG_TASK] or [180])
    def priority(eid):
        u,v=uv[eid];a,b=boxes[u],boxes[v];aligned=abs(a[0]+a[2]/2-b[0]-b[2]/2)<1 or abs(a[1]+a[3]/2-b[1]-b[3]/2)<1
        return (eid not in seqids,len(options[eid]) if fail_first else not aligned,path_length(fallback[eid]) if fallback[eid] else 1e9,eid)
    remaining=sorted(uv,key=priority);chosen={};safe={};blocked=[];routing_order=[];groups=0
    while remaining:
        eid=remaining.pop(0);group=[eid];pivot=set(uv[eid]);branch=any(degree[n]>=3 for n in pivot)
        if branch:
            for other in list(remaining):
                if other in seqids and pivot&set(uv[other]) and len(group)<3:group.append(other);remaining.remove(other)
        states=[(0.,{})]
        for i in group:
            choices=options[i]
            if not choices:
                blocked.append(i);routing_order.append(i);continue
            proposals=[]
            for cost,local in states:
                others={**chosen,**local}
                for p in choices:
                    value=cost+incremental(i,p,others,uv,tw);proposals.append((value,{**local,i:p}))
            proposals.sort(key=lambda s:(s[0],tuple((i,tuple(map(tuple,p))) for i,p in s[1].items())))
            states=proposals[:2] if branch else proposals[:1]
            routing_order.append(i)
        if states:
            for i,p in min(states,key=lambda s:s[0])[1].items():chosen[i]=p;safe[i]=p
        groups+=int(branch)
    # Exact preview metrics use the same contact definition as final geometry.
    from .quality import contacts
    overlap=0.;pressure=0.
    items=list(chosen.items())
    for k,(i,p) in enumerate(items):
        for j,q in items[k+1:]:
            for a,b in zip(p,p[1:]):
                for c,d in zip(q,q[1:]):overlap+=segment_overlap(a,b,c,d)
    from .readability import edge_crowding
    for i,p in chosen.items():pressure+=edge_crowding(p,{j:q for j,q in chosen.items() if j!=i},12)/tw
    total=contacts(chosen,uv);length=sum(path_length(chosen[i]) for i in chosen if i in seqids);info=[path_length(chosen[i])/tw for i in chosen if i not in seqids]
    outgoing=Counter(u for _,u,v,*_ in seq);incoming=Counter(v for _,u,v,*_ in seq)
    serial={i for i,u,v,*_ in seq if nodes[u]['kind'] in TAG_TASK and nodes[v]['kind'] in TAG_TASK and outgoing[u]==incoming[v]==1}
    broken=sum(len(chosen[i])>2 for i in serial if i in chosen);bends=sum(max(0,len(p)-2) for i,p in chosen.items() if i in seqids)
    visible=[b for n,b in boxes.items() if n in nodes or n in docs]+list(report.get('reserved_captions',{}).values())
    width=max(x+w for x,y,w,h in visible)-min(x for x,y,w,h in visible);height=max(y+h for x,y,w,h in visible)-min(y for x,y,w,h in visible)
    packing=math.sqrt(width*height/(max(1,len(nodes))*tw*76))
    loss=16*len(total)+length/tw+.55*bends+3*broken+10*packing+32*overlap/tw+4*pressure+80*len(blocked)+.5*sum(info)+4*sum(max(0,x-1)**2 for x in info)
    return {'score':round(loss,6),'contacts':len(total),'bends':bends,'flow_length':round(length,2),'information_length':round(sum(info)*tw,2),'information_max_task_units':max(info,default=0),'shared_length':round(overlap,2),'parallel_pressure':round(pressure,6),'unsupported_edges':len(blocked),'flow_count':len(seq),'previewed_edges':len(chosen),'branch_windows':groups,'template_checks':tested,'order':'fail-first' if fail_first else 'aligned-first','area':round(width*height,2),'width':round(width,2),'height':round(height,2),'serial_straight':sum(len(chosen[i])==2 for i in serial if i in chosen),'paths':safe,'routing_order':routing_order,'unsupported_ids':blocked},(options,fallback,tested)


def route_hints(nodes,seq,boxes,member,lanes,report):
    from .return_corridors import hints_factory
    base=hints_factory(nodes,seq,boxes,member,lanes);planned=report.get('preplanned_paths',{})
    def hints(eid,paths):return ([planned[eid]] if eid in planned else [])+base(eid,paths)
    return hints
