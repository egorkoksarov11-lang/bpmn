"""Strict orthogonal routing on fixed DI, with distinct ports and channels.

Existing v22 quick candidates are reused; a separate A* fallback forbids
collinear reuse instead of accepting input geometry as a successful fallback.
"""
from collections import defaultdict
from functools import lru_cache
import heapq, math
from lxml import etree as ET
from bpmn_refkit.model import read_bpmn, set_di
from bpmn_refkit.geometry import compress, bbox_intersect_seg, segment_overlap, segment_intersection, geometry_audit
from bpmn_universal.engine import quick_routes, good_poly, route_cost, save_labels, arrange_flow_labels
from bpmn_universal.cli import deadline
from .quality import intersection, score, burdens, contacts, edge_score


def overlapping(p, paths):
    return any(segment_overlap(a,b,c,d)>.01 for a,b in zip(p,p[1:]) for ps in paths.values() for c,d in zip(ps,ps[1:]))


def astar(eid,boxes,uv,paths,pairs,clip_window=True):
    u,v=uv[eid];bu,bv=boxes[u],boxes[v]
    x0=min(bu[0],bv[0])-120;x1=max(bu[0]+bu[2],bv[0]+bv[2])+120
    y0=min(bu[1],bv[1])-120;y1=max(bu[1]+bu[3],bv[1]+bv[3])+120
    relevant={k:b for k,b in boxes.items() if b[0]<=x1 and b[0]+b[2]>=x0 and b[1]<=y1 and b[1]+b[3]>=y0}
    xs={x0,x1};ys={y0,y1}
    for x,y,w,h in relevant.values():xs.update((x-8,x+w+8));ys.update((y-8,y+h+8))
    segments=[(a,b) for ps in paths.values() for a,b in zip(ps,ps[1:]) if min(a[0],b[0])<=x1 and max(a[0],b[0])>=x0 and min(a[1],b[1])<=y1 and max(a[1],b[1])>=y0]
    for a,b in segments:
        if a[0]==b[0]:xs.update((a[0]-5,a[0]+5))
        if a[1]==b[1]:ys.update((a[1]-5,a[1]+5))
    # Include all candidate ports so fallback can escape congested shared centers.
    for s,t in pairs:xs.update((s[0],t[0]));ys.update((s[1],t[1]))
    xs=sorted({round(x,2) for x in xs if not clip_window or x0<=x<=x1});ys=sorted({round(y,2) for y in ys if not clip_window or y0<=y<=y1})
    xi={x:i for i,x in enumerate(xs)};yi={y:i for i,y in enumerate(ys)}
    @lru_cache(None)
    def cost(i,j,ii,jj):
        a=(xs[i],ys[j]);b=(xs[ii],ys[jj])
        if any(bbox_intersect_seg(box,a,b,clearance=1) for box in (relevant.values() if clip_window else boxes.values())):return math.inf
        crossings=0
        for c,d in segments:
            if segment_overlap(a,b,c,d)>.01:return math.inf
            if intersection(a,b,c,d) is not None:crossings+=1
        return abs(a[0]-b[0])+abs(a[1]-b[1])+crossings*1500
    best=None
    for s,t in pairs[:48]:
        start=(xi[round(s[0],2)],yi[round(s[1],2)],-1);target=(xi[round(t[0],2)],yi[round(t[1],2)])
        queue=[(0,0,start)];dist={start:0};parent={};end=None
        while queue:
            _,g,state=heapq.heappop(queue);i,j,axis=state
            if g!=dist.get(state):continue
            if (i,j)==target:end=state;break
            for di,dj,newaxis in ((1,0,0),(-1,0,0),(0,1,1),(0,-1,1)):
                ii,jj=i+di,j+dj
                if not 0<=ii<len(xs) or not 0<=jj<len(ys):continue
                step=cost(i,j,ii,jj)
                if not math.isfinite(step):continue
                ng=g+step+(70 if axis>=0 and axis!=newaxis else 0)
                nxt=(ii,jj,newaxis)
                if ng<dist.get(nxt,math.inf):
                    dist[nxt]=ng;parent[nxt]=state
                    h=abs(xs[ii]-t[0])+abs(ys[jj]-t[1]);heapq.heappush(queue,(ng+h,ng,nxt))
        if end is not None:
            p=[];state=end
            while True:
                p.append((xs[state[0]],ys[state[1]]))
                if state not in parent:break
                state=parent[state]
            p=compress(p[::-1])
            if good_poly(eid,p,boxes,uv) and not overlapping(p,paths):
                if best is None or route_cost(p,paths,eid)<route_cost(best,paths,eid):best=p
                # First feasible A* result bounds work; quick routes handle easy cases.
                break
    return best


