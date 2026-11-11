"""Polish an internally generated candidate before comparing compositions."""
from pathlib import Path
from bpmn_refkit.model import read_bpmn,TAG_TASK,set_di
from bpmn_universal.contract import NS,semantic_equality
from bpmn_universal.engine import save_labels,arrange_flow_labels
from .deadline import deadline
from .contours import attach,bounding_ports
from .router import refine_paths
from .labels import place_labels
from .freeze import equal
from .pattern_routing import hints_factory
from .return_corridors import hints_factory as return_hints
from .readability import metrics as reading_metrics


def polish_entry(backend,source,entry,folder,seq,assocs,nodes,docs,member,lanes,logs):
    from .pipeline import geometry
    from .di_geometry import update_geometry
    quality,name,bpmn,svg_bytes,report=entry;uv={i:(u,v) for i,u,v,*_ in seq+assocs}
    bp=Path(folder)/'best.bpmn';sp=bp.with_suffix('.svg');bp.write_bytes(bpmn);sp.write_bytes(svg_bytes)
    initial=geometry(bp);original_safe=not initial['excessive_bend_edges']
    tree,root,_,plane,_,_,_,_,_,_,boxes,paths=read_bpmn(bp)
    if getattr(backend,'straight_documents',False):paths={**paths,**bounding_ports({i:paths[i] for i,*_ in seq},uv,boxes,nodes)}
    else:paths=bounding_ports(paths,uv,boxes,nodes)
    obstacles={n:b for n,b in boxes.items() if n in nodes or n in docs}
    obstacles.update({f'__lane_header_{l}':(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes})
    if getattr(backend,'straight_documents',False):
        query='.//bd:BPMNShape/bd:BPMNLabel/dc:Bounds'
        if report.get('reserved_flow_captions'):query+=' | .//bd:BPMNEdge/bd:BPMNLabel/dc:Bounds'
        for b in root.xpath(query,namespaces=NS):
            n=b.getparent().getparent().get('bpmnElement')
            if n in nodes and nodes[n]['kind'] in TAG_TASK:continue
            obstacles['__text_'+n]=tuple(float(b.get(k)) for k in ('x','y','width','height'))
    interrupted=False
    try:
        with deadline(min(120,backend.candidate_seconds)):
            changes=refine_paths(obstacles,uv,paths,rounds=4,avoid_crowding=True,simplify=getattr(backend,'simplify_routes',False),
                routing_policy=getattr(backend,'routing_policy',None),protected_ids=[i for i,*_ in assocs if len(paths[i])<=10] if getattr(backend,'straight_documents',False) else (),
                hints=return_hints(nodes,seq,boxes,member,{l:boxes[l] for l in lanes}) if getattr(backend,'return_corridors',False) else None if report.get('external_engine') or not report.get('slots') else hints_factory(report,boxes,seq,member,{l:boxes[l] for l in lanes}))
    except TimeoutError:changes=[];interrupted=True
    paths=attach(paths,uv,boxes,nodes)
    if getattr(backend,'straight_documents',False):update_geometry(root,plane,{},paths)
    else:set_di(root,plane,{},paths);save_labels(root,plane,boxes,nodes,paths);arrange_flow_labels(root,plane,obstacles,seq,paths)
    tree.write(str(bp),encoding='utf-8',xml_declaration=True);lr=place_labels(bp,sp,preserve=getattr(backend,'preserve_labels',False));g=geometry(bp)
    rank=backend.candidate_rank(bp,boxes,paths,uv,nodes,docs,seq)
    valid=(not lr['unplaced_labels'] and not lr['rendering']['text_overflow_ids'] and not g['label_collision_pairs'] and not g['label_line_cuts']
           and g['routing_safety_passed'] and g['edge_clearance_passed'] and not g['excessive_bend_edges'])
    if not semantic_equality(source,bp) or not equal(source,bp):raise ValueError('Portfolio polish freeze violation')
    if valid and (rank<quality or not original_safe):
        logs.append({'candidate':name+'-refined','status':'verified','rank':rank,'readability':reading_metrics(boxes,paths,nodes,seq),'refinement_interrupted':interrupted,'refinements':changes})
        return rank,name+'-refined',bp.read_bytes(),sp.read_bytes(),report
    logs.append({'candidate':name+'-refined','status':'discarded','rank':rank,'refinement_interrupted':interrupted,'reason':'no improvement or independent audit failed'})
    return entry if original_safe else None
