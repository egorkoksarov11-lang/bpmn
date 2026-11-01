"""BPMN 2.0 XML parsing, immutable business semantics and DI writing."""
from __future__ import annotations
from lxml import etree as ET
import hashlib, json, copy
from pathlib import Path
B = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
BD = 'http://www.omg.org/spec/BPMN/20100524/DI'
DC = 'http://www.omg.org/spec/DD/20100524/DC'
DI = 'http://www.omg.org/spec/DD/20100524/DI'

def Q(n, ns=B):
    return '{%s}%s' % (ns, n)
TAG_TASK = {'task', 'userTask', 'manualTask', 'serviceTask', 'scriptTask', 'businessRuleTask', 'sendTask', 'receiveTask', 'callActivity', 'subProcess', 'transaction'}
TAG_GATE = {'exclusiveGateway', 'parallelGateway', 'inclusiveGateway', 'eventBasedGateway', 'complexGateway'}
TAG_EVENT = {'startEvent', 'endEvent', 'intermediateCatchEvent', 'intermediateThrowEvent', 'boundaryEvent'}
TAG_DOC = {'dataObjectReference', 'dataStoreReference'}

def local(e):
    return ET.QName(e).localname

def semantic_snapshot(root):
    """Semantic XML fingerprint ignoring only DI and document reference drawing.
    Includes every process node/edge/association and their nonvisual attributes.
    """
    res = []
    for e in root.iter():
        typ = local(e)
        if typ in {'BPMNDiagram', 'BPMNPlane', 'BPMNShape', 'BPMNEdge', 'Bounds', 'waypoint', 'BPMNLabel'}:
            continue
        if e.tag.startswith('{' + BD + '}') or e.tag.startswith('{' + DC + '}') or e.tag.startswith('{' + DI + '}'):
            continue
        if typ == 'dataObjectReference':
            continue
        if typ == 'association':
            res.append(('association', e.get('id'), e.get('sourceRef'), e.get('targetRef'), e.get('associationDirection')))
            continue
        if typ in ['documentation', 'extensionElements']:
            continue
        if typ in TAG_TASK | TAG_GATE | TAG_EVENT | {'sequenceFlow', 'participant', 'lane', 'dataObject', 'dataStoreReference', 'laneSet', 'process', 'collaboration'}:
            a = tuple(sorted(((k, v) for k, v in e.attrib.items() if k not in ['implementation'])))
            res.append((typ, a))
        if typ in {'flowNodeRef', 'conditionExpression', 'timerEventDefinition', 'messageEventDefinition'}:
            res.append((typ, (e.text or '').strip(), tuple(sorted(e.attrib.items()))))
    return res

def semantic_digest(root):
    return hashlib.sha256(json.dumps(semantic_snapshot(root), ensure_ascii=False, sort_keys=True).encode()).hexdigest()

