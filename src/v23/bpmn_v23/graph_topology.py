"""Graph-only regions; identifiers are opaque deterministic tie breakers.

No step/role/flow names, step numbers, or input positions are consulted.
"""
from collections import defaultdict,deque
from bpmn_refkit.model import TAG_TASK as TASK

def adjacency(nodes,edges):
 out={n:set() for n in nodes};inc={n:set() for n in nodes}
 for _,u,v in edges:out[u].add(v);inc[v].add(u)
 return out,inc
def reach(starts,out,stop=frozenset()):
 seen=set();q=list(starts)
 while q:
  u=q.pop()
  if u in seen or u in stop:continue
  seen.add(u);q.extend(out[u]-seen)
 return seen
def scc(nodes,out):
 # Iterative Kosaraju, so deep chains do not consume Python recursion depth.
 seen=set();order=[]
 for root in sorted(nodes):
  if root in seen:continue
  seen.add(root);stack=[(root,iter(sorted(out[root])))]
  while stack:
   u,it=stack[-1]
   try:
    v=next(it)
    if v not in seen:seen.add(v);stack.append((v,iter(sorted(out[v]))))
   except StopIteration:order.append(u);stack.pop()
 rev={n:set() for n in nodes}
 for u in nodes:
  for v in out[u]:rev[v].add(u)
 result=[];seen=set()
 for u in reversed(order):
  if u in seen:continue
  comp=reach([u],rev,seen);seen|=comp;result.append(comp)
 return result

def dominators(nodes,out,inc,roots):
 """Sets only for nodes reachable from declared/in-degree-zero roots.

 Multiple roots act as children of a virtual root. Closed unreachable cycles
 remain undefined rather than receiving a fabricated semantic entry.
 """
 active=reach(roots,out);dom={n:({n} if n in roots else set(active)) for n in active};changed=True
 while changed:
  changed=False
  for n in sorted(active-set(roots)):
   preds=inc[n]&active
   value={n}|(set.intersection(*(dom[p] for p in preds)) if preds else set())
   if value!=dom[n]:dom[n]=value;changed=True
 return dom

def recognize(nodes,edges,lanes):
 out,inc=adjacency(nodes,edges);roots={n for n in nodes if nodes[n]=='startEvent' or not inc[n]};ends={n for n in nodes if nodes[n]=='endEvent' or not out[n]};dom=dominators(nodes,out,inc,roots);post=dominators(nodes,inc,out,ends)
 components=scc(nodes,out);which={n:i for i,c in enumerate(components) for n in c};loops=[]
 for eid,tail,header in edges:
  if header not in dom.get(tail,set()):continue
  body={header,tail};todo=[tail] if tail!=header else []
  while todo:
   v=todo.pop()
   for p in inc[v]:
    if p not in body:body.add(p);todo.append(p)
  entries=[i for i,u,v in edges if v in body and u not in body]
  exits=[i for i,u,v in edges if u in body and v not in body]
  ports=[dict(edge=i,source=u,target=v,direction='in' if v in body else 'out') for i,u,v in edges if (u in body)!=(v in body)]
  loops.append(dict(type='natural_loop',header=header,tail=tail,backedge=eid,nodes=sorted(body),entries=entries,exits=exits,boundary_ports=ports))
 pairs=[];branches=[];terminals=[]
 for n in sorted(nodes):
  if nodes[n] in TASK and len(out[n])==1:
   g=next(iter(out[n]))
   if nodes[g].endswith('Gateway') and len(out[g])>=2:pairs.append(dict(type='task_decision',task=n,gateway=g,same_lane=lanes.get(n)==lanes.get(g) and n in lanes,gateway_kind=nodes[g],external_gateway_inputs=sorted(inc[g]-{n})))
  if not nodes[n].endswith('Gateway') or len(out[n])<2:continue
  candidates=post.get(n,set())-{n};join=max(sorted(candidates),key=lambda x:len(post[x])) if candidates else None
  if join is not None:
   region={n}|reach(out[n],out,{join});region.add(join)
   incoming=[i for i,u,v in edges if v in region-{n} and u not in region];outside_exits=[i for i,u,v in edges if u in region-{join} and v not in region]
   branches.append(dict(type='split_join',split=n,join=join,gateway_kind=nodes[n],nodes=sorted(region),strict_single_entry_exit=not incoming and not outside_exits,external_inputs=incoming,external_outputs=outside_exits))
  for v in sorted(out[n]):
   chain=[n,v];cur=v
   while nodes[cur]!='endEvent' and len(out[cur])==1 and len(inc[cur])==1 and len(chain)<8:
    nxt=next(iter(out[cur]))
    if nxt in chain:break
    chain.append(nxt);cur=nxt
   if nodes[cur]=='endEvent':terminals.append(dict(type='terminal_branch',split=n,nodes=chain))
 handoffs=[dict(type='role_handoff',edge=i,source=u,target=v,source_lane=lanes[u],target_lane=lanes[v]) for i,u,v in edges if u in lanes and v in lanes and lanes[u]!=lanes[v]]
 cyclic=[dict(nodes=sorted(c),entry_nodes=sorted({v for _,u,v in edges if v in c and u not in c}),multi_entry=len({v for _,u,v in edges if v in c and u not in c})>1) for c in components if len(c)>1 or any(n in out[n] for n in c)]
 return dict(task_decisions=pairs,natural_loops=loops,split_joins=branches,terminal_branches=terminals,role_handoffs=handoffs,cyclic_components=cyclic,not_reachable_from_entry=sorted(set(nodes)-set(dom)),not_reaching_exit=sorted(set(nodes)-set(post)),cyclic_edge_ids=sorted(i for i,u,v in edges if which[u]==which[v] and (len(components[which[u]])>1 or u==v)))


