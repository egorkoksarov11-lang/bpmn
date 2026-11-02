"""Geometry updates which retain the author's label bounds and branch captions.

The immutable v22 set_di intentionally deletes captions for reconstruction.
Refinement must explicitly preserve them instead.
"""
import copy
from bpmn_refkit.model import set_di
from bpmn_universal.contract import Q,BD


def update_geometry(root,plane,boxes,paths):
    owners=list(plane.findall(Q(BD,'BPMNShape')))+list(plane.findall(Q(BD,'BPMNEdge')))
    labels={e.get('bpmnElement'):[copy.deepcopy(l) for l in e.findall(Q(BD,'BPMNLabel'))] for e in owners}
    set_di(root,plane,boxes,paths)
    for e in owners:
        if e.get('bpmnElement') in boxes or e.get('bpmnElement') in paths:
            for label in labels[e.get('bpmnElement')]:e.append(label)