def read_bpmn(path):
    tree = ET.parse(str(path))
    root = tree.getroot()
    process = root.find('.//' + Q('process'))
    if process is None:
        raise ValueError('No bpmn:process')
    nodes = {}
    sequences = []
    associates = []
    docs = {}
    lanes = {}
    lane_names = {}
    for lan in process.findall('.//' + Q('lane')):
        lane_names[lan.get('id')] = lan.get('name', '')
        for n in lan.findall(Q('flowNodeRef')):
            lanes[n.text] = lan.get('id')
    for e in process.iter():
        kind = local(e)
        id = e.get('id')
        if not id:
            continue
        if kind in TAG_TASK | TAG_GATE | TAG_EVENT:
            nodes[id] = {'kind': kind, 'name': e.get('name', ''), 'lane': lanes.get(id)}
        if kind in TAG_DOC:
            docs[id] = {'kind': kind, 'name': e.get('name', ''), 'obj': e.get('dataObjectRef', id)}
        if kind == 'sequenceFlow':
            sequences.append((id, e.get('sourceRef'), e.get('targetRef'), e.get('name', '')))
        if kind == 'association':
            associates.append((id, e.get('sourceRef'), e.get('targetRef'), e.get('associationDirection', 'None')))
        if kind in ('dataInputAssociation', 'dataOutputAssociation'):
            # BPMN data associations are nested inside their owning activity.
            # Their raw target/source may point to an internal Property instead
            # of a diagram shape; route the DI edge to/from the activity itself.
            parent=e.getparent()
            owner=parent.get('id') if parent is not None else None
            if kind=='dataInputAssociation':
                sources=[x.text for x in e.findall(Q('sourceRef'))]
                if len(sources)!=1:
                    raise ValueError(f'{id}: exactly one visual input source is supported')
                associates.append((id,sources[0],owner,'Input'))
            else:
                targets=[x.text for x in e.findall(Q('targetRef'))]
                if len(targets)!=1:
                    raise ValueError(f'{id}: exactly one visual output target is supported')
                associates.append((id,owner,targets[0],'Output'))
    bounds = {}
    edges = {}
    plane = root.find('.//' + Q('BPMNPlane', BD))
    if plane is None:
        raise ValueError('BPMN DI plane is missing')
    for shape in plane.findall(Q('BPMNShape', BD)):
        b = shape.find(Q('Bounds', DC))
        id = shape.get('bpmnElement')
        if b is not None:
            bounds[id] = tuple((float(b.get(s)) for s in ['x', 'y', 'width', 'height']))
    for edge in plane.findall(Q('BPMNEdge', BD)):
        edges[edge.get('bpmnElement')] = [(float(w.get('x')), float(w.get('y'))) for w in edge.findall(Q('waypoint', DI))]
    return (tree, root, process, plane, nodes, sequences, associates, docs, lanes, lane_names, bounds, edges)

def set_di(root, plane, boxes, paths):
    shape_by = {e.get('bpmnElement'): e for e in plane.findall(Q('BPMNShape', BD))}
    for n, (x, y, w, h) in boxes.items():
        if n not in shape_by:
            continue
        e = shape_by[n]
        b = e.find(Q('Bounds', DC))
        if b is None:
            b = ET.SubElement(e, Q('Bounds', DC))
        for k, v in zip(('x', 'y', 'width', 'height'), (x, y, w, h)):
            b.set(k, str(round(v, 2)))
        for lab in e.findall(Q('BPMNLabel', BD)):
            e.remove(lab)
    edge_by = {e.get('bpmnElement'): e for e in plane.findall(Q('BPMNEdge', BD))}
    for eid, p in paths.items():
        if eid not in edge_by or len(p) < 2:
            continue
        e = edge_by[eid]
        for w in e.findall(Q('waypoint', DI)):
            e.remove(w)
        for x, y in p:
            ET.SubElement(e, Q('waypoint', DI), x=str(round(x, 2)), y=str(round(y, 2)))
        for lab in e.findall(Q('BPMNLabel', BD)):
            e.remove(lab)

def exact_business_signature(root):
    """Strict original BPMN model subtree signature, excluding only BPMN-DI."""
    o = copy.deepcopy(root)
    for e in list(o):
        if e.tag.startswith('{' + BD + '}') or e.tag.startswith('{' + DI + '}'):
            o.remove(e)
    return hashlib.sha256(ET.tostring(o, method='c14n')).hexdigest()

def lane_boxes(root, plane, names):
    bands = {}
    for s in plane.findall(Q('BPMNShape', BD)):
        id = s.get('bpmnElement')
        if id not in names:
            continue
        box = s.find(Q('Bounds', DC))
        if box is not None:
            bands[id] = (float(box.get('y')), float(box.get('y')) + float(box.get('height')))
    return bands

def validate_di(root, nodes, docs, flows, associations, bounds, paths):
    """Reject missing geometry and dangling sequence/document references."""
    issues = []
    for identifier in sorted(set(nodes) | set(docs)):
        if identifier not in bounds:
            issues.append(f'Missing BPMNShape: {identifier}')
    known = set(nodes) | set(docs)
    for identifier, src, dst, _ in flows + associations:
        if src not in known or dst not in known:
            issues.append(f'Unresolved endpoint for {identifier}: {src} -> {dst}')
        if identifier not in paths or len(paths[identifier]) < 2:
            issues.append(f'Missing BPMNEdge waypoints: {identifier}')
    return issues
