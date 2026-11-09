"""Compose independently laid-out processes without merging their token graphs."""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import tempfile
from lxml import etree as ET
from bpmn_universal.contract import B, BD, DC, DI, NS, Q, parse, normalized_model, semantic_equality
from bpmn_refkit.model import TAG_TASK, TAG_GATE, TAG_EVENT, read_bpmn
from bpmn_refkit.geometry import bbox_intersect_seg
from .freeze import equal as di_equal
from .typography import wrap, width

NODE = TAG_TASK | TAG_GATE | TAG_EVENT


def is_collaboration(path, for_geometry=False):
    root = parse(path)
    if for_geometry:
        return len(root.findall(Q(B,'process'))) > 1 or bool(root.findall('.//' + Q(B,'messageFlow')))
    return root.find(Q(B, 'collaboration')) is not None or len(root.findall(Q(B, 'process'))) > 1


def extract(root, process_id):
    result = copy.deepcopy(root)
    for element in list(result):
        if element.tag == Q(B, 'collaboration') or element.tag == Q(B, 'process') and element.get('id') != process_id:
            result.remove(element)
    process = result.find(Q(B, 'process'))
    if process is None: raise ValueError('Process not found: ' + process_id)
    ids = {e.get('id') for e in process.iter() if e.get('id')}
    plane = result.find('.//' + Q(BD, 'BPMNPlane'))
    if plane is None: raise ValueError('Missing collaboration DI plane')
    plane.set('bpmnElement', process_id)
    for element in list(plane):
        if element.get('bpmnElement') not in ids: plane.remove(element)
    return result


def write(root, path):
    ET.ElementTree(root).write(str(path), encoding='utf-8', xml_declaration=True)


