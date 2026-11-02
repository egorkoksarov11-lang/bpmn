"""Strict orthogonal routing on fixed DI, with distinct ports and channels.

Existing v22 quick candidates are reused; a separate A* fallback forbids
collinear reuse instead of accepting input geometry as a successful fallback.
"""
from collections import defaultdict
from functools import lru_cache
import heapq, math, time
from lxml import etree as ET
from bpmn_refkit.model import read_bpmn, set_di
from bpmn_refkit.geometry import compress, bbox_intersect_seg, segment_overlap, segment_intersection, geometry_audit
from bpmn_universal.engine import quick_routes, good_poly, route_cost, save_labels, arrange_flow_labels
from bpmn_universal.cli import deadline
from .quality import intersection, score, burdens, contacts, edge_score, segment_overlap
from .clearance import safe_poly,segment_blocked
from .readability import edge_crowding,parallel_nearness


def overlapping(p, paths):
    return any(segment_overlap(a,b,c,d)>.01 for a,b in zip(p,p[1:]) for ps in paths.values() for c,d in zip(ps,ps[1:]))


def astar(eid,boxes,uv,paths,pairs,clip_window=True,avoid_crowding=False,window_margin=120,bend_penalty=70):
    u,v=uv[eid];bu,bv=boxes[u],boxes[v]
    x0=min(bu[0],bv[0])-window_margin;x1=max(bu[0]+bu[2],bv[0]+bv[2])+window_margin
    y0=min(bu[1],bv[1])-window_margin;y1=max(bu[1]+bu[3],bv[1]+bv[3])+window_margin
    relevant={k:b for k,b in boxes.items() if b[0]-8<=x1 and b[0]+b[2]+8>=x0 and b[1]-8<=y1 and b[1]+b[3]+8>=y0}
    xs={x0,x1};ys={y0,y1}
    for name,(x,y,w,h) in relevant.items():
        clearance=2 if str(name).startswith('__text_') else 8
        xs.update((x-clearance,x+w+clearance));ys.update((y-clearance,y+h+clearance))
    margin=12 if avoid_crowding else 0
    segments=[(a,b) for ps in paths.values() for a,b in zip(ps,ps[1:]) if min(a[0],b[0])<=x1+margin and max(a[0],b[0])>=x0-margin and min(a[1],b[1])<=y1+margin and max(a[1],b[1])>=y0-margin]
    for a,b in segments:
        if a[0]==b[0]:xs.update((a[0]-5,a[0]+5))
        if a[1]==b[1]:ys.update((a[1]-5,a[1]+5))
    # Include all candidate ports so fallback can escape congested shared centers.
    for s,t in pairs:xs.update((s[0],t[0]));ys.update((s[1],t[1]))
    xs=sorted({round(x,2) for x in xs if not clip_window or x0<=x<=x1});ys=sorted({round(y,2) for y in ys if not clip_window or y0<=y<=y1})
    xi={x:i for i,x in enumerate(xs)};yi={y:i for i,y in enumerate(ys)}
    segment_index=None
    from .labels import SpatialIndex
    obstacle_index=SpatialIndex()
    for name,box in (relevant.items() if clip_window else boxes.items()):
        x,y,w,h=box;clearance=2 if str(name).startswith('__text_') else 8
        obstacle_index.add((x-clearance,y-clearance,w+clearance*2,h+clearance*2),(name,box,clearance))
    if avoid_crowding:
        segment_index=SpatialIndex()
        for a,b in segments:segment_index.add((min(a[0],b[0]),min(a[1],b[1]),abs(a[0]-b[0]),abs(a[1]-b[1])),(a,b))
    @lru_cache(None)
    def cost(i,j,ii,jj):
        a=(xs[i],ys[j]);b=(xs[ii],ys[jj])
        query=(min(a[0],b[0]),min(a[1],b[1]),abs(a[0]-b[0]),abs(a[1]-b[1]))
        if any(segment_blocked(a,b,box,n in (u,v),clearance) for n,box,clearance in obstacle_index.query(query)):return math.inf
        crossings=0;near=0.0
        nearby=segment_index.query((min(a[0],b[0])-12,min(a[1],b[1])-12,abs(a[0]-b[0])+24,abs(a[1]-b[1])+24)) if segment_index else segments
        for c,d in nearby:
            if segment_overlap(a,b,c,d)>.01:return math.inf
            if intersection(a,b,c,d) is not None:crossings+=1
            if avoid_crowding:near+=parallel_nearness(a,b,c,d,12)
        return abs(a[0]-b[0])+abs(a[1]-b[1])+crossings*1500+near*3
    if not pairs:return None
    pairs=[(tuple(s),tuple(t)) for s,t in pairs]
    sources=list(dict.fromkeys(s for s,t in pairs));targets=list(dict.fromkeys(t for s,t in pairs))
    started=time.monotonic()
    def search(source_points,target_points):
        goals={(xi[round(t[0],2)],yi[round(t[1],2)]) for t in target_points}
        @lru_cache(None)
        def heuristic(i,j):return min(abs(xs[i]-t[0])+abs(ys[j]-t[1]) for t in target_points)
        queue=[];dist={};parent={}
        for source in source_points:
            state=(xi[round(source[0],2)],yi[round(source[1],2)],-1)
            dist[state]=0;heapq.heappush(queue,(heuristic(*state[:2]),0,state))
        visited=0
        while queue:
            visited+=1
            if visited%512==0 and (visited>90000 or time.monotonic()-started>8):return None
            _,g,state=heapq.heappop(queue);i,j,axis=state
            if g!=dist.get(state):continue
            if (i,j) in goals:
                points=[];cursor=state
                while True:
                    points.append((xs[cursor[0]],ys[cursor[1]]))
                    if cursor not in parent:break
                    cursor=parent[cursor]
                points=compress(points[::-1])
                if len(points)>1 and not (u==v and points[0]==points[-1]) and safe_poly(eid,points,boxes,uv) and not overlapping(points,paths):return points
            for di,dj,newaxis in ((1,0,0),(-1,0,0),(0,1,1),(0,-1,1)):
                ii,jj=i+di,j+dj
                if not 0<=ii<len(xs) or not 0<=jj<len(ys):continue
                step=cost(i,j,ii,jj)
                if not math.isfinite(step):continue
                ng=g+step+(bend_penalty if axis>=0 and axis!=newaxis else 0);nxt=(ii,jj,newaxis)
                if ng<dist.get(nxt,math.inf):
                    dist[nxt]=ng;parent[nxt]=state;heapq.heappush(queue,(ng+heuristic(ii,jj),ng,nxt))
        return None
    if u!=v and len(set(pairs))==len(sources)*len(targets):return search(sources,targets)
    # Rare explicitly restricted pairings retain their pair constraints.
    for source,target in pairs:
        if u==v and source==target:continue
        if time.monotonic()-started>8:break
        result=search([source],[target])
        if result:return result
    return None