def refine_paths(boxes,uv,paths,rounds=2,clip_window=True):
    """Rip up congested edges; commit only a strictly better global score."""
    changes=[]
    for iteration in range(rounds):
        count=burdens(paths,uv);changed=False
        for eid in sorted(count,key=lambda k:(-count[k],k)):
            if count[eid]<1:continue
            old=paths[eid];others={k:p for k,p in paths.items() if k!=eid};before=edge_score(eid,old,others,uv)
            variants=quick_routes(eid,boxes,uv,others,old)
            variants=[p for p in variants if not overlapping(p,others)]
            u,v=uv[eid]
            # A* needs only the already valid ports; alternative sides come from quick routes.
            routed=astar(eid,boxes,uv,others,[(old[0],old[-1])],clip_window=clip_window)
            if routed is None and not clip_window:routed=astar(eid,boxes,uv,others,[(old[0],old[-1])])
            if routed:variants.append(routed)
            best=old;best_score=before
            for p in variants:
                value=edge_score(eid,p,others,uv)
                if value<best_score:best=p;best_score=value
            if best_score<before:
                paths[eid]=best;changed=True;changes.append({'edge':eid,'before':before,'after':best_score})
        if not changed:break
    return changes


def route_graph(boxes,nodes,seq,assocs,docs,oldpaths,rounds=2,clip_window=True):
    uv={i:(u,v) for i,u,v,_ in seq+assocs};paths={};usage=defaultdict(set)
    def port_options(n):
        x,y,w,h=boxes[n];options=[]
        for f in (.5,.35,.65,.2,.8):
            options.extend([(x+w,y+h*f),(x,y+h*f),(x+w*f,y+h),(x+w*f,y)])
        return [tuple(round(z,2) for z in p) for p in options if tuple(round(z,2) for z in p) not in usage[n]]
    seq_ids={s[0] for s in seq}
    order=sorted(uv,key=lambda i:(i not in seq_ids,abs(boxes[uv[i][0]][0]-boxes[uv[i][1]][0])+abs(boxes[uv[i][0]][1]-boxes[uv[i][1]][1]),i))
    fallbacks=0
    for eid in order:
        u,v=uv[eid]
        variants=quick_routes(eid,boxes,uv,paths,oldpaths[eid])
        variants=[p for p in variants if p[0] not in usage[u] and p[-1] not in usage[v] and not overlapping(p,paths)]
        if variants:p=min(variants,key=lambda p:route_cost(p,paths,eid))
        else:
            pairs=[(s,t) for s in port_options(u) for t in port_options(v)]
            pairs.sort(key=lambda st:abs(st[0][0]-st[1][0])+abs(st[0][1]-st[1][1]))
            diverse=[];used_s=set();used_t=set()
            for pair in pairs:
                if pair[0] not in used_s and pair[1] not in used_t:
                    diverse.append(pair);used_s.add(pair[0]);used_t.add(pair[1])
            pairs=diverse+[pair for pair in pairs if pair not in diverse]
            p=astar(eid,boxes,uv,paths,pairs,clip_window=clip_window)
            if p is None and not clip_window:p=astar(eid,boxes,uv,paths,pairs)
            fallbacks+=1
        if p is None:raise RuntimeError('No distinct-channel route for '+eid)
        paths[eid]=p;usage[u].add(p[0]);usage[v].add(p[-1])
    initial=score(paths,uv)
    changes=refine_paths(boxes,uv,paths,rounds=rounds,clip_window=clip_window)
    return paths,{'astar_fallbacks':fallbacks,'initial_quality':initial,'final_quality':score(paths,uv),'refinements':changes}


class OrthogonalBackend:
    name='v23-distinct-channel-orthogonal'
    def layout(self,source,output,svg):
        tree,root,process,plane,nodes,seq,assocs,docs,_,_,allboxes,oldpaths=read_bpmn(source)
        boxes={k:b for k,b in allboxes.items() if k in nodes or k in docs}
        with deadline(180):paths,details=route_graph(boxes,nodes,seq,assocs,docs,oldpaths)
        set_di(root,plane,boxes,paths)
        save_labels(root,plane,boxes,nodes,paths);arrange_flow_labels(root,plane,boxes,seq,paths)
        tree.write(str(output),encoding='utf-8',xml_declaration=True)
        return {'backend':self.name,**details,'geometry_before':geometry_audit(boxes,oldpaths,seq,assocs,nodes,docs),'geometry_after':geometry_audit(boxes,paths,seq,assocs,nodes,docs),'removed_redundant_associations':[]}
