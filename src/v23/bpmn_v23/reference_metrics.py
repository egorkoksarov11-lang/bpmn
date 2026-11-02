"""Reference-conformity diagnostics. Not a probability of human approval.

Scores are one-sided (a cleaner route is never punished) except aspect ratio.
Mandatory geometry/text gates prevent pathological overpacking.
Calibration must be frozen before candidate selection; no benchmark IDs enter it.
"""
from statistics import median
import math
from bpmn_refkit.model import TAG_TASK,TAG_GATE,TAG_EVENT
from lxml import etree as ET
from .quality import contacts
from .readability import metrics as reading_metrics
from .reference_style import percentile

FAMILIES={
 'routes':{'bends_per_flow':'low','straight_fraction':'high','p90_bends':'low'},
 'distance':{'mean_length_widths':'low','p90_length_widths':'low','forward_hop_excess':'low'},
 'crossings':{'contacts_per_flow':'low'},
 'crowding':{'parallel_crowding_per_flow':'low','hotspot_excess':'low'},
 'packing':{'area_factor':'low','aspect_ratio':'range'},
 'alignment':{'axis_aligned_fraction':'high'},
 'documents':{'document_distance_widths':'low','document_bends':'low'},
}

def clean(ps):
 out=[]
 for p in ps:
  if out and math.dist(out[-1],p)<1e-6:continue
  while len(out)>1:
   a,b=out[-2:];cross=(b[0]-a[0])*(p[1]-b[1])-(b[1]-a[1])*(p[0]-b[0]);dot=(b[0]-a[0])*(p[0]-b[0])+(b[1]-a[1])*(p[1]-b[1])
   if abs(cross)<1e-5 and dot>=0:out.pop()
   else:break
  out.append(p)
 return out


def features(path):
 raw=open(path,'rb').read()
 if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('XML entities not supported')
 root=ET.fromstring(raw,ET.XMLParser(resolve_entities=False,no_network=True));nodes={};docs={};seq=[];boxes={};paths={};lanes=set()
 for e in root.iter():
  kind=ET.QName(e).localname;n=e.get('id')
  if kind in TAG_TASK|TAG_GATE|TAG_EVENT and n:nodes[n]={'kind':kind,'name':e.get('name','')}
  if kind in ('dataObjectReference','dataStoreReference') and n:docs[n]={}
  if kind=='lane':lanes.add(n)
  if kind=='sequenceFlow':seq.append((n,e.get('sourceRef'),e.get('targetRef'),e.get('name','')))
  if kind=='BPMNShape':
   b=e.find('{http://www.omg.org/spec/DD/20100524/DC}Bounds')
   if b is not None:boxes[e.get('bpmnElement')]=tuple(float(b.get(k)) for k in ('x','y','width','height'))
  if kind=='BPMNEdge':paths[e.get('bpmnElement')]=[(float(w.get('x')),float(w.get('y'))) for w in e if ET.QName(w).localname=='waypoint']
 seqids={i for i,_,_,_ in seq}
 associds={e.get('id') for e in root.iter() if ET.QName(e).localname in ('association','dataInputAssociation','dataOutputAssociation')}
 assocs=[(i,None,None,None) for i in paths if i in associds]
 if any(n not in boxes for n in nodes|docs) or any(i not in paths for i in seqids):raise ValueError('Missing DI geometry')
 task=[boxes[n] for n,o in nodes.items() if o['kind'] in TAG_TASK];tw=median(b[2] for b in task) if task else 160
 lengths=[];bends=[];aligned=0
 for i,u,v,_ in seq:
  ps=clean(paths[i]);lengths.append(sum(math.dist(a,b) for a,b in zip(ps,ps[1:]))/tw);bends.append(max(0,len(ps)-2));a,b=boxes[u],boxes[v]
  # Compatible axes need overlapping side intervals, not equal centres.
  aligned+=int(max(a[0],b[0])<=min(a[0]+a[2],b[0]+b[2]) or max(a[1],b[1])<=min(a[1]+a[3],b[1]+b[3]))
 flowpaths={i:paths[i] for i,_,_,_ in seq};uv={i:(u,v) for i,u,v,_ in seq};rd=reading_metrics(boxes,flowpaths,nodes,seq)
 shapes=[boxes[n] for n in nodes|docs];w=max(b[0]+b[2] for b in shapes)-min(b[0] for b in shapes);h=max(b[1]+b[3] for b in shapes)-min(b[1] for b in shapes)
 dl=[sum(math.dist(a,b) for a,b in zip(paths[i],paths[i][1:]))/tw for i,_,_,_ in assocs];db=[max(0,len(clean(paths[i]))-2) for i,_,_,_ in assocs]
 n=max(1,len(seq));result={'flow_count':len(seq),'node_count':len(nodes),'lane_count':len(lanes),'return_fraction':rd['graph_return_count']/n,'document_count':len(docs),'bends_per_flow':sum(bends)/n,'straight_fraction':sum(b==0 for b in bends)/n,'p90_bends':percentile(bends,.9) or 0,'mean_length_widths':sum(lengths)/n,'p90_length_widths':percentile(lengths,.9) or 0,'contacts_per_flow':len(contacts(flowpaths,uv))/n,'area_factor':w*h/sum(b[2]*b[3] for b in shapes),'aspect_ratio':w/h,'axis_aligned_fraction':aligned/n,'document_distance_widths':sum(dl)/max(1,len(dl)),'document_bends':sum(db)/max(1,len(db))}
 result.update({k:rd[k] for k in ['forward_hop_excess','parallel_crowding_per_flow','hotspot_excess']});return result


