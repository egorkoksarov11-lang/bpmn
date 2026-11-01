"""Choose decision orientations using their complete logical interface.

All four variants preserve node/edge identities. Vertical variants grow the
whole affected row; subsequent rows and lanes move together. A cheap routing
estimate proposes geometry; only the full backend audit can accept a result.
"""
from collections import defaultdict
from bpmn_refkit.geometry import compress,bbox_intersect_seg
from .clearance import outward
from .reference_style import profile


def reflow(boxes,report,orientations,nodes,docs,membership):
    result=dict(boxes);pairs=report['pairs'];owner={n:n for n in nodes}
    for a,g in pairs.items():owner[g]=a
    slots=report['slots'];extra=defaultdict(int)
    for a,kind in orientations.items():
        if kind in ('top','bottom'):
            lane=membership[a];row=slots[a][1];extra[lane,row]=max(extra[lane,row],boxes[pairs[a]][3]+26)
    lanes=sorted(report['role_order'],key=lambda l:boxes[l][1]);shift={};cursor=0
    for lane in lanes:
        shift[lane]=cursor;x,y,w,h=boxes[lane];growth=sum(v for (l,r),v in extra.items() if l==lane)
        result[lane]=(x,y+cursor,w,h+growth);cursor+=growth
    def delta(macro):
        lane=membership[macro];row=slots[macro][1]
        return shift[lane]+sum(v for (l,r),v in extra.items() if l==lane and r<row)
    for n in nodes:
        x,y,w,h=boxes[n];result[n]=(x,y+delta(owner[n]),w,h)
    for a,g in pairs.items():
        x,y,w,h=result[a];gw,gh=boxes[g][2:];kind=orientations.get(a,'right')
        if kind=='left':result[a]=(x+gw+30,y,w,h);result[g]=(x,y+(h-gh)/2,gw,gh)
        elif kind=='bottom':result[g]=(x+(w-gw)/2,y+h+26,gw,gh)
        elif kind=='top':result[a]=(x,y+gh+26,w,h);result[g]=(x+(w-gw)/2,y,gw,gh)
    for d in docs:
        a=report['document_owners'][d];x,y,w,h=boxes[d];ay=boxes[a][1];ah=boxes[a][3];lane=membership[a];row=slots[a][1]
        # Bay documents follow the new row footprint. Side documents stay at
        # the side of their task; the full collision audit handles exceptions.
        growth=extra[lane,row] if y>=ay+ah+15 else 0
        result[d]=(x,y+delta(a)+growth,w,h)
    if cursor:
        top=min(boxes[l][1] for l in lanes);bottom=max(boxes[l][1]+boxes[l][3] for l in lanes)
        for n,b in boxes.items():
            if n in nodes or n in docs or n in lanes:continue
            x,y,w,h=b
            if y<=top+.1 and y+h>=bottom-.1:result[n]=(x,y,w,h+cursor)
    return result


def _ports(a,b):
    x,y,w,h=a;cx=b[0]+b[2]/2;cy=b[1]+b[3]/2
    out=[(x,y+h/2),(x+w,y+h/2),(x+w/2,y),(x+w/2,y+h)]
    if y+3<=cy<=y+h-3:out.extend([(x,cy),(x+w,cy)])
    if x+3<=cx<=x+w-3:out.extend([(cx,y),(cx,y+h)])
    return list(dict.fromkeys(out))


