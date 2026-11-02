"""Use explicit author step numbers as optional layout hints, never business edits."""
import re
from collections import defaultdict,deque,Counter
from .human_search import HumanStyleBackend
from .human_layout import _proposals
from .patterns import analyze
from .readability import graph_returns
from bpmn_refkit.model import TAG_TASK


def step_hints(nodes):
    matches={}
    for n,o in nodes.items():
        if o['kind'] not in TAG_TASK:continue
        m=re.match(r'^\s*(\d{1,2})\.(\d{1,3})\s+',o.get('name',''))
        if m:matches[n]=(int(m[1]),int(m[2]))
    if len(matches)<5:return {}
    section,count=Counter(a for a,b in matches.values()).most_common(1)[0]
    chosen={n:b for n,(a,b) in matches.items() if a==section}
    return chosen if len(chosen)>=sum(o['kind'] in TAG_TASK for o in nodes.values())*.5 else {}


def phase_plan(nodes,seq,member,original,per_column=2):
    motifs=analyze(nodes,seq,member,original);owner=motifs['owner'];hints=step_hints(nodes)
    if not hints:raise ValueError('Insufficient explicit step-number hints; use graph backend instead')
    labels={owner[n]:v for n,v in hints.items()};inc=defaultdict(set);out=defaultdict(set)
    for _,u,v,_ in seq:
        a,b=owner[u],owner[v]
        if a!=b:inc[b].add(a);out[a].add(b)
    explicit=dict(labels)
    for n in motifs['macros']:
        if n in labels:continue
        # Prefer nearest preceding explicit stage. Backtrack by graph distance,
        # not by keywords, numbering of XML IDs or pre-existing coordinates.
        found=[]
        for adjacency in (inc,out):
            todo=deque([(n,0)]);seen={n};best=None
            while todo:
                u,d=todo.popleft()
                if best is not None and d>best:break
                if u in explicit:found.append(explicit[u]);best=d;continue
                for v in sorted(adjacency[u]):
                    if v not in seen:seen.add(v);todo.append((v,d+1))
            if found:break
        # Only the original explicit hints guide propagation; avoid chain-order
        # effects from previously inferred stages.
        hints_for_node=min(found) if found else min(hints.values())
        labels[n]=hints_for_node
    phases=sorted(set(labels.values()));index={p:i for i,p in enumerate(phases)};main={n for c in motifs['components'] for n in c['backbone']};slots={};counts=defaultdict(int)
    for n in sorted(motifs['macros'],key=lambda n:(index[labels[n]]//per_column,n not in main,index[labels[n]],original[n][1],n)):
        col=index[labels[n]]//per_column;lane=member[n];row=counts[lane,col];slots[n]=(col,row)
        if nodes[n]['kind']!='startEvent':counts[lane,col]+=1
    return slots,labels


class PhaseBackend(HumanStyleBackend):
    name='v23-explicit-step-hints'
    def __init__(self,**kwargs):super().__init__(orient_decisions=False,**kwargs)
    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        for per_column in (2,3):
            slots,labels=phase_plan(nodes,seq,member,original,per_column)
            for _,boxes,report in _proposals(nodes,docs,seq,assocs,member,lanes,original,chain_depths=(2,),role_variants=0,slot_plan=slots,compact_doc_bays=True):
                yield f'author-stages-{per_column}',boxes,{**report,'external_engine':'explicit-author-step-hints','feedback_edges':sorted(graph_returns(nodes,seq)),'stage_labels':labels,'stages_per_column':per_column}
