"""Graph-only motif recognition plus DI diagnostics; never edits a BPMN model.

Run --help. IDs/names/coordinates do not determine motif membership. Candidate
regions can overlap and are not instructions to contract the semantic graph.
"""
from pathlib import Path
from collections import defaultdict,deque,Counter
from statistics import median
import xml.etree.ElementTree as ET
import argparse,json,hashlib,math,itertools
B='http://www.omg.org/spec/BPMN/20100524/MODEL';BD='http://www.omg.org/spec/BPMN/20100524/DI';DC='http://www.omg.org/spec/DD/20100524/DC';DI='http://www.omg.org/spec/DD/20100524/DI'
TASK={'task','userTask','manualTask','serviceTask','scriptTask','businessRuleTask','sendTask','receiveTask','callActivity','subProcess','transaction'}
def local(e):return e.tag.rsplit('}',1)[-1]
def parse(path):
 raw=Path(path).read_bytes()
 if len(raw)>25*1024*1024 or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:raise ValueError('Unsupported XML input')
 r=ET.fromstring(raw);identified=[e for e in r.iter() if e.get('id')]
 if len({e.get('id') for e in identified})!=len(identified):raise ValueError('Duplicate BPMN ID')
 els={e.get('id'):e for e in identified};nodes={i:local(e) for i,e in els.items() if local(e) in TASK or local(e).endswith('Gateway') or local(e).endswith('Event')};edges=[(i,e.get('sourceRef'),e.get('targetRef')) for i,e in els.items() if local(e)=='sequenceFlow'];lanes={};boxes={};paths={}
 for e in r.iter():
  if e.tag==f'{{{B}}}lane':
   for x in e.findall(f'{{{B}}}flowNodeRef'):lanes[x.text]=e.get('id')
  if e.tag==f'{{{BD}}}BPMNShape':
   x=e.find(f'{{{DC}}}Bounds')
   if x is not None:boxes[e.get('bpmnElement')]=tuple(float(x.get(k)) for k in ('x','y','width','height'))
  if e.tag==f'{{{BD}}}BPMNEdge':paths[e.get('bpmnElement')]=[(float(x.get('x')),float(x.get('y'))) for x in e.findall(f'{{{DI}}}waypoint')]
 if any(u not in nodes or v not in nodes for _,u,v in edges):raise ValueError('Dangling sequenceFlow endpoint')
 # Per-process scopes are intentional: nested subprocesses need their own graph.
 parent={c:p for p in r.iter() for c in p};scopes=defaultdict(list)
 for i in nodes:
  p=parent.get(els[i])
  while p is not None and local(p) not in ('process','subProcess','transaction'):p=parent.get(p)
  scopes[p.get('id') if p is not None else None].append(i)
 node_scope={n:s for s,ns in scopes.items() for n in ns}
 if any(node_scope[u]!=node_scope[v] for _,u,v in edges):raise ValueError('Cross-scope sequenceFlow')
 if any(not all(math.isfinite(x) for x in b) or b[2]<=0 or b[3]<=0 for b in boxes.values()):raise ValueError('Invalid DI bounds')
 links=[]
 for i,e in els.items():
  kind=local(e)
  if kind=='association':links.append((i,e.get('sourceRef'),e.get('targetRef')))
  elif kind=='dataInputAssociation':
   owner=parent[e].get('id');links.extend((i,x.text,owner) for x in e.findall(f'{{{B}}}sourceRef'))
  elif kind=='dataOutputAssociation':
   owner=parent[e].get('id');links.extend((i,owner,x.text) for x in e.findall(f'{{{B}}}targetRef'))
 return dict(nodes=nodes,edges=edges,lanes=lanes,boxes=boxes,paths=paths,scopes=dict(scopes),links=links,edge_names={i:els[i].get('name','') for i,_,_ in edges},sha256=hashlib.sha256(raw).hexdigest())
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

