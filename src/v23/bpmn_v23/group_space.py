"""Adaptive geometric repair of a graph-selected group; never edit BPMN logic."""
from collections import defaultdict
from .responsive_labels import gap


def repair_space(boxes,labels,placement,nodes,docs,owners,member,lanes,anchor,max_neighbors=8,defer_documents=False):
    out=dict(boxes);caps=dict(labels);requested=set(placement);changed=set();pushed=set()
    def shift(n,dx,dy):
        if abs(dx)+abs(dy)<.01:return
        x,y,w,h=out[n];out[n]=(x+dx,y+dy,w,h);changed.add(n)
        if n in caps:x,y,w,h=caps[n];caps[n]=(x+dx,y+dy,w,h)
        for d,owner in owners.items():
            if owner!=n:continue
            x,y,w,h=out[d];out[d]=(x+dx,y+dy,w,h);changed.add(d)
            if d in caps:x,y,w,h=caps[d];caps[d]=(x+dx,y+dy,w,h)
    for n,b in placement.items():shift(n,b[0]-out[n][0],b[1]-out[n][1])
    # Push a blocking activity with its own attachments; let expansion of the
    # role bands absorb the resulting height. Keep the requested pattern intact.
    for _ in range(max_neighbors+2):
        conflict=None
        for n in sorted(changed):
            if defer_documents and n in docs:continue
            for other in sorted(nodes.keys() if defer_documents else nodes.keys()|docs.keys()):
                if n==other or gap(out[n],out[other])>=5:continue
                if owners.get(n)==other or owners.get(other)==n:continue
                conflict=n,other;break
            if conflict:break
        if conflict is None:break
        n,other=conflict;root=owners.get(other,other)
        if root in requested or root==anchor:
            root=owners.get(n,n);n,other=other,n
        if root in requested or root==anchor or root not in nodes:return None,'pinned-pattern-collision'
        if len(pushed|{root})>max_neighbors:return None,'neighbor-limit'
        blocker=out[n];target=out[other];rx,ry,rw,rh=out[root]
        # The object may be a document attached to root; translate the whole
        # attachment group by the displacement needed by the colliding glyph.
        shifts=[(blocker[0]+blocker[2]+28-target[0],0),(blocker[0]-28-target[2]-target[0],0),(0,blocker[1]+blocker[3]+28-target[1]),(0,blocker[1]-28-target[3]-target[1])]
        lane=boxes[member[root]]
        def cost(delta):
            dx,dy=delta;bad=rx+dx<lane[0]+56
            others=sum(gap((out[v][0]+dx,out[v][1]+dy,*out[v][2:]),out[k])<5 for v in [root]+[d for d,o in owners.items() if o==root] for k in requested|{anchor} if k!=v)
            return (bad,others,abs(dx)+abs(dy)+(.1 if dy else 0),dx,dy)
        dx,dy=min(shifts,key=cost)
        if rx+dx<lane[0]+56:return None,'left-role-header'
        shift(root,dx,dy);pushed.add(root)
    else:return None,'collision-repair-limit'
    collision_ids=nodes.keys() if defer_documents else nodes.keys()|docs.keys()
    if any(gap(out[a],out[b])<5 for a in changed if a in collision_ids for b in collision_ids if a!=b and owners.get(a)!=b and owners.get(b)!=a):return None,'remaining-shape-collision'
    role_of=lambda n:member.get(owners.get(n,n))
    role_objects=defaultdict(list)
    for n in nodes.keys()|docs.keys():
        if role_of(n) in lanes:role_objects[role_of(n)].append((n,out[n]))
    for n,b in caps.items():
        if n in nodes or n in docs:
            if role_of(n) in lanes:role_objects[role_of(n)].append((n,b))
    total_shift=0;expanded=[];role_offsets={}
    for lane in sorted(lanes,key=lambda l:(boxes[l][1],l)):
        lx,ly,lw,lh=boxes[lane];pieces=role_objects[lane]
        if any(b[0]<lx+56 for _,b in pieces):return None,'left-role-header'
        minimum=min((b[1] for _,b in pieces),default=ly+16);maximum=max((b[1]+b[3] for _,b in pieces),default=ly+lh-16)
        extra_top=max(0,ly+16-minimum);height=max(lh,maximum+extra_top+16-ly);dy=total_shift+extra_top
        role_offsets[lane]=dy
        for n in sorted(nodes):
            if member[n]==lane:shift(n,0,dy)
        # Captions for control flows will be reseeded on rerouted paths.
        out[lane]=(lx,ly+total_shift,lw,height)
        if height>lh+.1:expanded.append(lane)
        total_shift+=height-lh
    width=max([boxes[l][0]+boxes[l][2] for l in lanes]+[b[0]+b[2]+24 for n,b in out.items() if n in nodes or n in docs]+[b[0]+b[2]+12 for n,b in caps.items() if n in nodes or n in docs])
    for lane in lanes:x,y,w,h=out[lane];out[lane]=(x,y,max(w,width-x),h)
    # Pool frames also follow their role bands.
    for n in set(boxes)-nodes.keys()-docs.keys()-lanes.keys():
        x,y,w,h=out[n];bottom=max(out[l][1]+out[l][3] for l in lanes);out[n]=(x,y,max(w,width-x),max(h,bottom-y))
    changed={n for n,b in out.items() if b!=boxes[n]}
    return (out,caps,changed,{'neighbor_roots_moved':len(pushed),'expanded_role_bands':len(expanded),'role_offsets':role_offsets}),None
