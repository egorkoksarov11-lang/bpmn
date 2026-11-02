"""Measure direct successors in human DI without editing or extracting inputs."""
from pathlib import Path
from statistics import median
from lxml import etree as ET
import argparse,json,sys,zipfile,hashlib
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src/v23'),str(Path(__file__).resolve().parents[1]/'src/v22')]
from bpmn_v23.continuity import neighbourhood,local_metrics
from bpmn_refkit.model import TAG_TASK,TAG_GATE,TAG_EVENT


def measure(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('XML entities not supported')
    root=ET.fromstring(raw,ET.XMLParser(resolve_entities=False,no_network=True));boxes={};paths={};nodes={};seq=[]
    for e in root.iter():
        kind=ET.QName(e).localname
        if kind in TAG_TASK|TAG_GATE|TAG_EVENT:nodes[e.get('id')]={'kind':kind}
        if kind=='sequenceFlow':seq.append((e.get('id'),e.get('sourceRef'),e.get('targetRef'),''))
        if kind=='BPMNShape':
            b=e.find('{http://www.omg.org/spec/DD/20100524/DC}Bounds')
            if b is not None:boxes[e.get('bpmnElement')]=tuple(float(b.get(k)) for k in ('x','y','width','height'))
        if kind=='BPMNEdge':paths[e.get('bpmnElement')]=[(float(w.get('x')),float(w.get('y'))) for w in e if ET.QName(w).localname=='waypoint']
    near=neighbourhood(nodes,seq,boxes);groups={}
    def family(n):
        kind=nodes[n]['kind'];return 'task' if kind in TAG_TASK else 'gateway' if kind in TAG_GATE else 'event'
    for i,u,v,_ in seq:
        if i in near:groups.setdefault(family(u)+'->'+family(v),[]).append(i)
    return {**local_metrics(paths,near),'by_node_kinds':{k:local_metrics(paths,ids) for k,ids in groups.items()}}


def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.resolve() in {a.archive.resolve(),a.baseline.resolve(),a.candidate.resolve()}:p.error('Separate output required')
    rows=[]
    with zipfile.ZipFile(a.archive) as z:
        for i in z.infolist():
            if not i.filename.lower().endswith('.bpmn'):continue
            if i.file_size>25_000_000:raise ValueError('Oversized reference')
            raw=z.read(i);rows.append({'file':i.filename,'sha256':hashlib.sha256(raw).hexdigest(),**measure(raw)})
    totals={k:sum(r[k] for r in rows) for k in ('frozen_neighbour_count','straight','one_bend','two_plus_bends','bends')}
    totals['straight_fraction']=totals['straight']/max(1,totals['frozen_neighbour_count'])
    kinds={}
    for row in rows:
        for kind,m in row['by_node_kinds'].items():
            target=kinds.setdefault(kind,{k:0 for k in ('frozen_neighbour_count','straight','one_bend','two_plus_bends')})
            for k in target:target[k]+=m[k]
    result={'definition':'direct sequenceFlow; bounding-box Manhattan gap <= 0.8 median task width; separate from 7-family conformity','reference_count':len(rows),'reference_totals':totals,'reference_totals_by_node_kinds':kinds,'reference_median_straight_fraction':median(r['straight_fraction'] for r in rows),'references':rows,'baseline':measure(a.baseline.read_bytes()),'candidate_dynamic_neighbourhood':measure(a.candidate.read_bytes()),'note':'Candidate selection freezes incumbent neighbour IDs; moving a bad link out of scope cannot improve its selection score. This external dynamic measurement is diagnostic only; task-to-gateway links influence the aggregate.'}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='references'},ensure_ascii=False))


if __name__=='__main__':main()