def compact(ps):
 out=[]
 for p in ps:
  if out and math.dist(out[-1],p)<1e-6:continue
  while len(out)>1:
   a,b=out[-2:];c=(b[0]-a[0])*(p[1]-b[1])-(b[1]-a[1])*(p[0]-b[0]);dot=(b[0]-a[0])*(p[0]-b[0])+(b[1]-a[1])*(p[1]-b[1])
   if abs(c)<1e-6 and dot>=0:out.pop()
   else:break
  out.append(p)
 return out

def small_loop_signature(model,body):
 """Exact directed isomorphism signature for <=6 nodes, preserving BPMN types
 and lane equivalence classes. Boundary arity is deliberately NOT discarded:
 it is carried separately on each candidate's boundary_ports.
 """
 body=set(body)
 if len(body)>6:return None
 edges=[(u,v) for _,u,v in model['edges'] if u in body and v in body];best=None
 for perm in itertools.permutations(sorted(body)):
  index={n:i for i,n in enumerate(perm)};roles={};laneclasses=[]
  for n in perm:
   lane=model['lanes'].get(n,'unassigned');roles.setdefault(lane,len(roles));laneclasses.append(roles[lane])
  code=(tuple(model['nodes'][n] for n in perm),tuple(laneclasses),tuple(sorted((index[u],index[v]) for u,v in edges)))
  if best is None or code<best:best=code
 return json.dumps(best)

def loop_geometry(model,loop):
 body=set(loop['nodes'])
 if not body<=set(model['boxes']):return None
 bb=[model['boxes'][n] for n in body];xmin=min(b[0] for b in bb);ymin=min(b[1] for b in bb);w=max(b[0]+b[2] for b in bb)-xmin;h=max(b[1]+b[3] for b in bb)-ymin;ids=[i for i,u,v in model['edges'] if u in body and v in body]
 if any(i not in model['paths'] for i in ids):return None
 length=sum(sum(math.dist(a,b) for a,b in zip(model['paths'][i],model['paths'][i][1:])) for i in ids);bends=sum(max(0,len(compact(model['paths'][i]))-2) for i in ids)
 return dict(bbox=[round(w,2),round(h,2)],internal_length=round(length,2),internal_bends=bends)

def branch_turns(model):
 inc=defaultdict(list);out=defaultdict(list);counts=Counter()
 for edge in model['edges']:inc[edge[2]].append(edge);out[edge[1]].append(edge)
 for g,flows in out.items():
  if model['nodes'][g]!='exclusiveGateway' or len(flows)<2 or len(inc[g])!=1:continue
  incoming=compact(model['paths'].get(inc[g][0][0],[]))
  if len(incoming)<2:continue
  a,b=incoming[-2:];v=(b[0]-a[0],b[1]-a[1])
  for i,_,_ in flows:
   ps=compact(model['paths'].get(i,[]))
   if len(ps)<2:continue
   a,b=ps[:2];w=(b[0]-a[0],b[1]-a[1]);cross=v[0]*w[1]-v[1]*w[0];dot=v[0]*w[0]+v[1]*w[1]
   relation='continuation' if abs(cross)<.01 and dot>0 else 'reverse' if abs(cross)<.01 and dot<0 else 'turn'
   name=model.get('edge_names',{}).get(i,'').strip().casefold();group='yes' if name in ('да','yes') else 'no' if name in ('нет','no') else 'other';counts[group+':'+relation]+=1
 return dict(counts)