def free_pairs(boxes,uv,paths,u,v):
    def ports(n):
        x,y,w,h=boxes[n]
        used={p[0] for eid,p in paths.items() if uv[eid][0]==n}|{p[-1] for eid,p in paths.items() if uv[eid][1]==n}
        return [p for f in (.5,.35,.65,.2,.8) for p in [(x+w,y+h*f),(x,y+h*f),(x+w*f,y+h),(x+w*f,y)] if p not in used]
    return [(s,t) for s in ports(u) for t in ports(v)]


def choice_score(eid,points,others,uv,avoid_crowding=False):
    raw=edge_score(eid,points,others,uv)
    if not avoid_crowding:return raw
    near=edge_crowding(points,others,12)
    return (round(raw[0]*1500+near*3+raw[1]*70+raw[2],4),*raw)


def orthogonal_shortcuts(points):
    """Rubber-band a generated route, without relying on its source diagram."""
    seen=set()
    for span in range(len(points)-1,2,-1):
        for i in range(len(points)-span):
            j=i+span;a,b=points[i],points[j]
            for elbow in ((a[0],b[1]),(b[0],a[1])):
                candidate=compress(points[:i+1]+[elbow]+points[j:]);key=tuple(candidate)
                if len(candidate)>=len(points) or key in seen:continue
                seen.add(key)
                crossed=False
                for k,(u,v) in enumerate(zip(candidate,candidate[1:])):
                    for m in range(k+2,len(candidate)-1):
                        c,d=candidate[m:m+2]
                        if intersection(u,v,c,d) is not None or segment_overlap(u,v,c,d)>.01:crossed=True;break
                    if crossed:break
                if not crossed:yield candidate