def validate_collaboration(path):
    from .pipeline import validate_xml
    root = parse(path)
    processes = root.findall(Q(B, 'process'))
    collaborations = root.findall(Q(B, 'collaboration'))
    if not 1 <= len(processes) <= 2 or len(collaborations) != 1:
        raise ValueError('Нужны 1–2 процесса и один collaboration')
    planes = root.findall('.//' + Q(BD, 'BPMNPlane'))
    if len(planes) != 1: raise ValueError('Нужен один общий BPMNPlane')
    plane, collab = planes[0], collaborations[0]
    if plane.get('bpmnElement') != collab.get('id'): raise ValueError('BPMNPlane должен ссылаться на collaboration')
    ids = [e.get('id') for e in root.iter() if e.get('id')]
    if len(ids) != len(set(ids)): raise ValueError('Duplicate BPMN IDs')
    by_id = {e.get('id'): e for e in root.iter() if e.get('id')}
    for el in root.iter():
        for attr in ('sourceRef', 'targetRef', 'processRef', 'messageRef', 'dataObjectRef', 'dataStoreRef', 'bpmnElement'):
            value = el.get(attr)
            if value and value not in by_id: raise ValueError(f'{el.get("id")}.{attr}: dangling reference {value}')
            if attr == 'messageRef' and value and by_id[value].tag != Q(B, 'message'):
                raise ValueError('messageRef must reference a message')
    parts = collab.findall(Q(B, 'participant'))
    pids = {p.get('id') for p in processes}
    refs = [p.get('processRef') for p in parts]
    if len(parts) != len(processes) or set(refs) != pids or len(refs) != len(set(refs)):
        raise ValueError('Каждому процессу нужен собственный participant с processRef; пустые пулы пока не поддержаны')
    shapes = plane.findall(Q(BD, 'BPMNShape')); edges = plane.findall(Q(BD, 'BPMNEdge'))
    shape_refs = [s.get('bpmnElement') for s in shapes]; edge_refs = [s.get('bpmnElement') for s in edges]
    if len(shape_refs) != len(set(shape_refs)) or len(edge_refs) != len(set(edge_refs)):
        raise ValueError('Duplicate DI objects')
    for part in parts:
        if part.get('id') not in shape_refs: raise ValueError('Missing participant DI: ' + part.get('id'))
        if next(s for s in shapes if s.get('bpmnElement')==part.get('id')).get('isHorizontal')=='false':
            raise ValueError('Вертикальные пулы пока не поддерживаются; нужны горизонтальные пулы')
    membership = {e.get('id'): p.get('id') for p in processes for e in p.iter() if e.get('id')}
    membership.update({p.get('id'): p.get('processRef') for p in parts})
    messages = collab.findall(Q(B, 'messageFlow'))
    for edge in messages:
        u, v = edge.get('sourceRef'), edge.get('targetRef')
        if u not in membership or v not in membership or membership[u] == membership[v]:
            raise ValueError('messageFlow должен соединять разных участников: ' + str(edge.get('id')))
        for ref in (u, v):
            if ET.QName(by_id[ref]).localname not in TAG_TASK | TAG_EVENT | {'participant'}:
                raise ValueError('messageFlow endpoint must be activity, event or participant: ' + ref)
        if by_id[u].tag in {Q(B, k) for k in ('startEvent', 'intermediateCatchEvent', 'receiveTask')} or by_id[v].tag in {Q(B, k) for k in ('endEvent', 'intermediateThrowEvent', 'sendTask')}:
            raise ValueError('Неверное направление messageFlow для события')
        if edge.get('id') not in edge_refs: raise ValueError('Missing messageFlow DI')
    known_shapes = {p.get('id') for p in parts}
    known_edges = {m.get('id') for m in messages}
    scans = []
    with tempfile.TemporaryDirectory(prefix='bpmn-collab-validation-') as directory:
        for i, process in enumerate(processes):
            sub = extract(root, process.get('id')); target = Path(directory) / f'p{i}.bpmn'; write(sub, target)
            scans.append(validate_xml(target)['preflight'])
            subplane = sub.find('.//' + Q(BD, 'BPMNPlane'))
            known_shapes.update(s.get('bpmnElement') for s in subplane.findall(Q(BD, 'BPMNShape')))
            known_edges.update(s.get('bpmnElement') for s in subplane.findall(Q(BD, 'BPMNEdge')))
    if set(shape_refs) != known_shapes or set(edge_refs) != known_edges: raise ValueError('Unknown collaboration DI elements')
    for shape in shapes:
        b = shape.find(Q(DC, 'Bounds'))
        vals = [] if b is None else [float(b.get(k)) for k in ('x', 'y', 'width', 'height')]
        if len(vals) != 4 or not all(math.isfinite(v) for v in vals) or min(vals[2:]) <= 0: raise ValueError('Invalid DI Bounds')
    for edge in edges:
        points = edge.findall(Q(DI, 'waypoint'))
        if len(points) < 2 or any(not math.isfinite(float(pt.get(k))) for pt in points for k in ('x', 'y')):
            raise ValueError('Invalid DI waypoints')
    counts = {key: sum(s['counts'].get(key, 0) for s in scans) for key in scans[0]['counts']}
    counts.update(processes=len(processes), diagrams=1, participants=len(parts), message_flows=len(messages))
    bare = root.xpath('.//b:intermediateCatchEvent[not(b:messageEventDefinition) and not(b:timerEventDefinition)]/@id', namespaces=NS)
    return {'xml_parse': True, 'reference_integrity': True, 'preflight': {'compatible': True, 'counts': counts,
            'warnings': ['События без определения сохранены без выдуманного триггера: ' + ', '.join(bare)] if bare else []}}


def shift_di(element, dx, dy):
    for bound in element.iter(Q(DC, 'Bounds')):
        bound.set('x', str(float(bound.get('x')) + dx)); bound.set('y', str(float(bound.get('y')) + dy))
    for point in element.iter(Q(DI, 'waypoint')):
        point.set('x', str(float(point.get('x')) + dx)); point.set('y', str(float(point.get('y')) + dy))


