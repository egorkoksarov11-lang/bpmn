"""Few-bend corridor candidates for true graph returns; all paths still audited."""
from collections import defaultdict
from .readability import graph_returns
from bpmn_refkit.geometry import compress


def hints_factory(nodes,seq,boxes,membership,lane_boxes):
    uv={i:(u,v) for i,u,v,_ in seq};returns=graph_returns(nodes,seq);groups=defaultdict(list)
    for i in sorted(returns,key=lambda i:(-abs(boxes[uv[i][0]][0]-boxes[uv[i][1]][0]),i)):groups[membership[uv[i][0]]].append(i)
    ranks={i:j for ids in groups.values() for j,i in enumerate(ids)}
    object_boxes=[boxes[n] for n in nodes];left=min(b[0] for b in object_boxes)-18;right=max(b[0]+b[2] for b in object_boxes)+18
    def hints(eid,paths):
        if eid not in returns:return []
        u,v=uv[eid];a,b=boxes[u],boxes[v];lane=lane_boxes[membership[u]];result=[]
        channels=[lane[1]+10+14*ranks[eid],lane[1]+lane[3]-10-14*ranks[eid]]
        for cy in channels:
            for s in [(a[0]+a[2],a[1]+a[3]/2),(a[0],a[1]+a[3]/2)]:
                for t in [(b[0],b[1]+b[3]/2),(b[0]+b[2],b[1]+b[3]/2)]:
                    sx=s[0]+(18 if s[0]>a[0] else -18);tx=t[0]+(-18 if t[0]==b[0] else 18)
                    result.append(compress([s,(sx,s[1]),(sx,cy),(tx,cy),(tx,t[1]),t]))
                    for outer in (left,right):result.append(compress([s,(outer,s[1]),(outer,t[1]),t]))
            for top in (True,False):
                s=(a[0]+a[2]/2,a[1] if top else a[1]+a[3]);t=(b[0]+b[2]/2,b[1] if top else b[1]+b[3]);result.append(compress([s,(s[0],cy),(t[0],cy),t]))
        return result
    return hints