def refine_paths(boxes,uv,paths,rounds=2,clip_window=True,hints=None,avoid_crowding=False,simplify=False,protected_ids=()):
    """Rip up congested edges; commit only a strictly better global score."""
    changes=[]
    for iteration in range(rounds):
        count=burdens(paths,uv);changed=False;crowded={}
        simplify_ids={eid for eid,p in paths.items() if len(p)>4} if simplify else set()
        for eid in simplify_ids:count.setdefault(eid,0)
        if avoid_crowding:
            for eid,points in paths.items():
                near=edge_crowding(points,{k:p for k,p in paths.items() if k!=eid},12)
                if near>24:crowded[eid]=near;count.setdefault(eid,0)
        for eid in sorted(count,key=lambda k:(not(simplify and len(paths[k])>10),-count[k]*1500-crowded.get(k,0)*3,k)):
            if eid in protected_ids:continue
            if count[eid]<1 and eid not in crowded and eid not in simplify_ids:continue
            old=paths[eid];others={k:p for k,p in paths.items() if k!=eid}
            def value_of(points):
                value=choice_score(eid,points,others,uv,avoid_crowding)
                return (len(points)>10,*value) if simplify else value
            before=value_of(old)
            variants=quick_routes(eid,boxes,uv,others,old)
            if simplify:variants.extend(orthogonal_shortcuts(old))
            if hints:variants.extend(p for p in hints(eid,others) if safe_poly(eid,p,boxes,uv))
            variants=[p for p in variants if safe_poly(eid,p,boxes,uv) and not overlapping(p,others)]
            u,v=uv[eid]
            # A* needs only the already valid ports; alternative sides come from quick routes.
            port_pairs=free_pairs(boxes,uv,others,u,v) if avoid_crowding or count[eid]>1 else [(old[0],old[-1])]
            routed=astar(eid,boxes,uv,others,port_pairs,clip_window=clip_window,avoid_crowding=avoid_crowding)
            if routed is None and not clip_window:routed=astar(eid,boxes,uv,others,port_pairs,avoid_crowding=avoid_crowding)
            if routed:variants.append(routed)
            if simplify and len(old)>10:
                for penalty in (240,1000):
                    alternative=astar(eid,boxes,uv,others,port_pairs,clip_window=clip_window,avoid_crowding=avoid_crowding,window_margin=600,bend_penalty=penalty)
                    if alternative:variants.append(alternative)
                    if alternative and len(alternative)<=10:break
            best=old;best_score=before
            for p in variants:
                value=value_of(p)
                if value<best_score:best=p;best_score=value
            if best_score<before:
                paths[eid]=best;changed=True;changes.append({'edge':eid,'before':before,'after':best_score})
        if not changed:break
    return changes


