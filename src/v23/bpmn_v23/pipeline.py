"""Strict, staged backend API with independent post-save audits.

Default backend searches compact reference-style layouts and decision orientations.
The original v22 adapter is retained for comparison. This is not an A4 solver.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, tempfile
from pathlib import Path
from typing import Protocol
from lxml import etree as ET
from bpmn_universal.cli import optimize
from bpmn_universal.contract import normalized_model, preflight, semantic_equality, parse, NS, Q, B, BD, DC, DI
from bpmn_universal.settings import Settings
from bpmn_refkit.model import read_bpmn, TAG_TASK
from bpmn_refkit.geometry import geometry_audit
from .labels import place_labels
from . import __version__
from .router import OrthogonalBackend
from .search import SearchBackend
from .human_search import HumanStyleBackend
from .contours import on_contour
from .quality import contacts
from .readability import metrics as reading_metrics
from .typography import fits,wrap,task_fits,TASK_FONT
from .freeze import equal as di_structure_equal,digest as di_structure_digest
from .reference_style import style_cost
from bpmn_refkit.geometry import bbox_intersect_seg


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


class LayoutBackend(Protocol):
    name: str
    def layout(self, source: Path, output: Path, svg: Path) -> dict: ...


class V22Backend:
    name = 'v22-orthogonal'
    def layout(self, source, output, svg):
        settings = Settings()
        settings.execution.timeout_seconds = 120
        settings.semantics.mode = 'strict'
        settings.semantics.approved_association_removals = []
        return optimize(source, output, settings, svg=svg)


def geometry(path):
    _, root, _, _, nodes, seq, assocs, docs, membership, _, boxes, paths = read_bpmn(path)
    result = geometry_audit(boxes, paths, seq, assocs, nodes, docs)
    diagonal=[]; excessive=[]; endpoints=[]; outside=[]; nonfinite=[]
    def border(p, b):
        x,y,w,h=b; px,py=p
        return ((abs(px-x)<1 or abs(px-x-w)<1) and y-1<=py<=y+h+1 or
                (abs(py-y)<1 or abs(py-y-h)<1) and x-1<=px<=x+w+1)
    for eid,u,v,_ in seq+assocs:
        points=paths[eid]
        if any(not math.isfinite(z) for pt in points for z in pt): nonfinite.append(eid)
        if not on_contour(points[0],boxes[u],nodes.get(u,{}).get('kind','')) or not on_contour(points[-1],boxes[v],nodes.get(v,{}).get('kind','')):endpoints.append(eid)
        if len(points)-2>8:excessive.append(eid)
        for a,b in zip(points,points[1:]):
            if abs(a[0]-b[0])>0.01 and abs(a[1]-b[1])>0.01:diagonal.append(eid)
    for nid,lane in membership.items():
        if lane not in boxes or nid not in boxes:outside.append(nid);continue
        x,y,w,h=boxes[nid];lx,ly,lw,lh=boxes[lane]
        if x<lx or y<ly or x+w>lx+lw or y+h>ly+lh:outside.append(nid)
    sizes=sorted({(b[2],b[3]) for n,b in boxes.items() if n in nodes and nodes[n]['kind'] in TAG_TASK})
    rects=list(boxes.values())
    rects += [tuple(float(e.get(k)) for k in ('x','y','width','height')) for e in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS)]
    points=[p for ps in paths.values() for p in ps]
    minx=min([b[0] for b in rects]+[p[0] for p in points]);miny=min([b[1] for b in rects]+[p[1] for p in points])
    width=max([b[0]+b[2] for b in rects]+[p[0] for p in points])-minx
    height=max([b[1]+b[3] for b in rects]+[p[1] for p in points])-miny
    ratio=width/height
    a4_scale=min(277/width,190/height)
    min_print_font_pt=12*a4_scale/0.3527777778
    labels=[]
    for e in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
        owner=e.getparent().getparent().get('bpmnElement');b=tuple(float(e.get(k)) for k in ('x','y','width','height'))
        labels.append((owner,b))
    def overlaps(a,b):return min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0])>0.01 and min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1])>0.01
    label_collisions=[]
    for i,(a,ab) in enumerate(labels):
        for b,bb in labels[i+1:]:
            if overlaps(ab,bb):label_collisions.append([a,b])
        for b,bb in boxes.items():
            if b in nodes or b in docs:
                if a!=b and overlaps(ab,bb):label_collisions.append([a,b])
    uv={i:(u,v) for i,u,v,_ in seq+assocs}
    robust_contacts=contacts(paths,uv)
    overflow=[n for n,o in nodes.items() if o['kind'] in TAG_TASK and not task_fits(o.get('name',''),boxes[n],o['kind'])]
    label_line_cuts=[]
    for owner,rect in labels:
        for eid,points in paths.items():
            if any(bbox_intersect_seg(rect,a,b,clearance=1) for a,b in zip(points,points[1:])):label_line_cuts.append([owner,eid])
    result['readability']=reading_metrics(boxes,paths,nodes,seq)
    result.update(ambiguous_contacts=len(robust_contacts),contact_examples=robust_contacts[:40],task_text_overflows=overflow,label_line_cuts=label_line_cuts)
    clearance_violations=set();header_cuts=set()
    for eid,u,v,_ in seq+assocs:
        ps=paths[eid]
        for index,(a,b) in enumerate(zip(ps,ps[1:])):
            for n,box in boxes.items():
                if n not in nodes and n not in docs:continue
                if n==u and index==0 or n==v and index==len(ps)-2:continue
                if bbox_intersect_seg(box,a,b,clearance=-7.9):clearance_violations.add((eid,n))
            for lane in set(membership.values()):
                if lane in boxes:
                    x,y,w,h=boxes[lane]
                    if bbox_intersect_seg((x,y,48,h),a,b,clearance=0):header_cuts.add((eid,lane))
    result.update(edge_object_clearance_violations=sorted(clearance_violations),lane_header_cuts=sorted(header_cuts),edge_clearance_passed=not clearance_violations and not header_cuts,reference_style=style_cost(boxes,nodes,docs))
    result.update(diagonal_segments=len(diagonal),diagonal_edges=sorted(set(diagonal)), excessive_bend_edges=excessive,
        invalid_endpoints=endpoints,nonfinite_waypoints=nonfinite,outside_lanes=outside,task_sizes=sizes,
        task_sizes_uniform=len(sizes)<=1,label_collision_pairs=label_collisions,
        extent={'width':width,'height':height,'aspect_ratio':ratio},
        a4_ratio_passed=1.35<=ratio<=1.65,estimated_A4_min_font_pt=round(min_print_font_pt,2),a4_legible_at_8pt=min_print_font_pt>=8,text_overflow_check='measured_bundled_OpenSans_13px',
        crossing_avoidability='not_proven')
    result['routing_safety_passed']=not (result['shape_overlaps'] or result['line_through_shapes'] or result['crossings'].get('overlapping_segments',0) or diagonal or endpoints or outside or nonfinite)
    result['release_geometry_passed']=result['routing_safety_passed'] and result['edge_clearance_passed'] and result['a4_ratio_passed'] and min_print_font_pt>=8 and not label_collisions and not excessive and len(sizes)<=1 and not robust_contacts and not overflow and not label_line_cuts
    return result


def validate_xml(path):
    root=parse(path)
    ids={e.get('id') for e in root.iter() if e.get('id')}
    dangling=[]
    for e in root.iter():
        for attr in ('sourceRef','targetRef','bpmnElement','dataObjectRef','dataStoreRef','attachedToRef','processRef'):
            if e.get(attr) and e.get(attr) not in ids:dangling.append([e.get('id'),attr,e.get(attr)])
        if e.tag in {Q(B,'sourceRef'),Q(B,'targetRef'),Q(B,'flowNodeRef')} and (e.text or '').strip() not in ids:
            dangling.append([e.getparent().get('id'),ET.QName(e).localname,e.text])
    scan=preflight(path)
    if dangling or not scan['compatible']:raise ValueError({'dangling':dangling,'preflight':scan})
    return {'xml_parse':True,'reference_integrity':True,'preflight':scan}


def run(source, destination, backend=None):
    source=Path(source).resolve();destination=Path(destination).resolve()
    backend=backend or HumanStyleBackend()
    if destination==source.parent or source.is_relative_to(destination):
        raise ValueError('Destination must be separate from input directory')
    validate_xml(source)
    destination.mkdir(parents=True,exist_ok=True)
    source_bytes=source.read_bytes()
    with tempfile.TemporaryDirectory(prefix='v23-stage-',dir=destination.parent) as td:
        stage=Path(td);bpmn=stage/'process_08_v23.bpmn';svg=stage/'process_08_v23.svg'
        before=geometry(source)
        report=backend.layout(source,bpmn,svg)
        label_report=place_labels(bpmn,svg)
        validation=validate_xml(bpmn)
        if not semantic_equality(source,bpmn):raise ValueError('Semantic freeze violation')
        if not di_structure_equal(source,bpmn):raise ValueError('DI structure freeze violation')
        after=geometry(bpmn)
        if not after['routing_safety_passed']:raise ValueError({'routing_safety_rejected':after})
        if label_report['unplaced_labels']:raise ValueError({'unplaced_labels':label_report['unplaced_labels']})
        if after['label_collision_pairs'] or after['label_line_cuts'] or after['task_text_overflows'] or label_report['rendering']['text_overflow_ids']:
            raise ValueError({'readability_rejected':after,'rendering':label_report['rendering']})
        if source.read_bytes()!=source_bytes:raise ValueError('Input changed during layout')
        semantic={'equal':True,'diff_count':0,'whitelist':[], 'comparison':'canonical complete XML excluding BPMNDiagram',
                  'source_file':source.name,
                  'source_sha256':hashlib.sha256(source_bytes).hexdigest(),
                  'before_semantic_sha256':hashlib.sha256(normalized_model(source)).hexdigest(),
                  'after_semantic_sha256':hashlib.sha256(normalized_model(bpmn)).hexdigest(),
                  'di_structure_preserved':True,'di_structure_sha256':di_structure_digest(bpmn)}
        save_json(stage/'semantic_diff.json',semantic)
        save_json(stage/'geometry_report.json',{'before':before,'after':after})
        report['output']=str(destination/'process_08_v23.bpmn')
        report['artifacts']={'bpmn':str(destination/'process_08_v23.bpmn'),'svg':str(destination/'process_08_v23.svg'),'png':None}
        save_json(stage/'run_report.json',{'version':__version__,'backend':backend.name,
            'status':'layout_candidate_verified','release_ready':False,
            'limitations':['global optimality is not proven','see geometry_report.json for remaining readability limitations'], 'source_file':source.name,
            'validation':validation,'label_placement':label_report,'backend_report':report})
        (stage/'source_semantic_snapshot.xml').write_bytes(normalized_model(source))
        ET.parse(str(svg))
        for p in stage.iterdir():os.replace(p,destination/p.name)
    validate_xml(destination/'process_08_v23.bpmn')
    return {'status':'layout_candidate_verified','release_ready':False,'semantic_diff':0,'routing_safety':True,'a4_ratio_passed':after['a4_ratio_passed']}


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--candidate-timeout',type=int,default=150,help='maximum routing seconds per placement candidate (1..600)')
    p.add_argument('--no-decision-orientations',action='store_true',help='compare with the four baseline human-style placements')
    p.add_argument('--incumbent',type=Path,help='optional previously verified layout of the identical frozen model')
    p.add_argument('--orientations-only',action='store_true',help='experiment: test only oriented proposals plus a required incumbent')
    p.add_argument('--repack-spine',action='store_true',help='experimental joint placement of primary steps and corrections')
    a=p.parse_args()
    print(json.dumps(run(a.input,a.output_dir,HumanStyleBackend(candidate_seconds=a.candidate_timeout,orient_decisions=not a.no_decision_orientations,incumbent=a.incumbent,orientations_only=a.orientations_only,repack_spine=a.repack_spine)),ensure_ascii=False,indent=2))