def _edge_estimate(u,v,boxes):
    a,b=boxes[u],boxes[v];best=float('inf')
    relevant=[bb for n,bb in boxes.items() if n not in (u,v)]
    for s in _ports(a,b):
        for t in _ports(b,a):
            cx=(s[0]+t[0])/2;cy=(s[1]+t[1])/2
            for route in ([s,t],[s,(s[0],t[1]),t],[s,(t[0],s[1]),t],[s,(cx,s[1]),(cx,t[1]),t],[s,(s[0],cy),(t[0],cy),t]):
                p=compress(route)
                if len(p)<2 or any(abs(aa[0]-bb[0])>.01 and abs(aa[1]-bb[1])>.01 for aa,bb in zip(p,p[1:])):continue
                if not outward(p[0],p[1],a) or not outward(p[-1],p[-2],b):continue
                length=sum(abs(aa[0]-bb[0])+abs(aa[1]-bb[1]) for aa,bb in zip(p,p[1:]));value=90*(len(p)-2)+length*.3
                if value>=best:continue
                # Obstruction is a ranking penalty, not permission to route
                # through an object. The actual router forbids intersections.
                if any(bbox_intersect_seg(rect,aa,bb,clearance=-8) for rect in relevant for aa,bb in zip(p,p[1:])):value+=900
                if value<best:best=value
    return best if best<float('inf') else 2000


def _valid(boxes,nodes,docs,membership):
    ids=sorted(nodes|docs)
    for n in nodes:
        x,y,w,h=boxes[n];lx,ly,lw,lh=boxes[membership[n]]
        if x<lx+48 or y<ly or x+w>lx+lw or y+h>ly+lh:return False
    for i,n in enumerate(ids):
        a=boxes[n]
        for other in ids[i+1:]:
            b=boxes[other]
            if min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0])> -7.9 and min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1])> -7.9:return False
    return True


def orient(boxes,report,nodes,docs,seq,assocs,membership):
    orientations={a:'right' for a in report['pairs']};changes=[]
    def aspect(candidate):
        shapes=[candidate[n] for n in nodes|docs]
        w=max(b[0]+b[2] for b in shapes)-min(b[0] for b in shapes)
        h=max(b[1]+b[3] for b in shapes)-min(b[1] for b in shapes)
        return w/h
    aspect_floor=min(aspect(boxes),profile()['aspect_ratio_p10'])
    uv={i:(u,v) for i,u,v,_ in seq+assocs};allids=set(nodes)|set(docs)
    def objective(candidate,affected):
        ob={n:candidate[n] for n in allids}
        # Every incident edge is included, not just task->gateway. Distances
        # for the rest of the graph account for row/lane growth approximately.
        incident=sum(_edge_estimate(u,v,ob) for i,(u,v) in uv.items() if u in affected or v in affected)
        length=sum(abs(candidate[u][0]-candidate[v][0])+abs(candidate[u][1]-candidate[v][1]) for u,v in uv.values())
        growth=sum(candidate[l][3]-boxes[l][3] for l in report['role_order'])
        return incident+length*.025+growth*.12
    for a,g in sorted(report['pairs'].items()):
        current=reflow(boxes,report,orientations,nodes,docs,membership);affected={a,g};before=objective(current,affected);best=(before,'right',current)
        for kind in ('bottom','left','top'):
            trial={**orientations,a:kind};candidate=reflow(boxes,report,trial,nodes,docs,membership)
            if not _valid(candidate,nodes,docs,membership) or aspect(candidate)<aspect_floor:continue
            cost=objective(candidate,affected)
            if cost<best[0]-.01:best=(cost,kind,candidate)
        if best[1]!='right':
            orientations[a]=best[1];changes.append({'task':a,'gateway':g,'orientation':best[1],'proxy_before':round(before,2),'proxy_after':round(best[0],2)})
    result=reflow(boxes,report,orientations,nodes,docs,membership)
    anchors={d:(anchor[0]+result[d][0]-boxes[d][0],anchor[1]+result[d][1]-boxes[d][1],anchor[2],anchor[3]) for d,anchor in report.get('document_label_anchors',{}).items()}
    return result,{**report,'document_label_anchors':anchors,'decision_orientations':orientations,'orientation_changes':changes,'orientation_aspect_floor':round(aspect_floor,4),'orientation_method':'complete incident interface, approximate routes and reference aspect guard; full routing and audits required'}
