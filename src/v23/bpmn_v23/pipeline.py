"""Strict, staged backend API with independent post-save audits.

Default backend reconstructs the business graph after erasing all input geometry.
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
from .contours import on_contour,label_hits_shape
from .quality import contacts,overlap_pairs,path_length
from .readability import metrics as reading_metrics
from .typography import fits,wrap,task_fits,task_layout,label_layout,TASK_FONT
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
    diagonal=[]; allowed_doc_diagonals=[]; excessive=[]; endpoints=[]; outside=[]; nonfinite=[]
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
            if abs(a[0]-b[0])>0.01 and abs(a[1]-b[1])>0.01:
                if eid in {i for i,_,_,_ in assocs} and len(points)==2 and (u in docs or v in docs):allowed_doc_diagonals.append(eid)
                else:diagonal.append(eid)
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
    measured_font_sizes=[task_layout(o.get('name',''),boxes[n],o['kind'])['font_size'] for n,o in nodes.items() if o['kind'] in TAG_TASK]
    names={**{n:o.get('name','') for n,o in (nodes|docs).items()},**{i:name for i,_,_,name in seq}}
    for bounds in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
        owner=bounds.getparent().getparent().get('bpmnElement')
        if owner in names and not(owner in nodes and nodes[owner]['kind'] in TAG_TASK):measured_font_sizes.append(label_layout(names[owner],tuple(float(bounds.get(k)) for k in ('x','y','width','height')))['font_size'])
    minimum_font_size=min(measured_font_sizes,default=12)
    min_print_font_pt=minimum_font_size*a4_scale/0.3527777778
    labels=[]
    for e in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
        owner=e.getparent().getparent().get('bpmnElement')
        if owner in nodes and nodes[owner]['kind'] in TAG_TASK:continue
        b=tuple(float(e.get(k)) for k in ('x','y','width','height'))
        labels.append((owner,b))
    def overlaps(a,b):return min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0])>0.01 and min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1])>0.01
    label_collisions=[]
    for i,(a,ab) in enumerate(labels):
        for b,bb in labels[i+1:]:
            if overlaps(ab,bb):label_collisions.append([a,b])
        for b,bb in boxes.items():
            if b in nodes or b in docs:
                if a!=b and label_hits_shape(ab,bb,nodes.get(b,{}).get('kind','')):label_collisions.append([a,b])
    uv={i:(u,v) for i,u,v,_ in seq+assocs}
    robust_contacts=contacts(paths,uv)
    overflow=[n for n,o in nodes.items() if o['kind'] in TAG_TASK and not task_fits(o.get('name',''),boxes[n],o['kind'])]
    label_line_cuts=[]
    for owner,rect in labels:
        for eid,points in paths.items():
            if any(bbox_intersect_seg(rect,a,b,clearance=1) for a,b in zip(points,points[1:])):label_line_cuts.append([owner,eid])
    result['readability']=reading_metrics(boxes,paths,nodes,seq)
    result.update(ambiguous_contacts=len(robust_contacts),contact_examples=robust_contacts[:40],task_text_overflows=overflow,label_line_cuts=label_line_cuts)
    label_owners={e.getparent().getparent().get('bpmnElement') for e in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS)}
    result['missing_named_flow_labels']=[i for i,_,_,name in seq if name and i not in label_owners]
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
        a4_ratio_passed=1.35<=ratio<=1.65,estimated_A4_min_font_pt=round(min_print_font_pt,2),minimum_measured_font_size=minimum_font_size,a4_legible_at_8pt=min_print_font_pt>=8,text_overflow_check='shared_measured_ink_layout_OpenSans_10_to_13px',
        crossing_avoidability='not_proven')
    result['collinear_overlap_pairs']=overlap_pairs(paths)
    result['allowed_straight_document_diagonals']=sorted(set(allowed_doc_diagonals))
    result['avg_document_length']=round(sum(path_length(paths[i]) for i,_,_,_ in assocs)/max(1,len(assocs)),2)
    result['routing_safety_passed']=not (result['shape_overlaps'] or result['line_through_shapes'] or result['collinear_overlap_pairs'] or diagonal or endpoints or outside or nonfinite)
    result['release_geometry_passed']=result['routing_safety_passed'] and result['edge_clearance_passed'] and result['a4_ratio_passed'] and min_print_font_pt>=8 and not label_collisions and not excessive and not robust_contacts and not overflow and not label_line_cuts and not result['missing_named_flow_labels']
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
    if backend is None:
        from .scratch_layout import ScratchBackend
        backend=ScratchBackend()
    if destination==source.parent or source.is_relative_to(destination):
        raise ValueError('Destination must be separate from input directory')
    validate_xml(source)
    destination.mkdir(parents=True,exist_ok=True)
    source_bytes=source.read_bytes()
    with tempfile.TemporaryDirectory(prefix='v23-stage-',dir=destination.parent) as td:
        stage=Path(td);bpmn=stage/'process_08_v23.bpmn';svg=stage/'process_08_v23.svg'
        # Reference measurements must not warm typography caches or affect the
        # reconstruction's time budget. Audit source geometry only afterwards.
        before=None if getattr(backend,'source_geometry_used',True) is False else geometry(source)
        report=backend.layout(source,bpmn,svg)
        label_report=place_labels(bpmn,svg,preserve=getattr(backend,'preserve_labels',False))
        if before is None:before=geometry(source)
        validation=validate_xml(bpmn)
        if not semantic_equality(source,bpmn):raise ValueError('Semantic freeze violation')
        if not di_structure_equal(source,bpmn):raise ValueError('DI structure freeze violation')
        after=geometry(bpmn)
        if not after['routing_safety_passed']:raise ValueError({'routing_safety_rejected':after})
        if label_report['unplaced_labels']:raise ValueError({'unplaced_labels':label_report['unplaced_labels']})
        if after['label_collision_pairs'] or after['label_line_cuts'] or after['task_text_overflows'] or after['missing_named_flow_labels'] or label_report['rendering']['text_overflow_ids']:
            raise ValueError({'readability_rejected':after,'rendering':label_report['rendering']})
        if source.read_bytes()!=source_bytes:raise ValueError('Input changed during layout')
        semantic={'equal':True,'diff_count':0,'whitelist':[], 'comparison':'canonical complete XML excluding BPMNDiagram',
                  'source_file':source.name,
                  'source_sha256':hashlib.sha256(source_bytes).hexdigest(),
                  'before_semantic_sha256':hashlib.sha256(normalized_model(source)).hexdigest(),
                  'after_semantic_sha256':hashlib.sha256(normalized_model(bpmn)).hexdigest(),
                  'di_structure_preserved':True,'di_structure_sha256':di_structure_digest(bpmn)}
        if getattr(backend,'reference_profile',None):
            from .reference_metrics import features,evaluate
            checks={'semantic_freeze':True,'DI_freeze':True,'routing_safety':after['routing_safety_passed'],'clearance':after['edge_clearance_passed'],'text_and_labels':not(after['task_text_overflows'] or after['label_collision_pairs'] or after['label_line_cuts']),'no_pathological_bends':not after['excessive_bend_edges']}
            save_json(stage/'reference_conformity.json',evaluate(features(bpmn),backend.reference_profile,checks))
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
    p.add_argument('--search-seconds',type=float,default=None,help='candidate search budget; verified whole-layout fallback required before stopping')
    p.add_argument('--candidate-timeout',type=int,default=30,help='maximum routing seconds per placement candidate (1..600)')
    p.add_argument('--no-decision-orientations',action='store_true',help='compare with the four baseline human-style placements')
    p.add_argument('--incumbent',type=Path,help='optional previously verified layout of the identical frozen model')
    p.add_argument('--orientations-only',action='store_true',help='experiment: test only oriented proposals plus a required incumbent')
    p.add_argument('--repack-spine',action='store_true',help='experimental joint placement of primary steps and corrections')
    p.add_argument('--scenario-blocks',action='store_true',help='experimental compact local loops and joint moves')
    p.add_argument('--layout-engine',choices=['human','elk','author-stages','lane-align','seed-orient','route-refine','local-continuity','axes','adaptive','reference','attachments','scratch','scratch-legacy','scratch-human'],default=None,help='default: scratch; erase every input coordinate before reconstruction')
    p.add_argument('--elk-module',type=Path,help='optional elk.bundled.js path; otherwise install npm dependencies')
    p.add_argument('--reference-profile',type=Path,help='frozen profile from tools/calibrate_references.py')
    p.add_argument('--seed-report',type=Path,help='original placement report for contextual orientation')
    p.add_argument('--refine-only',action='store_true',help='reference engine: compare current source corridors with the required incumbent, without new axis proposals')
    a=p.parse_args()
    if a.layout_engine is None:a.layout_engine='human' if a.orientations_only or a.repack_spine or a.scenario_blocks else 'scratch'
    if a.refine_only and (a.layout_engine!='reference' or a.incumbent is None):p.error('--refine-only requires --layout-engine reference and --incumbent')
    if a.layout_engine in ('scratch','scratch-legacy','scratch-human'):
        if a.incumbent is not None:p.error('Scratch reconstruction forbids external incumbents')
        from .scratch_layout import ScratchBackend,GraphChannelsBackend
        backend=ScratchBackend(candidate_seconds=a.candidate_timeout,control=a.layout_engine=='scratch-human',search_seconds=a.search_seconds,graph_backend=GraphChannelsBackend if a.layout_engine=='scratch-legacy' else None)
    elif a.layout_engine=='attachments':
        from .attachment_refinement import AttachmentBackend
        backend=AttachmentBackend(incumbent=a.incumbent,seconds=a.candidate_timeout)
    elif a.layout_engine=='reference':
        from .reference_layout import ReferenceBackend
        backend=ReferenceBackend(candidate_seconds=a.candidate_timeout,incumbent=a.incumbent,reference_profile=a.reference_profile,refine_only=a.refine_only)
    elif a.layout_engine=='elk':
        from .elk_layout import ElkBackend
        backend=ElkBackend(elk_module=a.elk_module,candidate_seconds=a.candidate_timeout,incumbent=a.incumbent,reference_profile=a.reference_profile)
    elif a.layout_engine=='adaptive':
        from .adaptive_layout import AdaptiveBackend
        backend=AdaptiveBackend(candidate_seconds=a.candidate_timeout,incumbent=a.incumbent,reference_profile=a.reference_profile)
    elif a.layout_engine=='axes':
        from .axis_layout import AxisBackend
        backend=AxisBackend(candidate_seconds=a.candidate_timeout,incumbent=a.incumbent,reference_profile=a.reference_profile)
    elif a.layout_engine=='local-continuity':
        from .continuity import ContinuityBackend
        backend=ContinuityBackend(candidate_seconds=a.candidate_timeout,incumbent=a.incumbent,reference_profile=a.reference_profile)
    elif a.layout_engine=='route-refine':
        from .route_refinement import RouteRefinementBackend
        backend=RouteRefinementBackend(candidate_seconds=a.candidate_timeout,incumbent=a.incumbent,reference_profile=a.reference_profile)
    elif a.layout_engine=='seed-orient':
        if a.seed_report is None:p.error('--seed-report is required for seed-orient')
        from .seed_orientation import SeedOrientationBackend
        backend=SeedOrientationBackend(seed_report=a.seed_report,candidate_seconds=a.candidate_timeout,incumbent=a.incumbent,reference_profile=a.reference_profile)
    elif a.layout_engine=='lane-align':
        from .lane_alignment import LaneAlignmentBackend
        backend=LaneAlignmentBackend(candidate_seconds=a.candidate_timeout,incumbent=a.incumbent,reference_profile=a.reference_profile)
    elif a.layout_engine=='author-stages':
        from .phase_layout import PhaseBackend
        backend=PhaseBackend(candidate_seconds=a.candidate_timeout,incumbent=a.incumbent,reference_profile=a.reference_profile)
    else:backend=HumanStyleBackend(candidate_seconds=a.candidate_timeout,orient_decisions=not a.no_decision_orientations,incumbent=a.incumbent,orientations_only=a.orientations_only,repack_spine=a.repack_spine,scenario_blocks=a.scenario_blocks,reference_profile=a.reference_profile)
    print(json.dumps(run(a.input,a.output_dir,backend),ensure_ascii=False,indent=2))
