"""Read-only, raw-XML measurements. Snapshot instructions are never executed."""
from pathlib import Path
from collections import Counter,defaultdict
from statistics import median
import xml.etree.ElementTree as E
import json,csv,math,hashlib
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dataset',type=Path,required=True,help='Extracted BPMN_Human_Layout_Dataset_v1 directory')
parser.add_argument('--corpus',type=Path,required=True,help='Directory of human BPMN references')
parser.add_argument('--automatic',type=Path,required=True,help='Automatic BPMN result to measure')
parser.add_argument('--output',type=Path,required=True,help='Separate output directory, never the input tree')
args=parser.parse_args(); DATA=args.dataset.resolve(); OUT=args.output.resolve()
if OUT==DATA or OUT.is_relative_to(DATA) or OUT==args.corpus.resolve() or OUT.is_relative_to(args.corpus.resolve()) or args.automatic.resolve().is_relative_to(OUT):raise ValueError('Output must be separate from input trees')
OUT.mkdir(parents=True,exist_ok=True)
B='http://www.omg.org/spec/BPMN/20100524/MODEL';BD='http://www.omg.org/spec/BPMN/20100524/DI';DC='http://www.omg.org/spec/DD/20100524/DC';DI='http://www.omg.org/spec/DD/20100524/DI'
TASK={'task','userTask','serviceTask','manualTask','sendTask','receiveTask','scriptTask','businessRuleTask','callActivity','subProcess','transaction'}
def local(e):return e.tag.rsplit('}',1)[-1]
def load(p):
 raw=p.read_bytes()
 if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:raise ValueError('unsafe XML')
 r=E.fromstring(raw);els={e.get('id'):e for e in r.iter() if e.get('id')};boxes={};paths={};labels={};lanes={}
 for e in r.iter():
  if e.tag==f'{{{BD}}}BPMNShape':
   b=e.find(f'{{{DC}}}Bounds')
   if b is not None:boxes[e.get('bpmnElement')]=tuple(float(b.get(k)) for k in ('x','y','width','height'))
  if e.tag==f'{{{BD}}}BPMNEdge':paths[e.get('bpmnElement')]=[(float(w.get('x')),float(w.get('y'))) for w in e.findall(f'{{{DI}}}waypoint')]
  if e.tag==f'{{{BD}}}BPMNLabel':
   pass
  if e.tag==f'{{{B}}}lane':
   for n in e.findall(f'{{{B}}}flowNodeRef'):lanes[n.text]=e.get('id')
 for e in r.iter():
  if local(e) in ('BPMNShape','BPMNEdge'):
   b=e.find(f'{{{BD}}}BPMNLabel/{{{DC}}}Bounds')
   if b is not None:labels[e.get('bpmnElement')]=tuple(float(b.get(k)) for k in ('x','y','width','height'))
 return dict(path=str(p),root=r,els=els,boxes=boxes,paths=paths,labels=labels,lanes=lanes,sha256=hashlib.sha256(raw).hexdigest())
def center(b):return (b[0]+b[2]/2,b[1]+b[3]/2)
def ptsclean(ps):
 out=[]
 for p in ps:
  if out and math.dist(out[-1],p)<1e-6:continue
  while len(out)>1:
   a,b=out[-2:];cross=(b[0]-a[0])*(p[1]-b[1])-(b[1]-a[1])*(p[0]-b[0]);dot=(b[0]-a[0])*(p[0]-b[0])+(b[1]-a[1])*(p[1]-b[1])
   if abs(cross)<1e-6 and dot>=0:out.pop()
   else:break
  out.append(p)
 return out

