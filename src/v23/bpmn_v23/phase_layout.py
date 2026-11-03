"""Graph-only phase layout. Text is used only for measured presentation."""
from collections import defaultdict,deque,Counter
from .human_search import HumanStyleBackend
from .human_layout import _proposals
from .patterns import analyze
from .readability import graph_returns
from bpmn_refkit.model import TAG_TASK


def step_hints(nodes):
    """Compatibility API: text-derived hints are deliberately disabled."""
    return {}


def phase_plan(nodes,seq,member,original,per_column=2):
    from .stage_episodes import semantic_stages
    motifs,labels=semantic_stages(nodes,seq,member,original)
    phases=sorted(set(labels.values()));index={p:i for i,p in enumerate(phases)};main={n for c in motifs['components'] for n in c['backbone']};slots={};counts=defaultdict(int)
    for n in sorted(motifs['macros'],key=lambda n:(index[labels[n]]//per_column,n not in main,index[labels[n]],original[n][1],n)):
        col=index[labels[n]]//per_column;lane=member[n];row=counts[lane,col];slots[n]=(col,row)
        if nodes[n]['kind']!='startEvent':counts[lane,col]+=1
    return slots,labels


class PhaseBackend(HumanStyleBackend):
    name='v23-graph-phases'
    def __init__(self,**kwargs):super().__init__(orient_decisions=False,**kwargs)
    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        for per_column in (2,3):
            slots,labels=phase_plan(nodes,seq,member,original,per_column)
            for _,boxes,report in _proposals(nodes,docs,seq,assocs,member,lanes,original,chain_depths=(2,),role_variants=0,slot_plan=slots,compact_doc_bays=True):
                yield f'author-stages-{per_column}',boxes,{**report,'external_engine':'graph-only-phases','feedback_edges':sorted(graph_returns(nodes,seq)),'stage_labels':labels,'stages_per_column':per_column}
