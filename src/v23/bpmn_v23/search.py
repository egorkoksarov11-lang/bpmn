"""Finite deterministic search: compare complete, semantically verified diagrams."""
import copy,math,tempfile,time
from pathlib import Path
from bpmn_refkit.model import read_bpmn,set_di,TAG_TASK
from bpmn_refkit.geometry import geometry_audit
from bpmn_universal.cli import deadline
from bpmn_universal.contract import semantic_equality,NS
from bpmn_universal.engine import save_labels,arrange_flow_labels
from .placement import candidates
from .router import route_graph
from .quality import score
from .typography import fits
from .contours import attach
from .freeze import equal as di_equal
from .labels import place_labels


def rank_quality(boxes,paths,uv,nodes):
    q=score(paths,uv)
    width=max(b[0]+b[2] for b in boxes.values())-min(b[0] for b in boxes.values())
    height=max(b[1]+b[3] for b in boxes.values())-min(b[1] for b in boxes.values())
    # Unsafe or overflowing diagrams are rejected before ranking. Contacts
    # dominate; bends, path length and actual content area break close ties.
    value=q[0]*100+q[1]*2+q[2]*.002+math.sqrt(width*height)*.02
    return (round(value,3),q,round(width/height,3))


class SearchBackend:
    name='v23-readable-candidate-search'
    def __init__(self,candidate_seconds=150):
        if not isinstance(candidate_seconds,int) or not 1<=candidate_seconds<=600:raise ValueError('candidate_seconds must be an integer from 1 to 600')
        self.candidate_seconds=candidate_seconds
    def layout(self,source,output,svg):
        tree,_,_,_,nodes,seq,assocs,docs,membership,lane_names,original,oldpaths=read_bpmn(source)
        uv={i:(u,v) for i,u,v,_ in seq+assocs};logs=[];best=None
        with tempfile.TemporaryDirectory(prefix='search-',dir=Path(output).parent) as td:
            td=Path(td)
            proposals=[]
            for name,proposal in candidates(nodes,docs,seq,assocs,membership,lane_names,original):
                proposals.append((name,proposal,True))
                if name=='expanded':proposals.append(('expanded-wide',proposal,False))
            for name,proposal,clip_window in proposals:
                started=time.monotonic();obstacles={k:b for k,b in proposal.items() if k in nodes or k in docs}
                pre=geometry_audit(obstacles,{},[],[],nodes,docs)
                if pre['shape_overlaps']:
                    logs.append({'candidate':name,'status':'rejected','reason':'shape overlaps','pairs':pre['shape_overlap_examples']});continue
                try:
                    with deadline(self.candidate_seconds):
                        paths,detail=route_graph(obstacles,nodes,seq,assocs,docs,oldpaths,rounds=2,clip_window=clip_window)
                        metrics=geometry_audit(obstacles,paths,seq,assocs,nodes,docs)
                        if metrics['shape_overlaps'] or metrics['line_through_shapes'] or metrics['crossings'].get('overlapping_segments',0):raise ValueError('unsafe routing')
                        paths=attach(paths,uv,proposal,nodes)
                        candidate=copy.deepcopy(tree);root=candidate.getroot();plane=root.xpath('.//bd:BPMNPlane',namespaces=NS)[0]
                        set_di(root,plane,proposal,paths)
                        save_labels(root,plane,proposal,nodes,paths);arrange_flow_labels(root,plane,proposal,seq,paths)
                        bp=td/(name+'.bpmn');sp=td/(name+'.svg')
                        candidate.write(str(bp),encoding='utf-8',xml_declaration=True)
                        label_report=place_labels(bp,sp)
                        if label_report['unplaced_labels']:raise ValueError('unplaced external labels: '+str(label_report['unplaced_labels']))
                        if label_report['rendering']['text_overflow_ids']:raise ValueError('text overflow: '+str(label_report['rendering']['text_overflow_ids']))
                        if not semantic_equality(source,bp) or not di_equal(source,bp):raise ValueError('freeze verification failed')
                        rank=rank_quality(proposal,paths,uv,nodes)
                        logs.append({'candidate':name,'status':'verified','rank':rank,'seconds':round(time.monotonic()-started,3),'labels':label_report,'details':detail})
                        if best is None or rank<best[0]:best=(rank,name,bp.read_bytes(),sp.read_bytes())
                except (ValueError,RuntimeError,TimeoutError) as error:
                    logs.append({'candidate':name,'status':'rejected','reason':str(error),'seconds':round(time.monotonic()-started,3)})
            if best is None:raise RuntimeError({'no_safe_readable_candidate':logs})
            rank,name,bpmn_bytes,svg_bytes=best
            Path(output).write_bytes(bpmn_bytes);Path(svg).write_bytes(svg_bytes)
        return {'backend':self.name,'selected_candidate':name,'quality':rank,'candidates':logs,'selection':'best among explored safe readable candidates; not a global optimum','removed_redundant_associations':[]}
