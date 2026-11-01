"""Supported BPMN 2.0 profile, input validation, semantic audit."""
from __future__ import annotations
from pathlib import Path
from lxml import etree as ET
import copy
import math

B='http://www.omg.org/spec/BPMN/20100524/MODEL'
BD='http://www.omg.org/spec/BPMN/20100524/DI'
DC='http://www.omg.org/spec/DD/20100524/DC'
DI='http://www.omg.org/spec/DD/20100524/DI'
NS={'b':B,'bd':BD,'dc':DC,'di':DI}
Q=lambda namespace,name: '{'+namespace+'}'+name

class UnsupportedBPMN(ValueError):
    """Source has a BPMN construct outside the tested single-process profile."""


def parse(path: Path):
    path=Path(path)
    if not path.is_file():raise FileNotFoundError(str(path))
    if path.stat().st_size>25_000_000:raise UnsupportedBPMN('File exceeds 25 MB safety limit')
    raw=path.read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise UnsupportedBPMN('DOCTYPE/ENTITY is forbidden in untrusted BPMN XML')
    parser=ET.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,huge_tree=False)
    return ET.fromstring(raw,parser)


def preflight(path: Path) -> dict:
    """Fail closed on unsupported cases rather than silently corrupt their DI."""
    root=parse(path)
    errors=[];warnings=[]
    if root.tag != Q(B,'definitions'):errors.append('Root must be bpmn:definitions')
    processes=root.xpath('.//b:process',namespaces=NS)
    planes=root.xpath('.//bd:BPMNPlane',namespaces=NS)
    if len(processes)!=1:errors.append(f'Exactly one process is required (found {len(processes)})')
    if len(planes)!=1:errors.append(f'Exactly one BPMNPlane is required (found {len(planes)})')
    # Nested expanded subprocesses and attached boundary events require relative/container layout.
    attached=root.xpath('.//b:boundaryEvent[@attachedToRef]',namespaces=NS)
    if attached:errors.append(f'{len(attached)} attached boundaryEvent(s): attachment geometry not supported')
    nested=[]
    for sub in root.xpath('.//b:subProcess',namespaces=NS):
        if any(ET.QName(el).localname in {'task','userTask','callActivity','exclusiveGateway','startEvent','endEvent','sequenceFlow'} for el in sub.iterdescendants()):
            nested.append(sub.get('id'))
    if nested:errors.append('Expanded subprocess containment not supported: '+', '.join(str(x) for x in nested))
    nonlocal_flows=root.xpath('.//b:messageFlow',namespaces=NS)
    if nonlocal_flows:errors.append(f'{len(nonlocal_flows)} messageFlow(s): cross-pool routing is not supported')
    if root.xpath('.//b:textAnnotation | .//b:group',namespaces=NS):
        errors.append('textAnnotation/group: obstacle-aware routing not implemented')
    all_ids=[e.get('id') for e in root.iter() if e.get('id')]
    if len(all_ids)!=len(set(all_ids)):errors.append('Duplicate BPMN IDs')
    ids=set(all_ids)
    nodes=[];docs=[];lanes=[];flows=[];assocs=[]
    if processes:
        process=processes[0]
        NODE={'task','userTask','manualTask','serviceTask','scriptTask','businessRuleTask','sendTask','receiveTask','callActivity','subProcess','transaction',
        'exclusiveGateway','parallelGateway','inclusiveGateway','eventBasedGateway','complexGateway','startEvent','endEvent','intermediateCatchEvent','intermediateThrowEvent','boundaryEvent'}
        for el in process.iter():
            local=ET.QName(el).localname
            if local in NODE and el.get('id'):nodes.append(el.get('id'))
            if local in ('dataObjectReference','dataStoreReference') and el.get('id'):docs.append(el.get('id'))
            if local=='lane' and el.get('id'):lanes.append(el.get('id'))
            if local=='sequenceFlow':flows.append(el)
            if local in ('association','dataInputAssociation','dataOutputAssociation'):assocs.append(el)
            if local in ('adHocSubProcess','choreographyTask','eventSubProcess'):
                errors.append(f'Unsupported element kind {local}: {el.get("id")}')
        if not nodes:errors.append('No process nodes detected')
    known=set(nodes)|set(docs)
    for e in flows+assocs:
        i=e.get('id');typ=ET.QName(e).localname
        if typ=='dataInputAssociation':
            refs=[t.text for t in e.findall(Q(B,'sourceRef'))]
            u=refs[0] if len(refs)==1 else None
            v=e.getparent().get('id') if e.getparent() is not None else None
            if len(refs)!=1:errors.append(f'{i}: multi-source dataInputAssociation not supported')
        elif typ=='dataOutputAssociation':
            refs=[t.text for t in e.findall(Q(B,'targetRef'))]
            u=e.getparent().get('id') if e.getparent() is not None else None
            v=refs[0] if len(refs)==1 else None
            if len(refs)!=1:errors.append(f'{i}: multi-target dataOutputAssociation not supported')
        else:u=e.get('sourceRef');v=e.get('targetRef')
        if u not in known or v not in known:
            errors.append(f'Edge {i} endpoints are not known nodes/data references: {u} -> {v}')
    if planes:
        plane=planes[0]
        shapes={s.get('bpmnElement'):s for s in plane.findall(Q(BD,'BPMNShape'))}
        edge_di={s.get('bpmnElement'):s for s in plane.findall(Q(BD,'BPMNEdge'))}
        absent=known-set(shapes)
        if absent:errors.append('Missing diagram shapes: '+', '.join(sorted(absent)[:10]))
        for k,shape in shapes.items():
            if k not in known and k not in lanes:
                defn=root.xpath('//*[@id=$id]',id=k)
                typ=ET.QName(defn[0]).localname if defn else 'unknown'
                if typ!='participant':errors.append(f'Unsupported diagram shape {k} ({typ})')
            bound=shape.find(Q(DC,'Bounds'))
            if bound is None:errors.append(f'No Bounds for shape {k}');continue
            try:
                x,y,w,h=[float(bound.get(z)) for z in ('x','y','width','height')]
                if not all(math.isfinite(a) for a in (x,y,w,h)) or w<=0 or h<=0:
                    errors.append(f'Invalid Bounds for shape {k}')
            except (ValueError,TypeError):errors.append(f'Non-numeric Bounds for shape {k}')
        for el in flows+assocs:
            i=el.get('id')
            if i not in edge_di:errors.append(f'Missing DI edge {i}')
            else:
                pts=edge_di[i].findall(Q(DI,'waypoint'))
                if len(pts)<2:errors.append(f'DI edge {i} has fewer than two waypoints')
        if len(root.xpath('.//b:participant',namespaces=NS)):
            warnings.append('Participants/pools are preserved but not resized or automatically reordered')
        other_edges=set(edge_di)-set(e.get('id') for e in flows+assocs)
        if other_edges:errors.append('Unrouted DI edges are not supported: '+', '.join(sorted(other_edges)[:10]))
    return {'compatible':not errors,'errors':errors,'warnings':warnings,'source':str(path),
            'counts':{'processes':len(processes),'diagrams':len(planes),'nodes':len(nodes),'sequence_flows':len(flows),
                      'associations':len(assocs),'data_references':len(docs),'lanes':len(lanes)}}


