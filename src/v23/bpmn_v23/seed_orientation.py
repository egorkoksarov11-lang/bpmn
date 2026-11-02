"""Reorient decisions in a verified layout, using its own saved row metadata."""
from pathlib import Path
import json
from .human_search import HumanStyleBackend
from .decision_layout import orient,reflow,_valid
from bpmn_refkit.model import read_bpmn


def layout_metadata(path):
    report=json.loads(Path(path).read_text())['backend_report'];selected=report['selected_candidate']
    matches=[c for c in report['candidates'] if c.get('layout') and selected.startswith(c['candidate'])]
    if not matches:raise ValueError('Seed report does not contain its selected placement metadata')
    return max(matches,key=lambda c:len(c['candidate']))['layout']


class SeedOrientationBackend(HumanStyleBackend):
    name='v23-contextual-seed-orientations'
    def __init__(self,seed_report,**kwargs):
        super().__init__(orient_decisions=False,**kwargs);self.seed_report=Path(seed_report)
        if self.incumbent is None:raise ValueError('Verified seed required')
    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        boxes=read_bpmn(self.incumbent)[-2];report=layout_metadata(self.seed_report)
        # The report is geometry metadata only. Frozen XML remains authoritative.
        if not set(report['pairs']).issubset(nodes) or not set(report['pairs'].values()).issubset(nodes):raise ValueError('Seed report IDs do not match model')
        changed,info=orient(boxes,report,nodes,docs,seq,assocs,member)
        if info['orientation_changes']:yield 'contextual-decisions',changed,{**info,'external_engine':'seed-context'}
        orientation={a:'right' for a in report['pairs']}
        for a,g in report['pairs'].items():
            x,y,w,h=boxes[a]
            targets=[v for _,u,v,_ in seq if u==g and v!=a and member[v]==member[a]]
            if any(abs(boxes[v][0]-x)<w*.3 and abs(boxes[v][1]-y)>h for v in targets):orientation[a]='left'
        candidate=reflow(boxes,report,orientation,nodes,docs,member)
        if _valid(candidate,nodes,docs,member):yield 'same-column-return-decisions',candidate,{**report,'decision_orientations':orientation,'external_engine':'seed-context'}