def region_stages(nodes,seq,member,motifs,chunk=2):
    """Small SESE/loop groups, then adjacent backbone groups; disconnected safe."""
    regions=recognize({n:o['kind'] for n,o in nodes.items()},[(i,u,v) for i,u,v,*_ in seq],member)
    owner=motifs['owner'];parent={n:n for n in motifs['macros']};sets={n:{n} for n in parent}
    def root(n):
        while parent[n]!=n:n=parent[n]
        return n
    candidates=[r for r in regions['split_joins'] if r['strict_single_entry_exit']]+regions['natural_loops']
    for region in sorted(candidates,key=lambda r:(len(r['nodes']),tuple(r['nodes']))):
        roots={root(owner[n]) for n in region['nodes']};merged=set().union(*(sets[r] for r in roots))
        if not 1<len(merged)<=8:continue
        head=min(roots)
        for r in roots:parent[r]=head
        sets[head]=merged
    inc=defaultdict(set);out=defaultdict(set)
    for i,u,v,*_ in seq:
        a,b=owner[u],owner[v]
        if a!=b:inc[b].add(a);out[a].add(b)
    stages={};offset=0
    for component in motifs['components']:
        allowed=set(component['nodes']);anchors=component['backbone'] or sorted(allowed)[:1];groups={}
        for n in anchors:
            r=root(n)
            if r not in groups:groups[r]=offset+len(groups)//chunk
        for n in allowed:
            if root(n) in groups:stages[n]=groups[root(n)]
        for n in sorted(allowed-set(stages)):
            found=[]
            for adj in (inc,out):
                queue=deque([(n,0)]);seen={n};depth=None
                while queue:
                    u,d=queue.popleft()
                    if depth is not None and d>depth:break
                    if u in stages:found.append(stages[u]);depth=d;continue
                    for v in sorted(adj[u]&allowed):
                        if v not in seen:seen.add(v);queue.append((v,d+1))
                if found:break
            stages[n]=min(found) if found else offset
        offset=max(stages.values(),default=offset)+1
    motifs['graph_regions']=regions
    return stages


def longest_complete_path(adjacency,starts,ends,weights,beam_width=256,per_vertex=8):
    """Bounded simple-path beam; protect complete graph routes before cutting cycles.

    Path weight counts visible graph vertices. No edge/node display text enters
    the search. This is a heuristic, not an exact longest-path solver.
    """
    if not starts:return [],[]
    beam=[(n,(n,),(),frozenset([n]),weights[n]) for n in sorted(set(starts))];best=None
    for _ in range(len(weights)+1):
        next_states=[]
        for u,path,edges,seen,value in beam:
            if u in ends:
                candidate=(value,path,edges)
                if best is None or value>best[0] or value==best[0] and path<best[1]:best=candidate
                continue
            for eid,v in sorted(adjacency[u]):
                if v not in seen:next_states.append((v,path+(v,),edges+(eid,),seen|{v},value+weights[v]))
        buckets={}
        for state in sorted(next_states,key=lambda s:(-s[4],s[1],s[2])):
            if len(buckets.setdefault(state[0],[]))<per_vertex:buckets[state[0]].append(state)
        beam=sorted([state for values in buckets.values() for state in values],key=lambda s:(-s[4],s[1],s[2]))[:beam_width]
        if not beam:break
    return (list(best[1]),list(best[2])) if best else ([],[])