def metrics(d):
 es=d['els'];bs=d['boxes'];ps=d['paths'];ls=d['lanes'];flows={i:e for i,e in es.items() if local(e)=='sequenceFlow'}
 tasks=[b for i,b in bs.items() if i in es and local(es[i]) in TASK];taskids={i for i in bs if i in es and local(es[i]) in TASK}
 stats=Counter();benddist=Counter();left=[];direct=[];align=[];lengths=[];detours=[];details=[]
 for i,e in flows.items():
  if i not in ps:continue
  p=ptsclean(ps[i]);length=sum(math.dist(a,b) for a,b in zip(p,p[1:]));bends=max(0,len(p)-2);lengths.append(length);benddist[bends]+=1
  if len(p)==2:stats['straight']+=1;direct.append(i)
  if any(abs(a[0]-b[0])>1e-5 and abs(a[1]-b[1])>1e-5 for a,b in zip(p,p[1:])):stats['diagonal_flows']+=1
  u,v=e.get('sourceRef'),e.get('targetRef')
  if u not in bs or v not in bs:continue
  a,b=center(bs[u]),center(bs[v]);crosslane=ls.get(u)!=ls.get(v) and u in ls and v in ls
  if crosslane:
   stats['cross_lane']+=1
   if abs(a[0]-b[0])<=10:stats['cross_lane_x_aligned_10']+=1;align.append(i)
  else:
   stats['same_lane']+=1
   if b[0]<a[0]-10:stats['same_lane_leftwards']+=1;left.append(i)
   if abs(a[1]-b[1])<=5:stats['same_lane_y_aligned_5']+=1
  dist=abs(p[-1][0]-p[0][0])+abs(p[-1][1]-p[0][1]);detours.append(length/max(1,dist))
  details.append(dict(id=i,source=u,target=v,source_name=es[u].get('name',''),target_name=es[v].get('name',''),cross_lane=crosslane,length=round(length,2),bends=bends,straight=len(p)==2,dx=round(b[0]-a[0],2),dy=round(b[1]-a[1],2)))
 docs={i for i,e in es.items() if local(e) in ('dataObjectReference','dataStoreReference')};docstats=Counter();assoc_lengths=[]
 for i,p in ps.items():
  if i not in es or local(es[i]) not in ('association','dataInputAssociation','dataOutputAssociation'):continue
  pp=ptsclean(p);docstats['count']+=1;docstats['straight']+=int(len(pp)==2);docstats['diagonal']+=int(any(abs(a[0]-b[0])>1e-5 and abs(a[1]-b[1])>1e-5 for a,b in zip(pp,pp[1:])));assoc_lengths.append(sum(math.dist(a,b) for a,b in zip(pp,pp[1:])))
 noncontainer={i:b for i,b in bs.items() if i in es and local(es[i]) not in ('lane','participant')};sumarea=sum(b[2]*b[3] for b in noncontainer.values());xs=[b[0] for b in noncontainer.values()];ys=[b[1] for b in noncontainer.values()];w=max(b[0]+b[2] for b in noncontainer.values())-min(xs);h=max(b[1]+b[3] for b in noncontainer.values())-min(ys)
 return dict(file=Path(d['path']).name,sha256=d['sha256'],sequence_count=len(flows),task_count=len(tasks),task_width_median=median(b[2] for b in tasks) if tasks else None,task_height_median=median(b[3] for b in tasks) if tasks else None,unique_task_sizes=len(set((b[2],b[3]) for b in tasks)),flow_stats=dict(stats),bend_distribution=dict(sorted(benddist.items())),sequence_bends=sum(k*v for k,v in benddist.items()),sequence_length_euclidean=round(sum(lengths),2),median_flow_length=median(lengths) if lengths else None,median_detour_ratio=round(median(detours),3) if detours else None,straight_flow_ids=direct,leftward_flow_ids=left,aligned_cross_lane_ids=align,association_stats=dict(docstats),median_association_length_euclidean=round(median(assoc_lengths),2) if assoc_lengths else None,node_bbox=[w,h],node_area_factor=round(w*h/sumarea,4),flows=details)
def canonical(e):
 return (e.tag,tuple(sorted(e.attrib.items())),(e.text or '').strip(),tuple(canonical(c) for c in e))