def ensure_working_roles(root):
    """Temporary layout frame only; it is never copied into the business model."""
    process = root.find(Q(B, 'process')); plane = root.find('.//' + Q(BD, 'BPMNPlane'))
    members = set(process.xpath('.//b:flowNodeRef/text()', namespaces=NS))
    missing = [e.get('id') for e in process if ET.QName(e).localname in NODE and e.get('id') not in members]
    if not missing: return set()
    used = {e.get('id') for e in root.iter()}
    lid = '__layout_internal_unassigned'
    while any(lid+suffix in used for suffix in ('','_set','_shape')): lid += '_'
    lanes = process.find(Q(B, 'laneSet'))
    if lanes is None: lanes = ET.SubElement(process, Q(B, 'laneSet'), id=lid + '_set')
    lane = ET.SubElement(lanes, Q(B, 'lane'), id=lid, name=process.get('name') or 'Процесс')
    for n in missing: ET.SubElement(lane, Q(B, 'flowNodeRef')).text = n
    shape = ET.SubElement(plane, Q(BD, 'BPMNShape'), id=lid + '_shape', bpmnElement=lid)
    ET.SubElement(shape, Q(DC, 'Bounds'), x='0', y='0', width='1400', height='500')
    return {lid}


def boxes_paths(root):
    plane = root.find('.//' + Q(BD, 'BPMNPlane'))
    boxes = {s.get('bpmnElement'): tuple(float(s.find(Q(DC, 'Bounds')).get(k)) for k in ('x', 'y', 'width', 'height')) for s in plane.findall(Q(BD, 'BPMNShape'))}
    paths = {s.get('bpmnElement'): [(float(p.get('x')), float(p.get('y'))) for p in s.findall(Q(DI, 'waypoint'))] for s in plane.findall(Q(BD, 'BPMNEdge'))}
    return boxes, paths


