"""Place interacting role bands close using generated endpoint positions only."""
from collections import defaultdict


def vertical_cost(order,heights,weights,offsets):
    before=set();total=0.;all_roles=set(order)
    for role in order:
        after=all_roles-before-{role};h=heights[role]
        total+=h*sum(weights[a,b] for a in before for b in after)
        total+=sum(offsets[role,a] for a in before)
        total+=sum(h*weights[role,b]-offsets[role,b] for b in after)
        before.add(role)
    return total


def optimize_order(roles,heights,weights,offsets):
    """Exact subset DP up to 13 roles; deterministic local search above that."""
    roles=tuple(roles);n=len(roles)
    if n>13:
        order=roles;best=vertical_cost(order,heights,weights,offsets)
        while True:
            trials=[]
            for i in range(n):
                rest=list(order);role=rest.pop(i)
                for j in range(n):
                    trial=tuple(rest[:j]+[role]+rest[j:]);trials.append((vertical_cost(trial,heights,weights,offsets),trial))
            value,trial=min(trials)
            if value>=best-1e-6:return list(order),best,'deterministic insertion search'
            order,best=trial,value
    table={0:(0.,())};full=(1<<n)-1
    for mask in range(1<<n):
        cost,order=table[mask];left=[roles[j] for j in range(n) if mask>>j&1]
        for i,role in enumerate(roles):
            if mask>>i&1:continue
            right=[roles[j] for j in range(n) if not mask>>j&1 and j!=i];h=heights[role]
            extra=h*sum(weights[a,b] for a in left for b in right)+sum(offsets[role,a] for a in left)+sum(h*weights[role,b]-offsets[role,b] for b in right)
            key=mask|1<<i;candidate=(round(cost+extra,6),order+(i,))
            if key not in table or candidate<table[key]:table[key]=candidate
    value,indices=table[full]
    return [roles[i] for i in indices],value,'exact subset dynamic programming'


def reorder_lanes(boxes,report,nodes,docs,seq,member,lanes,requested='auto'):
    roles=sorted(lanes,key=lambda l:(boxes[l][1],l));heights={l:boxes[l][3] for l in roles};weights=defaultdict(float);offsets=defaultdict(float)
    for _,u,v,_ in seq:
        a,b=member[u],member[v]
        if a==b:continue
        weights[a,b]+=1;weights[b,a]+=1
        offsets[a,b]+=boxes[u][1]+boxes[u][3]/2-boxes[a][1]
        offsets[b,a]+=boxes[v][1]+boxes[v][3]/2-boxes[b][1]
    old_cost=vertical_cost(roles,heights,weights,offsets)
    if requested=='auto':order,value,method=optimize_order(roles,heights,weights,offsets)
    else:
        order=list(requested)
        if len(order)!=len(roles) or set(order)!=set(roles):raise ValueError('Explicit lane order must contain every role ID exactly once')
        value=vertical_cost(order,heights,weights,offsets);method='explicit user role order'
    cursor=min(boxes[l][1] for l in roles);shift={};out=dict(boxes)
    for role in order:
        x,y,w,h=boxes[role];shift[role]=cursor-y;out[role]=(x,cursor,w,h);cursor+=h
    owners=report['document_owners']
    flow_owner={i:u for i,u,_,_ in seq}
    def role_of(n):
        owner=owners.get(n,n);return member.get(flow_owner.get(owner,owner))
    for n,b in boxes.items():
        if n not in nodes and n not in docs:continue
        role=role_of(n)
        if role is not None:x,y,w,h=b;out[n]=(x,y+shift[role],w,h)
    captions={}
    for n,(x,y,w,h) in report.get('reserved_captions',{}).items():
        role=role_of(n);captions[n]=(x,y+shift.get(role,0),w,h)
    detail={'method':method,'objective':'sum of vertical distances of actual cross-role sequence-flow endpoints; fixed within-role geometry',
            'before':old_cost,'after':value,'order_ids':order,'order_names':[lanes[l] for l in order],'previous_order_ids':roles}
    return out,{**report,'reserved_captions':captions,'lane_order_optimization':detail}
