"""Strict whitelist for DI edits, in addition to full business XML equality."""
import copy,hashlib
from lxml import etree as ET
from bpmn_universal.contract import parse,NS,BD,DC,DI,Q


def structure(path):
    root=parse(path);result=[]
    for diagram in root.xpath('.//bd:BPMNDiagram',namespaces=NS):
        diagram=copy.deepcopy(diagram)
        for e in list(diagram.iter()):
            if e.tag in {Q(BD,'BPMNLabel'),Q(DC,'Bounds'),Q(DI,'waypoint')}:
                parent=e.getparent()
                if parent is not None:parent.remove(e)
        for e in diagram.iter():
            if e.text and not e.text.strip():e.text=None
            if e.tail and not e.tail.strip():e.tail=None
        ET.cleanup_namespaces(diagram)
        result.append(ET.tostring(diagram,method='c14n'))
    return b'\n'.join(result)


def equal(source,target):return structure(source)==structure(target)

def digest(path):return hashlib.sha256(structure(path)).hexdigest()
