"""Place a productive role spine and attach local handoff/exception episodes.

Structural anchors are recomputed from the graph on every invocation. Folding
uses complete reading bands, rather than independently stacking arbitrary pairs.
"""
from collections import Counter,defaultdict,deque
from bpmn_refkit.model import TAG_TASK
from .patterns import analyze
from .readability import graph_returns
from .scratch_layout import semantic_document_owners
from .attachment_axes import attachment_axes
from .skyline_layout import compact_rows


def phase_slots(nodes,docs,seq,assocs,member,lanes,original,*,columns=8,attach_next=False):
    returns=graph_returns(nodes,seq);motifs=analyze(nodes,[e for e in seq if e[0] not in returns],member,original,pair_merges=False,penalize_stops=True)
    feedback=returns|set(motifs['feedback_edges']);owner=motifs['owner'];inc=defaultdict(set);out=defaultdict(set)
    for eid,u,v,_ in seq:
        a,b=owner[u],owner[v]
        if a!=b and eid not in feedback:out[a].add(b);inc[b].add(a)
    bases={};role_rows=defaultdict(int);components=[]
    for component in motifs['components']:
        allowed=set(component['nodes']);counts=Counter(member[n] for n in allowed if nodes[n]['kind'] in TAG_TASK)
        dominant=min(counts,key=lambda l:(-counts[l],l)) if counts else member[component['backbone'][0]]
        path=component['backbone'];anchors=[n for n in path if member[n]==dominant]
        if not anchors:anchors=path[:1]
        phases={n:float(i) for i,n in enumerate(anchors)}
        def nearest(n,adj):
            todo=deque([(n,0)]);seen={n};found=[];depth=None
            while todo:
                u,d=todo.popleft()
                if depth is not None and d>depth:break
                if u in phases:found.append(u);depth=d;continue
                for v in sorted(adj[u]&allowed):
                    if v not in seen:seen.add(v);todo.append((v,d+1))
            return found
        inferred={}
        for n in sorted(allowed-set(anchors)):
            before=nearest(n,inc);after=nearest(n,out)
            lo=max((phases[v] for v in before),default=None);hi=min((phases[v] for v in after),default=None)
            if lo is None:phase=hi if hi is not None else 0.
            elif hi is None:phase=lo
            else:phase=hi if attach_next else lo
            inferred[n]=phase
        phases.update(inferred);cap=max(1,min(columns,len(anchors)))
        occupancy=set();offsets={l:role_rows[l] for l in lanes}
        # Main sequence owns its reading band. Other nodes occupy nearby local
        # bands and do not push every later phase one whole column to the right.
        for n in anchors+sorted(allowed-set(anchors),key=lambda n:(n not in path,phases[n],n)):
            stage=int(phases[n]);band=stage//cap;col=stage%cap
            if band%2:col=cap-1-col
            row=offsets[member[n]]+band*(len(allowed)+1)
            if n not in anchors and member[n]==dominant:row+=1
            while (member[n],col,row) in occupancy:row+=1
            occupancy.add((member[n],col,row));bases[n]=(float(col),row)
        for l in lanes:
            used=[r for n,(c,r) in bases.items() if member[n]==l]
            if used:role_rows[l]=max(used)+1
        components.append({'primary_role':dominant,'anchor_count':len(anchors),'band_width':cap,'anchor_macros':anchors})
    return bases,motifs,components


def phase_proposal(nodes,docs,seq,assocs,member,lanes,original,*,columns=8,attach_next=False):
    bases,motifs,components=phase_slots(nodes,docs,seq,assocs,member,lanes,original,columns=columns,attach_next=attach_next)
    # Equal semantic columns share X across roles. Full group dimensions are
    # retained and measured caption bays are packed afterwards.
    widths=defaultdict(float);heights=defaultdict(float)
    for n,(c,r) in bases.items():
        w,h=original[n][2:];g=motifs['pairs'].get(n)
        if g:w+=original[g][2]+28
        widths[c]=max(widths[c],w);heights[member[n],r]=max(heights[member[n],r],h)
    xs={};cursor=120
    for c in sorted(widths):xs[c]=cursor;cursor+=widths[c]+40
    ys={};cursor=100
    for l in lanes:
        for r in sorted({r for n,(c,r) in bases.items() if member[n]==l}):ys[l,r]=cursor;cursor+=heights[l,r]+180
        cursor+=80
    basis=dict(original)
    for n,(c,r) in bases.items():
        x,y=xs[c],ys[member[n],r];w,h=original[n][2:];basis[n]=(x,y,w,h)
        if n in motifs['pairs']:
            g=motifs['pairs'][n];gw,gh=original[g][2:];basis[g]=(x+w+28,y+h/2-gh/2,gw,gh)
    for d,n in semantic_document_owners(nodes,docs,assocs,basis).items():
        x,y,w,h=basis[n];dw,dh=original[d][2:];basis[d]=(x,y+h+24,dw,dh)
    for index,l in enumerate(lanes):basis[l]=(30,65+index*1000,max(1000,sum(widths.values())),1000)
    boxes,report=attachment_axes(nodes,docs,seq,assocs,member,lanes,basis,gap_size=32,compact_bays=True,overlap_corridors=True)
    boxes,report=compact_rows(boxes,report,nodes,docs,member,lanes,seq)
    report.update(external_engine='semantic-role-spine-episodes',source_geometry_used=False,spine_episodes=components,phase_columns=columns,attach_to_next=attach_next)
    return boxes,report