def layout_messages(root):
    from .router import astar, orthogonal_candidates, overlapping, choice_score
    from .clearance import safe_poly
    from .contours import attach
    boxes, allpaths = boxes_paths(root)
    collab = root.find(Q(B, 'collaboration')); plane = root.find('.//' + Q(BD, 'BPMNPlane'))
    messages = collab.findall(Q(B, 'messageFlow'))
    ids = {m.get('id') for m in messages}
    paths = {i: ps for i, ps in allpaths.items() if i not in ids}
    uv = {}
    nodes = {}
    for process in root.findall(Q(B, 'process')):
        for el in process.iter():
            kind = ET.QName(el).localname
            if kind in NODE: nodes[el.get('id')] = {'kind': kind}
            if kind in ('sequenceFlow', 'association'): uv[el.get('id')] = (el.get('sourceRef'), el.get('targetRef'))
            elif kind in ('dataInputAssociation', 'dataOutputAssociation'):
                owner = el.getparent().get('id')
                uv[el.get('id')] = ((el.findtext(Q(B, 'sourceRef')), owner) if kind == 'dataInputAssociation' else (owner, el.findtext(Q(B, 'targetRef'))))
    uv.update({m.get('id'): (m.get('sourceRef'), m.get('targetRef')) for m in messages})
    parts = {p.get('id') for p in collab.findall(Q(B, 'participant'))}
    lane_ids = set(root.xpath('.//b:lane/@id', namespaces=NS))
    base = {k: b for k, b in boxes.items() if k not in parts | lane_ids}
    for k in lane_ids | parts:
        x, y, w, h = boxes[k]; base['__header_' + k] = (x, y, 48 if k in lane_ids else 36, h)
    for i, b in enumerate(root.xpath('.//bd:BPMNLabel/dc:Bounds', namespaces=NS)):
        if b.getparent().getparent().get('bpmnElement') not in ids:
            base[f'__text_existing_{i}'] = tuple(float(b.get(k)) for k in ('x', 'y', 'width', 'height'))
    edge_di = {e.get('bpmnElement'): e for e in plane.findall(Q(BD, 'BPMNEdge'))}
    for message in sorted(messages, key=lambda e: (abs(boxes[e.get('sourceRef')][0] - boxes[e.get('targetRef')][0]), e.get('id'))):
        eid, u, v = message.get('id'), message.get('sourceRef'), message.get('targetRef')
        obstacles = dict(base)
        for ref in (u, v):
            if ref in parts: obstacles[ref] = boxes[ref]
        used = {p[index] for i, p in paths.items() for index in (0, -1) if uv[i][0 if index == 0 else 1] in (u, v)}
        candidates = [p for p in orthogonal_candidates(eid, obstacles, uv, paths, allpaths[eid])
                      if p[0] not in used and p[-1] not in used and safe_poly(eid,p,obstacles,uv) and not overlapping(p, paths)]
        path = min(candidates, key=lambda p: choice_score(eid, p, paths, uv, True)) if candidates else None
        if path is None:
            def ports(ref):
                x, y, w, h = boxes[ref]
                return [(round(a, 2), round(b, 2)) for f in (.5, .35, .65, .2, .8)
                        for a, b in ((x, y+h*f), (x+w, y+h*f), (x+w*f, y), (x+w*f, y+h)) if (round(a,2),round(b,2)) not in used]
            pairs = [(s, t) for s in ports(u) for t in ports(v)]
            for margin in (180, 500, 1000):
                path = astar(eid, obstacles, uv, paths, pairs, avoid_crowding=True, window_margin=margin, max_seconds=12)
                if path: break
        if path is None: raise RuntimeError('Не удалось провести messageFlow без наложения: ' + eid)
        path = attach({eid: path}, uv, boxes, nodes)[eid]
        paths[eid] = path
        edge = edge_di[eid]
        for child in list(edge):
            if child.tag in (Q(DI, 'waypoint'), Q(BD, 'BPMNLabel')): edge.remove(child)
        for x, y in path: ET.SubElement(edge, Q(DI, 'waypoint'), x=str(x), y=str(y))
    # Labels are placed after all wires so no later wire can cut their text.
    occupied = list(base.values())
    for message in messages:
        eid = message.get('id'); name = message.get('name', '')
        if not name: continue
        lines = wrap(name, 180, 12); w = min(180, max(width(line, 12) for line in lines) + 8); h = len(lines) * 17 + 6
        options = []
        for a, b in zip(paths[eid], paths[eid][1:]):
            for f in (.5, .25, .75):
                x, y = a[0]+(b[0]-a[0])*f, a[1]+(b[1]-a[1])*f
                for gap in (10, 24, 48, 80):
                    options += [(x-w/2, y+gap, w, h), (x-w/2, y-h-gap, w, h)] if abs(a[1]-b[1]) < .01 else [(x+gap,y-h/2,w,h),(x-w-gap,y-h/2,w,h)]
        from .labels import overlap
        chosen = next((rect for rect in options if not any(overlap(rect, other, gap=2) for other in occupied)
                       and not any(bbox_intersect_seg(rect,a,b,clearance=-2) for ps in paths.values() for a,b in zip(ps,ps[1:]))), None)
        if chosen is None: raise RuntimeError('Нет места для полной подписи messageFlow: ' + eid)
        label = ET.SubElement(edge_di[eid], Q(BD, 'BPMNLabel'))
        ET.SubElement(label, Q(DC, 'Bounds'), **dict(zip(('x','y','width','height'), map(str,chosen))))
        occupied.append(chosen)