def diagnostics(m):
 allmotifs={k:[] for k in ('task_decisions','natural_loops','split_joins','terminal_branches','role_handoffs','cyclic_components','not_reachable_from_entry','not_reaching_exit','cyclic_edge_ids')};node_scopes={n:s for s,ns in m['scopes'].items() for n in ns}
 for scope,ns in m['scopes'].items():
  es=[e for e in m['edges'] if e[1] in ns and e[2] in ns];result=recognize({n:m['nodes'][n] for n in ns},es,m['lanes'])
  for k,vs in result.items():allmotifs[k].extend(vs)
 boxes=m['boxes'];edgeid={(u,v):i for i,u,v in m['edges']};pair_geometry=[];portstats=Counter();lefts=[];classes=defaultdict(list)
 def center(n):
  x,y,w,h=boxes[n];return x+w/2,y+h/2
 def side(p,n):
  x,y,w,h=boxes[n];cx,cy=x+w/2,y+h/2;dx=(p[0]-cx)/w;dy=(p[1]-cy)/h
  return ('right' if dx>=0 else 'left') if abs(dx)>=abs(dy) else ('bottom' if dy>=0 else 'top')
 for p in allmotifs['task_decisions']:
  u,v=p['task'],p['gateway']
  if u not in boxes or v not in boxes:continue
  a,b=center(u),center(v);dx,dy=b[0]-a[0],b[1]-a[1];direction=('right' if dx>=0 else 'left') if abs(dx)>=abs(dy) else ('down' if dy>=0 else 'up');eid=edgeid[u,v];ps=compact(m['paths'].get(eid,[]));pair_geometry.append(dict(task=u,gateway=v,same_lane=p['same_lane'],direction=direction,bends=max(0,len(ps)-2),straight=len(ps)==2))
 for i,u,v in m['edges']:
  if i not in m['paths'] or u not in boxes or v not in boxes:continue
  ps=compact(m['paths'][i]);cross=u in m['lanes'] and v in m['lanes'] and m['lanes'][u]!=m['lanes'][v];kind='handoff' if cross else 'local';cls=kind+':'+('task' if m['nodes'][u] in TASK else 'gateway' if m['nodes'][u].endswith('Gateway') else 'event')+'->'+('task' if m['nodes'][v] in TASK else 'gateway' if m['nodes'][v].endswith('Gateway') else 'event');classes[cls].append(max(0,len(ps)-2));portstats[side(ps[0],u)+'->'+side(ps[-1],v)]+=1
  if center(v)[0]<center(u)[0]-10:lefts.append(dict(edge=i,within_cycle=i in allmotifs['cyclic_edge_ids']))
 docs=defaultdict(set)
 for _,u,v in m['links']:
  if u in m['nodes'] and v not in m['nodes']:docs[v].add(u)
  if v in m['nodes'] and u not in m['nodes']:docs[u].add(v)
 small_loops=[];seen=set()
 for loop in allmotifs['natural_loops']:
  body=frozenset(loop['nodes'])
  if len(body)<=6 and body not in seen:small_loops.append(dict(header=loop['header'],nodes=loop['nodes'],signature=small_loop_signature(m,body),geometry=loop_geometry(m,loop),boundary_ports=loop['boundary_ports']));seen.add(body)
 return dict(small_loops=small_loops,branch_turns=branch_turns(m),sha256=m['sha256'],nodes=len(m['nodes']),edges=len(m['edges']),counts={k:len(v) for k,v in allmotifs.items()},motifs=allmotifs,pair_geometry=pair_geometry,pair_orientations=dict(Counter(p['direction'] for p in pair_geometry if p['same_lane'])),leftward_edges=lefts,port_side_combinations=dict(portstats),edge_classes={k:dict(count=len(v),bends=sum(v),mean_bends=round(sum(v)/len(v),4),straight=sum(x==0 for x in v)) for k,v in classes.items()},multi_owner_documents={d:sorted(v) for d,v in docs.items() if len(v)>1})

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True);p.add_argument('--human',type=Path,required=True);p.add_argument('--automatic',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve()
 if out.is_relative_to(a.corpus.resolve()) or a.human.resolve().is_relative_to(out) or a.automatic.resolve().is_relative_to(out):raise ValueError('Output must be separate from inputs')
 out.mkdir(parents=True,exist_ok=True);refs=[diagnostics(parse(f)) for f in sorted(a.corpus.rglob('*.bpmn'))];res=dict(method='Graph-only motifs; natural loops require dominance; candidate regions are overlapping and not automatic contractions. Geometry is diagnostic only.',references=refs,human=diagnostics(parse(a.human)),automatic=diagnostics(parse(a.automatic)))
 (out/'graph_patterns.json').write_text(json.dumps(res,ensure_ascii=False,indent=2));print(json.dumps({'references':len(refs),'human':res['human']['counts'],'automatic':res['automatic']['counts']}))
if __name__=='__main__':main()
