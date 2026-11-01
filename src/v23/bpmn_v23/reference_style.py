"""Measured reference style; aggregate geometry, not process logic or copied IDs."""
from pathlib import Path
from collections import Counter
import hashlib,json,statistics,zipfile,math
from lxml import etree as ET
from bpmn_universal.contract import B,BD,DC,NS,Q
from bpmn_refkit.model import TAG_TASK,TAG_GATE,TAG_EVENT
PROFILE=Path(__file__).parent/'assets/human_style_profile.json'


def percentile(values,p):
    values=sorted(values);return values[round((len(values)-1)*p)] if values else None


def measure_zip(path):
    widths=[];heights=[];gaps=[];aspects=[];factors=[];sizes=Counter();models=0;paired=0;vertical=0;horizontal=0
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            if not item.filename.lower().endswith('.bpmn'):continue
            if item.file_size>25_000_000:raise ValueError('Reference exceeds 25 MB')
            raw=archive.read(item)
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('Reference XML entities are not allowed')
            root=ET.fromstring(raw,ET.XMLParser(resolve_entities=False,no_network=True));models+=1
            nodes={e.get('id'):ET.QName(e).localname for e in root.iter() if e.get('id') and ET.QName(e).namespace==B and ET.QName(e).localname in TAG_TASK|TAG_GATE|TAG_EVENT|{'dataObjectReference','dataStoreReference'}}
            boxes={}
            for shape in root.xpath('.//bd:BPMNShape',namespaces=NS):
                bound=shape.find(Q(DC,'Bounds'));n=shape.get('bpmnElement')
                if bound is not None and n in nodes:boxes[n]=tuple(float(bound.get(k)) for k in ('x','y','width','height'))
            for n,(x,y,w,h) in boxes.items():
                if nodes[n] in TAG_TASK:widths.append(w);heights.append(h);sizes[(w,h)]+=1
            for flow in root.xpath('.//b:sequenceFlow',namespaces=NS):
                u,v=flow.get('sourceRef'),flow.get('targetRef')
                if u not in boxes or v not in boxes:continue
                a=boxes[u];b=boxes[v];dx=b[0]+b[2]/2-a[0]-a[2]/2;dy=b[1]+b[3]/2-a[1]-a[3]/2
                if nodes[u] in TAG_TASK and nodes[v] in TAG_GATE:paired+=1
                if abs(dy)<5 and dx>0:
                    horizontal+=1
                    if b[0]>=a[0]+a[2]:gaps.append(b[0]-a[0]-a[2])
                if abs(dx)<5 and dy>0:vertical+=1
            if boxes:
                w=max(x+ww for x,y,ww,hh in boxes.values())-min(x for x,y,ww,hh in boxes.values())
                h=max(y+hh for x,y,ww,hh in boxes.values())-min(y for x,y,ww,hh in boxes.values())
                aspects.append(w/h);factors.append(w*h/sum(b[2]*b[3] for b in boxes.values()))
    if not widths:raise ValueError('No measurable tasks in reference archive')
    return {'method':'aggregate reference geometry + explicit graph motifs; no neural training','reference_archive_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'models_measured':models,'tasks_measured':len(widths),'task_width_median':statistics.median(widths),'task_width_p75':percentile(widths,.75),'task_height_median':statistics.median(heights),
            'aligned_gap_median':statistics.median(gaps) if gaps else 40,'area_factor_median':statistics.median(factors),'area_factor_p90':percentile(factors,.9),'aspect_ratio_median':statistics.median(aspects),
            'aspect_ratio_p10':percentile(aspects,.1),'aspect_ratio_p90':percentile(aspects,.9),'task_to_decision_pairs':paired,'straight_horizontal_links':horizontal,'straight_vertical_links':vertical,
            'common_task_sizes':[{'width':w,'height':h,'count':count} for (w,h),count in sizes.most_common(10)],'task_font_px':13,'font_policy':'chosen for full text; source font sizes are not inferred'}


def profile():return json.loads(PROFILE.read_text())


def style_cost(boxes,nodes,docs):
    shapes=[b for n,b in boxes.items() if n in nodes or n in docs]
    width=max(b[0]+b[2] for b in shapes)-min(b[0] for b in shapes)
    height=max(b[1]+b[3] for b in shapes)-min(b[1] for b in shapes)
    factor=width*height/sum(b[2]*b[3] for b in shapes);p=profile()
    excess=max(0,factor/p['area_factor_p90']-1)
    return {'area_factor':round(factor,4),'reference_p90':round(p['area_factor_p90'],4),'within_reference_density':excess<=.15,'penalty':excess*12000}
