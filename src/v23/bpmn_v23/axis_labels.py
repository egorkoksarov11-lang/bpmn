"""Seed reserved named-start captions before the independent text audit."""
from lxml import etree as ET
from bpmn_universal.contract import NS,Q,BD,DC


def seed_captions(root,captions):
    for n,box in captions.items():
        matches=root.xpath('.//bd:BPMNShape[@bpmnElement=$id] | .//bd:BPMNEdge[@bpmnElement=$id]',namespaces=NS,id=n)
        if not matches:raise ValueError('Caption owner missing: '+n)
        shape=matches[0]
        for old in list(shape.findall(Q(BD,'BPMNLabel'))):shape.remove(old)
        label=ET.SubElement(shape,Q(BD,'BPMNLabel'))
        ET.SubElement(label,Q(DC,'Bounds'),**dict(zip(('x','y','width','height'),map(str,box))))