def normalized_model(path: Path, removed_associations=()):
    root=copy.deepcopy(parse(path))
    removed=set(removed_associations)
    for elem in list(root.iter()):
        if elem.get('id') in removed:
            parent=elem.getparent()
            if parent is not None:parent.remove(elem)
    for elem in list(root.iter()):
        if elem.tag==Q(BD,'BPMNDiagram'):
            elem.getparent().remove(elem)
    ET.cleanup_namespaces(root)
    return ET.tostring(root,method='c14n')


def semantic_equality(source: Path,target: Path,approved_removed=()):
    return normalized_model(source,approved_removed)==normalized_model(target)


def removable_mirror_ids(path: Path):
    """Return only task->document associations with a reverse document->task pair.

    This is a mechanical prerequisite, NOT evidence that deletion is business-approved.
    """
    root=parse(path)
    known_docs={e.get('id') for e in root.xpath('.//b:dataObjectReference | .//b:dataStoreReference',namespaces=NS)}
    groups={}
    for elem in root.xpath('.//b:association',namespaces=NS):
        u,v=elem.get('sourceRef'),elem.get('targetRef')
        if bool(u in known_docs)==bool(v in known_docs):continue
        groups.setdefault(frozenset((u,v)),[]).append((elem.get('id'),u,v))
    result=set()
    for pairs in groups.values():
        if len(pairs)!=2:continue
        a,b=pairs
        if a[1]==b[2] and a[2]==b[1]:
            result.update(id for id,u,v in pairs if u not in known_docs and v in known_docs)
    return result
