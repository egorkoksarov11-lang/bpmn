"""Semantic motifs for layout only: graph arcs are classified, never deleted."""
from collections import defaultdict,deque
import heapq,re
from bpmn_refkit.model import TAG_TASK,TAG_GATE


def analyze(nodes,seq,membership,original,*,pair_merges=True,penalize_stops=False):
    def repair(n):
        name=nodes[n].get('name','').lower()
        return (nodes[n]['kind'] in TAG_TASK and bool(re.search(r'уточн|исправ|устран|доработ|расхожд|измененн|недоста|незакрыт|повторн|отклонени',name)) or
                penalize_stops and bool(re.search(r'отмен|прекращ|недопуск|отказ|невозможн|cancel|reject|abort',name)))
    def reading(n):
        x,y,w,h=original[n];return (x+w/2,y+h/2,n)
    outgoing=defaultdict(list);incoming=defaultdict(list)
    for eid,u,v,name in seq:outgoing[u].append((eid,v,name));incoming[v].append((eid,u,name))
    # Pair an operation with its decision. Avoid claiming the same gateway twice.
    claimed=set();pairs={}
    for u in sorted(nodes,key=reading):
        successors=outgoing[u]
        if nodes[u]['kind'] in TAG_TASK and len(successors)==1:
            v=successors[0][1]
            if nodes[v]['kind'] in TAG_GATE and membership.get(u)==membership.get(v) and v not in claimed and (pair_merges or len(incoming[v])==1):
                pairs[u]=v;claimed.add(v)
    owner={n:n for n in nodes}
    for u,v in pairs.items():owner[v]=u
    macro_nodes={n:[n]+([pairs[n]] if n in pairs else []) for n in nodes if owner[n]==n}
    # Connected components keep independent starts/cycles as distinct regions.
    neighbours=defaultdict(set)
    for _,u,v,_ in seq:
        a,b=owner[u],owner[v]
        if a!=b:neighbours[a].add(b);neighbours[b].add(a)
    components=[];seen=set()
    for n in sorted(macro_nodes,key=reading):
        if n in seen:continue
        stack=[n];component=[];seen.add(n)
        while stack:
            u=stack.pop();component.append(u)
            for v in sorted(neighbours[u],key=reading):
                if v not in seen:seen.add(v);stack.append(v)
        components.append(component)
    blocks=[];feedback=[]
    for component in components:
        allowed=set(component);dag=defaultdict(list);indegree={n:0 for n in component}
        def reachable(start,target):
            pending=[start];visited=set()
            while pending:
                u=pending.pop()
                if u==target:return True
                if u not in visited:visited.add(u);pending.extend(dag[u])
            return False
        edges=[]
        for eid,u,v,name in seq:
            a,b=owner[u],owner[v]
            if a in allowed and b in allowed and a!=b:edges.append((eid,a,b))
        # Protect an actual start-to-end path before considering DI hints.
        # A later operation may be slightly left of its predecessor (handoff),
        # which must never turn the semantic spine into a dead end.
        full=defaultdict(list)
        for eid,a,b in edges:full[a].append((eid,b))
        starts_in=[owner[n] for n in nodes if nodes[n]['kind']=='startEvent' and owner[n] in allowed]
        ends_in={owner[n] for n in nodes if nodes[n]['kind']=='endEvent' and owner[n] in allowed}
        protected=set()
        for start in starts_in:
            pending=[(0,reading(start),start)];parents={start:None};dist={start:0};found=None
            while pending:
                distance,_,u=heapq.heappop(pending)
                if distance!=dist[u]:continue
                if u in ends_in:found=u;break
                for eid,v in sorted(full[u],key=lambda p:reading(p[1])):
                    cost=distance+1+30*sum(repair(n) for n in macro_nodes[v])
                    if cost<dist.get(v,float('inf')):
                        dist[v]=cost;parents[v]=(u,eid);heapq.heappush(pending,(cost,reading(v),v))
            if found is not None:
                while parents[found] is not None:
                    previous,eid=parents[found];protected.add(eid);found=previous
        # Original DI is a stability hint for feedback identification, not a
        # numbered-stage parser. Additional cycles are broken for ranking only.
        for eid,a,b in sorted(edges,key=lambda e:(e[0] not in protected,reading(e[2])[0]<reading(e[1])[0]-20,reading(e[1]),reading(e[2]),e[0])):
            if (eid not in protected and reading(b)[0]<reading(a)[0]-20) or reachable(b,a):feedback.append(eid);continue
            if b not in dag[a]:dag[a].append(b);indegree[b]+=1
        queue=[(reading(n),n) for n in component if indegree[n]==0];heapq.heapify(queue);order=[]
        while queue:
            _,u=heapq.heappop(queue);order.append(u)
            for v in dag[u]:
                indegree[v]-=1
                if indegree[v]==0:heapq.heappush(queue,(reading(v),v))
        ends={owner[n] for n in nodes if n in owner and owner[n] in allowed and nodes[n]['kind']=='endEvent'}
        best={};next_node={}
        for u in reversed(order):
            choices=[v for v in dag[u] if v in best]
            if u in ends or not ends and not dag[u]:best[u]=sum(-4 if repair(n) else 1 for n in macro_nodes[u]);continue
            if choices:
                v=max(choices,key=lambda n:(best[n],-reading(n)[0]));best[u]=sum(-4 if repair(n) else 1 for n in macro_nodes[u])+best[v];next_node[u]=v
        starts=[owner[n] for n in nodes if nodes[n]['kind']=='startEvent' and owner[n] in allowed and owner[n] in best]
        candidates=starts or [n for n in order if n in best]
        if candidates:
            u=max(candidates,key=lambda n:best[n]);backbone=[]
            while True:
                backbone.append(u)
                if u not in next_node:break
                u=next_node[u]
        else:backbone=order[:1]
        blocks.append({'nodes':component,'backbone':backbone})
    return {'pairs':pairs,'owner':owner,'macros':macro_nodes,'components':blocks,'feedback_edges':sorted(set(feedback)),
            'outgoing':dict(outgoing),'incoming':dict(incoming)}