def run_collaboration(source, destination, backend):
    from .pipeline import run, save_json
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if getattr(backend,'source_geometry_used',True) is not False:
        raise ValueError('Для collaboration поддерживается построение с нуля: --layout-engine scratch')
    if source.is_relative_to(destination): raise ValueError('Destination must be separate from input directory')
    validation = validate_collaboration(source)
    original = source.read_bytes(); root = parse(source); plane = root.find('.//' + Q(BD, 'BPMNPlane'))
    parts = root.find(Q(B, 'collaboration')).findall(Q(B, 'participant'))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='collaboration-layout-', dir=destination.parent) as td:
        stage = Path(td); results = []; local = {}
        for i, part in enumerate(parts):
            pid = part.get('processRef'); sub = extract(root, pid); synthetic = ensure_working_roles(sub)
            src = stage / f'input{i}.bpmn'; write(sub, src)
            run(src, stage / f'process{i}', copy.deepcopy(backend))
            generated = parse(stage / f'process{i}/process_08_v23.bpmn')
            local[pid] = (generated, synthetic)
            results.append(json.loads((stage / f'process{i}/run_report.json').read_text(encoding='utf-8')))
        # Align communication columns by graph endpoints, never names or numbers.
        offsets = {parts[0].get('processRef'): 0.0}
        node_centers = {}
        for pid, (sub, _) in local.items():
            b, _ = boxes_paths(sub)
            node_centers.update({n:(pid, x+w/2) for n,(x,y,w,h) in b.items()})
        deltas = []
        if len(parts) == 2:
            a, b = (p.get('processRef') for p in parts)
            for message in root.findall('.//' + Q(B, 'messageFlow')):
                u, v = message.get('sourceRef'), message.get('targetRef')
                if u in node_centers and v in node_centers:
                    pa, x = node_centers[u]; pb, y = node_centers[v]
                    deltas.append(x-y if pa == a else y-x)
            offsets[b] = median(deltas) if deltas else 0
        content = {}
        for pid, (sub, synthetic) in local.items():
            bounds = [e for e in sub.xpath('.//dc:Bounds', namespaces=NS) if e.getparent().get('bpmnElement') not in synthetic]
            minx = min(float(e.get('x')) for e in bounds); miny = min(float(e.get('y')) for e in bounds)
            maxx = max(float(e.get('x'))+float(e.get('width')) for e in bounds); maxy = max(float(e.get('y'))+float(e.get('height')) for e in bounds)
            points = sub.findall('.//' + Q(DI,'waypoint'))
            if points:
                minx=min(minx,min(float(p.get('x')) for p in points));miny=min(miny,min(float(p.get('y')) for p in points))
                maxx=max(maxx,max(float(p.get('x')) for p in points));maxy=max(maxy,max(float(p.get('y')) for p in points))
            content[pid] = (minx, miny, maxx, maxy)
        left = min(content[pid][0] + offsets[pid] for pid in local)
        right = max(content[pid][2] + offsets[pid] for pid in local)
        poolx, poolw = 40, right-left+140
        shape_by = {s.get('bpmnElement'):s for s in plane.findall(Q(BD,'BPMNShape'))}
        element_by = {e.get('bpmnElement'):e for e in plane}
        y = 80
        for part in parts:
            pid = part.get('processRef'); sub, synthetic = local[pid]; x0,y0,x1,y1 = content[pid]
            dx, dy = poolx+76-left+offsets[pid], y+30-y0
            for element in sub.find('.//' + Q(BD,'BPMNPlane')):
                identity = element.get('bpmnElement')
                if identity in synthetic: continue
                if identity not in element_by: raise ValueError('Unexpected generated DI identity: ' + str(identity))
                replacement = copy.deepcopy(element); shift_di(replacement,dx,dy)
                if root.xpath('.//b:lane[@id=$id]',namespaces=NS,id=identity):
                    lane_bound=replacement.find(Q(DC,'Bounds'));lane_bound.set('x',str(poolx+36));lane_bound.set('width',str(poolw-36))
                plane.replace(element_by[identity],replacement); element_by[identity]=replacement
            height = y1-y0+60
            bounds = shape_by[part.get('id')].find(Q(DC,'Bounds'))
            for key,value in zip(('x','y','width','height'),(poolx,y,poolw,height)): bounds.set(key,str(value))
            # Old external pool labels must not survive as detached obstacles.
            for label in shape_by[part.get('id')].findall(Q(BD,'BPMNLabel')): shape_by[part.get('id')].remove(label)
            y += height + max(96, 32*len(root.findall('.//' + Q(B,'messageFlow'))))
        layout_messages(root)
        target = stage/'process_08_v23.bpmn'; write(root,target)
        if not semantic_equality(source,target) or not di_equal(source,target): raise ValueError('Collaboration semantic/DI freeze violation')
        geometry = collaboration_geometry(target)
        if not geometry['routing_safety_passed'] or not geometry['edge_clearance_passed'] or geometry['label_collision_pairs'] or geometry['label_line_cuts']:
            raise ValueError({'collaboration_geometry_rejected':geometry})
        from .collaboration_svg import render_collaboration
        render_collaboration(target,stage/'process_08_v23.svg')
        validate_collaboration(target)
        if source.read_bytes()!=original: raise ValueError('Input changed during collaboration layout')
        save_json(stage/'semantic_diff.json',{'equal':True,'diff_count':0,'comparison':'complete XML excluding BPMNDiagram; participants, processRef, event definitions, messageFlow and document references included',
            'source_sha256':hashlib.sha256(original).hexdigest(),'before_semantic_sha256':hashlib.sha256(normalized_model(source)).hexdigest(),
            'after_semantic_sha256':hashlib.sha256(normalized_model(target)).hexdigest(),'di_structure_preserved':True})
        save_json(stage/'geometry_report.json',{'before':{'not_scored':'source geometry is not used'},'after':geometry})
        from . import __version__
        save_json(stage/'run_report.json',{'version':__version__,'backend':'collaboration/scratch-per-process','status':'layout_candidate_verified','release_ready':False,
            'validation':validation,'backend_report':{'from_scratch':True,'processes':results,'message_flows':len(root.findall('.//'+Q(B,'messageFlow'))),
            'pool_order':'participant declaration order; horizontal offsets from message endpoint medians','business_graphs_merged':False}})
        destination.mkdir(parents=True,exist_ok=True)
        for name in ('process_08_v23.bpmn','process_08_v23.svg','semantic_diff.json','geometry_report.json','run_report.json'):
            (destination/name).write_bytes((stage/name).read_bytes())
    return {'status':'layout_candidate_verified','release_ready':False,'semantic_diff':0,'routing_safety':True,'processes':len(parts)}


