"""Semantic motifs for layout only: graph arcs are classified, never deleted."""
from collections import defaultdict,deque
import heapq
from bpmn_refkit.model import TAG_TASK,TAG_GATE


def analyze(nodes,seq,membership,original,*,pair_merges=True,penalize_stops=False,_protected_paths=None):
    # Topology alone cannot distinguish a cancellation from another terminal
    # branch. Never infer business meaning from a task's wording.
    def repair(n):return False
    outgoing_distance=defaultdict(list);indeg=defaultdict(int)
    for _,u,v,*_ in seq:outgoing_distance[u].append(v);indeg[v]+=1
    starts=sorted(n for n,o in nodes.items() if o['kind']=='startEvent' or not indeg[n])
    graph_distance={n:0 for n in starts};queue=deque(starts)
    while queue:
        u=queue.popleft()
        for v in sorted(outgoing_distance[u]):
            if v not in graph_distance:graph_distance[v]=graph_distance[u]+1;queue.append(v)
    def reading(n):return (graph_distance.get(n,len(nodes)),n)
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
    blocks=[];feedback=[];improved_protections={}
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
        # Protect a real start-to-end route before cycle cuts. A bounded
        # complete-path search below can replace this initial protection;
        # input positions and display labels never determine the spine.
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
        if _protected_paths is not None and frozenset(component) in _protected_paths:
            protected=set(_protected_paths[frozenset(component)])
        # Complete graph paths are protected before cycle cuts. These cuts
        # affect ranking only; all original BPMN transitions stay intact.
        for eid,a,b in sorted(edges,key=lambda e:(e[0] not in protected,reading(e[1]),reading(e[2]),e[0])):
            if reachable(b,a):feedback.append(eid);continue
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
        if _protected_paths is None and starts_in and ends_in:
            from .graph_topology import longest_complete_path
            weights={n:len(macro_nodes[n]) for n in component}
            path,edges=longest_complete_path(full,starts_in,ends_in,weights)
            current=sum(weights[n] for n in backbone);proposed=sum(weights[n] for n in path)
            # Avoid destabilizing the whole layout for one tie or one tiny gain.
            import math
            if proposed>=current+max(2,math.ceil(current*.05)):
                improved_protections[frozenset(component)]=edges
        blocks.append({'nodes':component,'backbone':backbone})
    if improved_protections:
        result=analyze(nodes,seq,membership,original,pair_merges=pair_merges,penalize_stops=penalize_stops,_protected_paths=improved_protections)
        result['spine_protection_method']='bounded complete graph-path search before cycle cuts'
        return result
    return {'pairs':pairs,'owner':owner,'macros':macro_nodes,'components':blocks,'feedback_edges':sorted(set(feedback)),
            'outgoing':dict(outgoing),'incoming':dict(incoming)}
