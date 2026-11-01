"""Deterministic optimization of correction blocks, with the display spine locked."""
from collections import defaultdict
import random,math


def optimize_slots(slots,motifs,seq,membership,lane_order,iterations=1600):
    original=dict(slots);locked={n for c in motifs['components'] for n in c['backbone']}
    movable=sorted(set(slots)-locked);owner=motifs['owner']
    edges=sorted({(owner[u],owner[v]) for _,u,v,_ in seq if owner[u]!=owner[v]})
    maxcol=max(c for c,r in slots.values());maxrow={l:max((r for n,(c,r) in slots.items() if membership.get(n)==l),default=0) for l in lane_order}
    base={};y=0
    for lane in lane_order:base[lane]=y;y+=maxrow[lane]+1.3
    def cost(candidate):
        xy={n:(c*2.3,base[membership.get(n)]+r) for n,(c,r) in candidate.items()}
        values=[];length=0
        for u,v in edges:
            a,b=xy[u],xy[v];length+=abs(a[0]-b[0])+abs(a[1]-b[1]);values.append((u,v,a,b))
        crossings=0
        def orient(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        for i,(u,v,a,b) in enumerate(values):
            for uu,vv,c,d in values[i+1:]:
                if u in (uu,vv) or v in (uu,vv):continue
                if max(a[0],b[0])<min(c[0],d[0]) or max(c[0],d[0])<min(a[0],b[0]):continue
                if orient(a,b,c)*orient(a,b,d)<-.0001 and orient(c,d,a)*orient(c,d,b)<-.0001:crossings+=1
        height_penalty=sum(max((r for n,(c,r) in candidate.items() if membership.get(n)==lane),default=0)*35 for lane in lane_order)
        return crossings*500+length*8+height_penalty
    current=dict(slots);initial=cost(current);value=initial;best=dict(current);best_value=value;rng=random.Random(23)
    if not movable:return slots,{'initial_cost':initial,'final_cost':initial,'moves':0}
    for i in range(iterations):
        n=rng.choice(movable);lane=membership.get(n);target=(rng.randrange(maxcol+1),rng.randrange(maxrow[lane]+1))
        if target==current[n]:continue
        occupied=[k for k,p in current.items() if membership.get(k)==lane and p==target]
        if any(k in locked for k in occupied) or len(occupied)>1:continue
        trial=dict(current)
        if occupied:trial[occupied[0]]=current[n]
        trial[n]=target;new_value=cost(trial);temperature=300*(1-i/iterations)**2+.1
        if new_value<value or rng.random()<math.exp(min(0,(value-new_value)/temperature)):
            current=trial;value=new_value
            if value<best_value:best=dict(current);best_value=value
    return best,{'initial_cost':initial,'final_cost':best_value,'moves':sum(best[n]!=original[n] for n in best),'iterations':iterations,'seed':23}