def control(d):
 return dict(nodes={i:(local(e),tuple(sorted(e.attrib.items())),tuple(canonical(c) for c in e if local(c) not in ('incoming','outgoing','property','dataInputAssociation','dataOutputAssociation','ioSpecification'))) for i,e in d['els'].items() if local(e) in TASK or local(e).endswith('Gateway') or local(e).endswith('Event')},flows={i:canonical(e) for i,e in d['els'].items() if local(e)=='sequenceFlow'},members=d['lanes'])
def readcsv(n):return list(csv.DictReader((DATA/n).open(encoding='utf-8-sig')))
snaps=sorted((DATA/'source_session/20261101_113547_02_final_v20/snapshots').glob('*.bpmn'));ds=[load(p) for p in snaps];ms=[metrics(d) for d in ds]
base=control(ds[0]);trans=[];actions=readcsv('data/action_events.csv');trows=readcsv('data/transition_metrics.csv')
for i,(a,b) in enumerate(zip(ds,ds[1:]),1):
 co,cn=control(a),control(b);moves=[]
 for k in sorted(a['boxes'].keys()&b['boxes'].keys()):
  if a['boxes'][k]!=b['boxes'][k] and local(b['els'][k]) not in ('participant','lane'):
   aa,bb=a['boxes'][k],b['boxes'][k];moves.append((k,tuple(round(y-x,4) for x,y in zip(aa,bb))))
 common=Counter(v[:2] for _,v in moves).most_common(1);shift=common[0][0] if common else (0,0);nshift=common[0][1] if common else 0
 raw_roles={k:[co['members'].get(k),cn['members'].get(k)] for k in sorted(co['members'].keys()|cn['members'].keys()) if co['members'].get(k)!=cn['members'].get(k)}
 changes=[k for k in sorted(co['nodes'].keys()|cn['nodes'].keys()) if co['nodes'].get(k)!=cn['nodes'].get(k)];flowchanges=[k for k in sorted(co['flows'].keys()|cn['flows'].keys()) if co['flows'].get(k)!=cn['flows'].get(k)]
 trans.append(dict(save=i,declared_has_semantic_changes=trows[i-1]['has_semantic_changes'],node_changes=changes,flow_changes=flowchanges,lane_membership_changes=raw_roles,noncontainer_moves=len(moves),dominant_translation=list(shift),moves_with_dominant_translation=nshift,remaining_moves_after_dominant_translation=len([1 for _,v in moves if v[:2]!=shift]),sequence_length_delta=round(ms[i]['sequence_length_euclidean']-ms[i-1]['sequence_length_euclidean'],2),sequence_bends_delta=ms[i]['sequence_bends']-ms[i-1]['sequence_bends'],action_types=dict(Counter(r['action_type'] for r in actions if int(r['sequence'])==i))))
corpus=args.corpus;refs=[metrics(load(p)) for p in sorted(corpus.rglob('*.bpmn'))];auto=metrics(load(args.automatic))
res=dict(method={'length':'Euclidean sum of saved DI segments; all sequenceFlow segments orthogonal in final. Dataset Manhattan data-link lengths kept separate.','bends':'Actual direction changes after duplicate/collinear removal.','alignment':'centres within 10 units for cross-lane X, 5 for same-lane Y; thresholds are analysis settings.','scope':'Snapshots are correlated states of ONE process, not 18 independent samples. Action records are differences per save, not pointer gestures.'},snapshots=ms,transitions=trans,controlflow_invariant_all_saves=all(control(d)['nodes']==base['nodes'] and control(d)['flows']==base['flows'] for d in ds),final_roles_equal_baseline=control(ds[-1])['members']==base['members'],actions=dict(Counter(r['action_type'] for r in actions)),corpus_count=len(refs),corpus=refs,current_automatic=auto)
(OUT/'independent_measurements.json').write_text(json.dumps(res,ensure_ascii=False,indent=2))
print(json.dumps({'snapshots':len(ms),'references':len(refs),'controlflow_invariant':res['controlflow_invariant_all_saves'],'final_roles_restored':res['final_roles_equal_baseline'],'measurements':str(OUT/'independent_measurements.json')},ensure_ascii=False))