def route_graph(boxes,nodes,seq,assocs,docs,oldpaths,rounds=2,clip_window=True,priority=None,hints=None,avoid_crowding=False,fixed_paths=None,expand_windows=False):
    uv={i:(u,v) for i,u,v,_ in seq+assocs};paths={i:list(p) for i,p in (fixed_paths or {}).items()};usage=defaultdict(set)
    if not set(paths).issubset(uv):raise ValueError('Unknown fixed edge')
    for eid,p in paths.items():
        others={i:q for i,q in paths.items() if i!=eid}
        is_information=eid in {i for i,u,v,_ in assocs if u in docs or v in docs}
        safe=safe_poly(eid,p,boxes,uv)
        if is_information and len(p)==2:
            from .document_layout import safe_link
            from .contours import on_contour
            u,v=uv[eid]
            safe=safe_link(eid,p,boxes,uv,others,nodes=nodes) and all(on_contour(p[k],boxes[n],nodes.get(n,{}).get('kind','')) for k,n in ((0,u),(-1,v)))
        if not safe or overlapping(p,others):raise ValueError('Unsafe fixed path: '+eid)
        usage[uv[eid][0]].add(p[0]);usage[uv[eid][1]].add(p[-1])
    def port_options(n):
        x,y,w,h=boxes[n];options=[]
        for f in (.5,.35,.65,.2,.8):
            options.extend([(x+w,y+h*f),(x,y+h*f),(x+w*f,y+h),(x+w*f,y)])
        return [tuple(round(z,2) for z in p) for p in options if tuple(round(z,2) for z in p) not in usage[n]]
    seq_ids={s[0] for s in seq}
    order=sorted(uv,key=lambda i:(i not in seq_ids,abs(boxes[uv[i][0]][0]-boxes[uv[i][1]][0])+abs(boxes[uv[i][0]][1]-boxes[uv[i][1]][1]),i))
    if priority:
        position={eid:i for i,eid in enumerate(priority)};order.sort(key=lambda eid:(position.get(eid,len(position)),eid))
    fallbacks=0
    for eid in order:
        if eid in paths:continue
        u,v=uv[eid]
        variants=quick_routes(eid,boxes,uv,paths,oldpaths[eid])
        if hints:variants.extend(p for p in hints(eid,paths) if safe_poly(eid,p,boxes,uv))
        variants=[p for p in variants if p[0] not in usage[u] and p[-1] not in usage[v] and safe_poly(eid,p,boxes,uv) and not overlapping(p,paths)]
        if variants:p=min(variants,key=lambda p:choice_score(eid,p,paths,uv,avoid_crowding))
        else:
            pairs=[(s,t) for s in port_options(u) for t in port_options(v)]
            pairs.sort(key=lambda st:abs(st[0][0]-st[1][0])+abs(st[0][1]-st[1][1]))
            diverse=[];used_s=set();used_t=set()
            for pair in pairs:
                if pair[0] not in used_s and pair[1] not in used_t:
                    diverse.append(pair);used_s.add(pair[0]);used_t.add(pair[1])
            pairs=diverse+[pair for pair in pairs if pair not in diverse]
            p=astar(eid,boxes,uv,paths,pairs,clip_window=clip_window,avoid_crowding=avoid_crowding)
            if p is None and expand_windows:
                for margin in (300,600):
                    p=astar(eid,boxes,uv,paths,pairs,clip_window=clip_window,avoid_crowding=avoid_crowding,window_margin=margin)
                    if p is not None:break
            if p is None and not clip_window:p=astar(eid,boxes,uv,paths,pairs,avoid_crowding=avoid_crowding)
            fallbacks+=1
        if p is None:raise RuntimeError('No distinct-channel route for '+eid)
        paths[eid]=p;usage[u].add(p[0]);usage[v].add(p[-1])
    initial=score(paths,uv)
    interrupted=False
    try:changes=refine_paths(boxes,uv,paths,rounds=0 if fixed_paths else rounds,clip_window=clip_window,hints=hints,avoid_crowding=avoid_crowding)
    except TimeoutError:changes=[];interrupted=True
    return paths,{'refinement_interrupted':interrupted,'astar_fallbacks':fallbacks,'initial_quality':initial,'final_quality':score(paths,uv),'refinements':changes}


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