def collaboration_geometry(path):
    from .pipeline import geometry
    from .contours import on_contour
    from .quality import contacts, overlap_pairs, path_length
    root = parse(path); boxes, paths = boxes_paths(root)
    per_process = []
    with tempfile.TemporaryDirectory(prefix='collaboration-audit-') as directory:
        for i, proc in enumerate(root.findall(Q(B,'process'))):
            p = Path(directory)/f'{i}.bpmn'; write(extract(root,proc.get('id')),p)
            per_process.append(geometry(p))
    parts = root.findall('.//'+Q(B,'participant')); messages = root.findall('.//'+Q(B,'messageFlow'))
    nodes = {e.get('id'):ET.QName(e).localname for proc in root.findall(Q(B,'process')) for e in proc.iter() if ET.QName(e).localname in NODE | {'dataObjectReference','dataStoreReference'}}
    uv = {e.get('id'):(e.get('sourceRef'),e.get('targetRef')) for e in root.iter() if e.tag in (Q(B,'sequenceFlow'),Q(B,'association'),Q(B,'messageFlow'))}
    for proc in root.findall(Q(B,'process')):
        for e in proc.iter():
            if e.tag==Q(B,'dataInputAssociation'):uv[e.get('id')]=(e.findtext(Q(B,'sourceRef')),e.getparent().get('id'))
            if e.tag==Q(B,'dataOutputAssociation'):uv[e.get('id')]=(e.getparent().get('id'),e.findtext(Q(B,'targetRef')))
    invalid=[];hits=[];diagonals=[];outside=[];clearance=[];headers=[]
    for message in messages:
        eid,u,v=message.get('id'),message.get('sourceRef'),message.get('targetRef');ps=paths[eid]
        if len(ps)<2 or any(not math.isfinite(c) for pt in ps for c in pt): invalid.append(eid);continue
        if not on_contour(ps[0],boxes[u],nodes.get(u,'')) or not on_contour(ps[-1],boxes[v],nodes.get(v,'')): invalid.append(eid)
        for i,(a,b) in enumerate(zip(ps,ps[1:])):
            if abs(a[0]-b[0])>.01 and abs(a[1]-b[1])>.01:diagonals.append(eid)
            for n,kind in nodes.items():
                if n==u and i==0 or n==v and i==len(ps)-2:continue
                if bbox_intersect_seg(boxes[n],a,b,clearance=0):hits.append([eid,n])
                if bbox_intersect_seg(boxes[n],a,b,clearance=-7.9):clearance.append([eid,n])
            for lane in root.xpath('.//b:lane/@id',namespaces=NS):
                x,y,w,h=boxes[lane]
                if bbox_intersect_seg((x,y,48,h),a,b,clearance=0):headers.append([eid,lane])
            for part in parts:
                identity=part.get('id');x,y,w,h=boxes[identity]
                if identity not in (u,v) and bbox_intersect_seg((x,y,36,h),a,b,clearance=0):headers.append([eid,identity])
    for part in parts:
        x,y,w,h=boxes[part.get('id')];proc=root.xpath('./b:process[@id=$id]',namespaces=NS,id=part.get('processRef'))[0]
        for node in proc.iter():
            if node.get('id') not in nodes:continue
            a,b,c,d=boxes[node.get('id')]
            if a<x+36 or b<y or a+c>x+w or b+d>y+h:outside.append(node.get('id'))
        internal_ids={e.get('id') for e in proc.iter() if e.get('id')}
        for eid,ps in paths.items():
            if eid in internal_ids and any(a<x+36 or b<y or a>x+w or b>y+h for a,b in ps):outside.append(eid)
    from .labels import overlap
    labels=[(b.getparent().getparent().get('bpmnElement'),tuple(float(b.get(k)) for k in ('x','y','width','height'))) for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS)]
    collisions=[];cuts=[]
    for i,(owner,rect) in enumerate(labels):
        collisions.extend([owner,n] for n,other in labels[i+1:] if overlap(rect,other,gap=0))
        collisions.extend([owner,n] for n in nodes if n!=owner and overlap(rect,boxes[n],gap=0))
        cuts.extend([owner,eid] for eid,ps in paths.items() if any(bbox_intersect_seg(rect,a,b,clearance=0) for a,b in zip(ps,ps[1:])))
    overlaps=overlap_pairs(paths);allcontacts=contacts(paths,uv)
    pool_overlap=any(overlap(boxes[a.get('id')],boxes[b.get('id')],gap=0) for i,a in enumerate(parts) for b in parts[i+1:])
    safe=not(invalid or hits or diagonals or outside or overlaps or pool_overlap) and all(g['routing_safety_passed'] for g in per_process)
    return {'processes':per_process,'routing_safety_passed':safe,'edge_clearance_passed':not(clearance or headers) and all(g['edge_clearance_passed'] for g in per_process),
            'edge_object_clearance_violations':clearance,'lane_header_cuts':headers,
            'invalid_endpoints':invalid,'line_through_shapes':hits,'diagonal_edges':diagonals,'outside_pools':outside,'pool_overlaps':pool_overlap,
            'collinear_overlap_pairs':overlaps,'ambiguous_contacts':len(allcontacts),'contact_examples':allcontacts[:30],
            'label_collision_pairs':collisions,'label_line_cuts':cuts,'message_flows':len(messages),
            'message_total_length':sum(path_length(paths[m.get('id')]) for m in messages),
            'global_optimality_proven':False}
