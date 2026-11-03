"""Re-evaluate role order on the current geometry, then rebuild affected routes."""
from pathlib import Path
import copy,tempfile,time
from bpmn_refkit.model import read_bpmn,TAG_TASK
from bpmn_universal.contract import NS,semantic_equality
from bpmn_universal.cli import deadline
from .freeze import equal
from .lane_ordering import reorder_lanes
from .scratch_layout import semantic_document_owners
from .contours import bounding_ports,attach
from .clearance import safe_poly
from .router import route_graph,overlapping
from .di_geometry import update_geometry
from .labels import place_labels
from .layout_objective import objective
from .window_planner import extract_labels


def refine_roles(path,svg,source,seconds=30):
    from .pipeline import geometry
    started=time.monotonic();m=read_bpmn(path);tree,root,_,plane,nodes,seq,assocs,docs,member,lanes,boxes,paths=m
    if not lanes or any(n not in member for n in nodes):return {'status':'incomplete-role-model'}
    labels=extract_labels(root);old_score,old_detail=objective(boxes,paths,nodes,seq,member,docs,assocs,labels.values());report={'reserved_captions':labels,'document_owners':semantic_document_owners(nodes,docs,assocs,boxes)}
    new,detail=reorder_lanes(boxes,report,nodes,docs,seq,member,lanes,'auto');order=detail['lane_order_optimization'];result={'method':'graph interactions; current role geometry; exact subset order; reroute and full audits','accepted':False,'vertical_distance_before':order['before'],'vertical_distance_proposed':order['after'],'objective_before':old_score,'names_used':False}
    if order['before']-order['after']<.1:return {**result,'reason':'current-order-optimal'}
    uv={i:(u,v) for i,u,v,*_ in seq+assocs};headers={f'__header_{l}':(new[l][0],new[l][1],48,new[l][3]) for l in lanes};obstacles={n:b for n,b in new.items() if n in nodes or n in docs};obstacles.update(headers)
    fixed={};info={i for i,u,v,*_ in assocs if u in docs or v in docs}
    for i,(u,v) in uv.items():
        du=(new[u][0]-boxes[u][0],new[u][1]-boxes[u][1]);dv=(new[v][0]-boxes[v][0],new[v][1]-boxes[v][1])
        if du!=dv:continue
        translated=[(x+du[0],y+du[1]) for x,y in paths[i]]
        if i in info and len(translated)==2:
            from .document_layout import safe_link
            if safe_link(i,translated,obstacles,uv,fixed,nodes=nodes):fixed[i]=translated
        else:
            frame=bounding_ports({i:translated},uv,new,nodes)[i]
            if safe_poly(i,frame,obstacles,uv) and not overlapping(frame,fixed):fixed[i]=frame
    caps={n:b for n,b in detail['reserved_captions'].items() if n not in uv or n in fixed};obstacles.update({'__text_'+n:b for n,b in caps.items() if not(n in nodes and nodes[n]['kind'] in TAG_TASK)})
    # A changed role order can invalidate a previously fixed line through a
    # caption. Release it and its caption instead of rejecting the whole order.
    info={i for i,u,v,*_ in assocs if u in docs or v in docs}
    from .document_layout import safe_link
    from .quality import overlap_pairs
    released=set()
    for i,p in list(fixed.items()):
        valid=safe_link(i,p,obstacles,uv,{},nodes=nodes) if i in info and len(p)==2 else safe_poly(i,p,obstacles,uv)
        if not valid:released.add(i)
    for i,j in overlap_pairs(fixed):released.update((i,j))
    for i in released:fixed.pop(i,None);caps.pop(i,None);obstacles.pop('__text_'+i,None)
    result['released_fixed_wires']=len(released)
    try:
        with tempfile.TemporaryDirectory(prefix='current-role-order-',dir=Path(path).parent) as tmp:
            candidate=Path(tmp)/'candidate.bpmn';preview=candidate.with_suffix('.svg')
            with deadline(max(1,int(seconds))):
                routed,_=route_graph(obstacles,nodes,seq,assocs,docs,paths,rounds=0,avoid_crowding=True,fixed_paths=fixed,expand_windows=True,routing_policy={'crossing_penalty':1600,'bend_penalty':240})
                routed=attach(routed,uv,new,nodes);ct=copy.deepcopy(tree);cr=ct.getroot();cp=cr.xpath('.//bd:BPMNPlane',namespaces=NS)[0];update_geometry(cr,cp,new,routed)
                for b in cr.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
                    n=b.getparent().getparent().get('bpmnElement')
                    if n in uv and n not in fixed:b.getparent().getparent().remove(b.getparent())
                    elif n in caps:
                        for k,v in zip(('x','y','width','height'),caps[n]):b.set(k,str(v))
                ct.write(str(candidate),encoding='utf-8',xml_declaration=True);lr=place_labels(candidate,preview,preserve=True);g=geometry(candidate)
                if lr['unplaced_labels'] or lr['rendering']['text_overflow_ids'] or not g['routing_safety_passed'] or not g['edge_clearance_passed'] or g['label_collision_pairs'] or g['label_line_cuts'] or g['task_text_overflows'] or g['missing_named_flow_labels'] or g['excessive_bend_edges']:return {**result,'reason':'routing-text-audit-rejected'}
                if not semantic_equality(source,candidate) or not equal(source,candidate):raise ValueError('Role reordering freeze violation')
                parsed=read_bpmn(candidate);value,new_detail=objective(parsed[-2],parsed[-1],nodes,seq,member,docs,assocs,extract_labels(parsed[1]).values());result['objective_proposed']=value
                if value>=old_score-.02 or new_detail['contacts']>old_detail['contacts']*1.1+1:return {**result,'reason':'readability-rejected'}
                Path(path).write_bytes(candidate.read_bytes());Path(svg).write_bytes(preview.read_bytes());result.update(accepted=True,reason='verified-current-geometry-improvement')
    except (TimeoutError,RuntimeError,ValueError) as error:
        if 'freeze violation' in str(error):raise
        result.update(reason='bounded-routing-failed',error=str(error))
    result['seconds']=round(time.monotonic()-started,3);return result
