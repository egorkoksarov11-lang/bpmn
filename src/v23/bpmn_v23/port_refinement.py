"""Few-bend cleanup on the generated geometry, including adjacent-side ports."""
from pathlib import Path
import copy,tempfile,time
from bpmn_refkit.model import read_bpmn,TAG_TASK
from bpmn_universal.contract import NS,semantic_equality
from .router import orthogonal_candidates,overlapping
from .quality import edge_score,path_length
from .clearance import safe_poly
from .contours import attach
from .local_editing import physical_bends
from .di_geometry import update_geometry
from .labels import place_labels
from .freeze import equal


def refine_ports(path,svg,source,seconds=24):
    from .pipeline import geometry
    start=time.monotonic();changes=[];trials=0
    with tempfile.TemporaryDirectory(prefix='port-refinement-',dir=Path(path).parent) as folder:
        trial=Path(folder)/'trial.bpmn';preview=trial.with_suffix('.svg')
        initial=read_bpmn(path);order=sorted((i for i,*_ in initial[5]),key=lambda i:(-physical_bends(initial[-1][i]),-path_length(initial[-1][i]),i))
        for eid in order:
            if time.monotonic()-start>=seconds:break
            state=read_bpmn(path);tree,root,_,plane,nodes,seq,assocs,docs,member,lanes,boxes,paths=state
            old=paths[eid]
            if physical_bends(old)<2:continue
            uv={i:(u,v) for i,u,v,*_ in seq+assocs};others={i:p for i,p in paths.items() if i!=eid};u,v=uv[eid]
            obstacles={n:b for n,b in boxes.items() if n in nodes or n in docs}
            obstacles.update({f'__lane_{l}':(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes})
            for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
                owner=b.getparent().getparent().get('bpmnElement')
                if owner==eid or owner in nodes and nodes[owner]['kind'] in TAG_TASK:continue
                obstacles['__text_'+owner]=tuple(float(b.get(k)) for k in ('x','y','width','height'))
            before=edge_score(eid,old,others,uv);candidates=[]
            used={n:{p[0] for i,p in others.items() if uv[i][0]==n}|{p[-1] for i,p in others.items() if uv[i][1]==n} for n in (u,v)}
            for p in orthogonal_candidates(eid,obstacles,uv,others,old):
                if p[0] in used[u] or p[-1] in used[v] or not safe_poly(eid,p,obstacles,uv) or overlapping(p,others):continue
                p=attach({eid:p},uv,boxes,nodes)[eid]
                if physical_bends(p)>=physical_bends(old) or path_length(p)>path_length(old)*1.03:continue
                quality=edge_score(eid,p,others,uv)
                if quality[0]<=before[0]:candidates.append((physical_bends(p),quality[0],path_length(p),p))
            for _,_,_,p in sorted(candidates)[:3]:
                trials+=1;ct=copy.deepcopy(tree);cr=ct.getroot();cp=cr.xpath('.//bd:BPMNPlane',namespaces=NS)[0];update_geometry(cr,cp,{}, {eid:p})
                ct.write(str(trial),encoding='utf-8',xml_declaration=True);lr=place_labels(trial,preview,preserve=True);g=geometry(trial)
                if not(g['routing_safety_passed'] and g['edge_clearance_passed']) or g['label_collision_pairs'] or g['label_line_cuts'] or g['excessive_bend_edges'] or g['task_text_overflows'] or g['missing_named_flow_labels'] or lr['unplaced_labels'] or lr['rendering']['text_overflow_ids']:continue
                if any(d['id']==eid for d in lr['distant_from_owner']):continue
                if not semantic_equality(source,trial) or not equal(source,trial):raise ValueError('Port refinement freeze violation')
                Path(path).write_bytes(trial.read_bytes());Path(svg).write_bytes(preview.read_bytes());changes.append({'edge':eid,'bends_before':physical_bends(old),'bends_after':physical_bends(p),'length_before':path_length(old),'length_after':path_length(p)});break
    return {'method':'adjacent-side port candidates; no added contacts; lower bends; bounded length; full independent audit','changes':changes,'trials':trials,'seconds':round(time.monotonic()-start,3),'source_geometry_used':False}