def calibrate(rows):
 if len(rows)<5:raise ValueError('At least five reference models required')
 bands={}
 for family,cols in FAMILIES.items():
  for col,direction in cols.items():
   values=[r[col] for r in rows if not (family=='documents' and not r['document_count'])]
   if not values:continue
   q10,q25,q50,q75,q90=[percentile(values,p) for p in [.1,.25,.5,.75,.9]]
   bands[col]={'direction':direction,'p10':q10,'median':q50,'p90':q90,'scale':max(q75-q25,abs(q50)*.25,.05)}
 return {'complexity_ranges':{k:[min(r[k] for r in rows),max(r[k] for r in rows)] for k in ['flow_count','node_count','lane_count','return_fraction']},'version':'reference-conformity-v1','reference_count':len(rows),'bands':bands,'target':80,'interpretation':'diagnostic conformity, NOT 80% human-rated visual similarity'}


def evaluate(row,profile,hard_checks=None):
 fs={};details={}
 for family,cols in FAMILIES.items():
  if family=='documents' and not row['document_count']:continue
  scores=[]
  for col,direction in cols.items():
   if col not in profile['bands']:continue
   b=profile['bands'][col];x=row[col]
   excess=max(0,x-b['p90']) if direction=='low' else max(0,b['p10']-x) if direction=='high' else max(0,b['p10']-x,x-b['p90'])
   score=math.exp(-excess/(2*b['scale']));scores.append(score);details[col]={'value':x,'score':round(100*score,2),'reference_p10':b['p10'],'reference_p90':b['p90']}
  if scores:fs[family]=100*math.prod(scores)**(1/len(scores))
 overall=100*math.prod(v/100 for v in fs.values())**(1/len(fs))
 required=('semantic_freeze','DI_freeze','routing_safety','clearance','text_and_labels','no_pathological_bends')
 passed=hard_checks is not None and all(hard_checks.get(k) is True for k in required)
 outside={k:row[k] for k,(lo,hi) in profile.get('complexity_ranges',{}).items() if not lo<=row[k]<=hi}
 return {'outside_reference_complexity':outside,'conformity_percent':round(overall,2),'family_scores':{k:round(v,2) for k,v in fs.items()},'metrics':details,'hard_checks':hard_checks,'target_reached':passed and overall>=80 and min(fs.values())>=60,'visual_similarity_verified':False,'scope':'7 statistical families plus mandatory semantics/text/geometry gates; visual 80% needs user validation'}
