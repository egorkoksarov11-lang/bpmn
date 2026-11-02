"""Human-like local group drags on an already cold-generated verified layout.

Every accepted move preserves complete business XML and passes independent
routing, clearance and typography audits. No external reference is consulted.
"""
from pathlib import Path
from collections import defaultdict
from statistics import median
import copy,math,tempfile,time
from bpmn_refkit.model import read_bpmn,TAG_TASK
from bpmn_refkit.geometry import bbox_intersect_seg
from bpmn_universal.engine import quick_routes
from bpmn_universal.contract import NS,semantic_equality
from .freeze import equal
from .di_geometry import update_geometry
from .quality import contacts,path_length
from .clearance import safe_poly
from .router import overlapping,orthogonal_candidates
from .contours import attach
from .labels import place_labels
from .patterns import analyze
from .scratch_layout import semantic_document_owners


def physical_bends(points):
    vv=[(b[0]-a[0],b[1]-a[1]) for a,b in zip(points,points[1:]) if math.dist(a,b)>.01]
    return sum(abs(a[0]*b[1]-a[1]*b[0])>1e-6*math.hypot(*a)*math.hypot(*b) or a[0]*b[0]+a[1]*b[1]<0 for a,b in zip(vv,vv[1:]))


def local_quality(paths,uv,seq):
    ids={i for i,*_ in seq}
    return (len(contacts(paths,uv)),sum(physical_bends(p) for i,p in paths.items() if i in ids),sum(path_length(p) for i,p in paths.items() if i in ids))


def improves(new,old):
    # Keep contact count monotone. Accept a shorter simpler workflow, or a
    # substantial length reduction with the same number of bends.
    return new[0]<=old[0] and new[1]<=old[1] and (new[1]<old[1] and new[2]<=old[2]*1.01 or new[2]<old[2]-.5)


def edit_groups(path,svg,source,*,seconds=24,max_trials=90):
    from .pipeline import geometry
    started=time.monotonic();changes=[];trials=0;attempted=0
    original=read_bpmn(path);initial=local_quality(original[-1],{i:(u,v) for i,u,v,*_ in original[5]+original[6]},original[5])
    if not original[9] or any(n not in original[8] for n in original[4]):
        return {'method':'skipped: local role editing requires complete lane membership','before':initial,'after':initial,'accepted_moves':[],'source_geometry_used':False}
    with tempfile.TemporaryDirectory(prefix='local-episodes-',dir=Path(path).parent) as folder:
        trial=Path(folder)/'trial.bpmn';preview=trial.with_suffix('.svg')
        for sweep in range(6):
            state=read_bpmn(path);nodes,seq,assocs,docs,member,lanes,boxes,paths=state[4:]
            motifs=analyze(nodes,seq,member,boxes,pair_merges=False);owners=semantic_document_owners(nodes,docs,assocs,boxes)
            groups={n:set(v) for n,v in motifs['macros'].items()}
            for d,n in owners.items():groups[motifs['owner'][n]].add(d)
            labels={b.getparent().getparent().get('bpmnElement'):tuple(float(b.get(k)) for k in ('x','y','width','height')) for b in state[1].xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS)}
            uv={i:(u,v) for i,u,v,*_ in seq+assocs};before=local_quality(paths,uv,seq);proposals=[]
            centre=lambda n:(boxes[n][0]+boxes[n][2]/2,boxes[n][1]+boxes[n][3]/2)
            for eid,u,v,name in seq:
                gu,gv=motifs['owner'][u],motifs['owner'][v]
                if gu==gv:continue
                for moving,anchor,g in ((u,v,gu),(v,u,gv)):
                    a,b=boxes[moving],boxes[anchor];ac,bc=centre(moving),centre(anchor)
                    shifts={(bc[0]-ac[0],0),(0,bc[1]-ac[1])}
                    if member[moving]==member[anchor]:
                        shifts|={(b[0]+b[2]+28-a[0],bc[1]-ac[1]),(b[0]-28-a[2]-a[0],bc[1]-ac[1]),(bc[0]-ac[0],b[1]+b[3]+24-a[1]),(bc[0]-ac[0],b[1]-24-a[3]-a[1])}
                    burden=path_length(paths[eid])+physical_bends(paths[eid])*80
                    for dx,dy in shifts:
                        if abs(dx)+abs(dy)<1:continue
                        proposals.append((-burden,g,round(dx,2),round(dy,2)))
            seen=set();accepted=False
            for _,group,dx,dy in sorted(proposals):
                key=(group,dx,dy)
                if key in seen:continue
                seen.add(key);attempted+=1
                if time.monotonic()-started>=seconds or trials>=max_trials:break
                moved=groups[group];new=dict(boxes)
                for n in moved:
                    x,y,w,h=boxes[n];new[n]=(x+dx,y+dy,w,h)
                def role(n):return member.get(owners.get(n,n))
                if any(role(n) not in boxes or new[n][0]<boxes[role(n)][0]+56 or new[n][1]<boxes[role(n)][1]+8 or new[n][0]+new[n][2]>boxes[role(n)][0]+boxes[role(n)][2]-8 or new[n][1]+new[n][3]>boxes[role(n)][1]+boxes[role(n)][3]-8 for n in moved):continue
                def overlap(a,b):return min(a[0]+a[2]+4,b[0]+b[2])-max(a[0]-4,b[0])>0 and min(a[1]+a[3]+4,b[1]+b[3])-max(a[1]-4,b[1])>0
                if any(overlap(new[a],b) for a in moved for n,b in new.items() if n not in moved and (n in nodes or n in docs)):continue
                affected={i for i,(u,v) in uv.items() if u in moved or v in moved};fixed={i:p for i,p in paths.items() if i not in affected}
                obstacles={n:b for n,b in new.items() if n in nodes or n in docs}
                obstacles.update({f'__lane_{l}':(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes})
                next_labels={n:(x+dx,y+dy,w,h) if n in moved else (x,y,w,h) for n,(x,y,w,h) in labels.items() if n not in affected}
                obstacles.update({'__text_'+n:b for n,b in next_labels.items() if n not in nodes or nodes[n]['kind'] not in TAG_TASK})
                if any(bbox_intersect_seg(new[n],a,b,clearance=-7.9) for n in moved for p in fixed.values() for a,b in zip(p,p[1:])):continue
                if any(bbox_intersect_seg(cap,a,b,clearance=1) for n,cap in next_labels.items() if n in moved for p in fixed.values() for a,b in zip(p,p[1:])):continue
                candidate=dict(fixed);failed=False;trials+=1
                for eid in sorted(affected,key=lambda i:(i not in {e[0] for e in seq},path_length(paths[i]),i)):
                    u,v=uv[eid];used_u={p[0] for i,p in candidate.items() if uv[i][0]==u}|{p[-1] for i,p in candidate.items() if uv[i][1]==u}
                    used_v={p[0] for i,p in candidate.items() if uv[i][0]==v}|{p[-1] for i,p in candidate.items() if uv[i][1]==v}
                    possibilities=[p for p in orthogonal_candidates(eid,obstacles,uv,candidate,paths[eid]) if p[0] not in used_u and p[-1] not in used_v and safe_poly(eid,p,obstacles,uv) and not overlapping(p,candidate)]
                    if not possibilities:failed=True;break
                    def rank(p):return (len(contacts({**candidate,eid:p},{i:uv[i] for i in candidate.keys()|{eid}})),physical_bends(p)*100+path_length(p))
                    candidate[eid]=min(possibilities,key=rank)
                if failed:continue
                candidate=attach(candidate,uv,new,nodes);quality=local_quality(candidate,uv,seq)
                info_ids={i for i,*_ in assocs}
                if sum(path_length(candidate[i]) for i in info_ids)>sum(path_length(paths[i]) for i in info_ids)*1.05+.1:continue
                if sum(physical_bends(candidate[i]) for i in info_ids)>sum(physical_bends(paths[i]) for i in info_ids):continue
                if not improves(quality,before):continue
                tree=copy.deepcopy(state[0]);root=tree.getroot();plane=root.xpath('.//bd:BPMNPlane',namespaces=NS)[0]
                update_geometry(root,plane,{n:new[n] for n in moved},candidate)
                for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
                    n=b.getparent().getparent().get('bpmnElement')
                    if n in moved:
                        b.set('x',str(float(b.get('x'))+dx));b.set('y',str(float(b.get('y'))+dy))
                tree.write(str(trial),encoding='utf-8',xml_declaration=True);lr=place_labels(trial,preview,preserve=True);g=geometry(trial)
                if lr['unplaced_labels'] or lr['rendering']['text_overflow_ids'] or not g['routing_safety_passed'] or not g['edge_clearance_passed'] or g['label_collision_pairs'] or g['label_line_cuts'] or g['excessive_bend_edges'] or g['missing_named_flow_labels'] or g['task_text_overflows']:continue
                if any(d['id'] in affected|moved for d in lr['distant_from_owner']):continue
                if not semantic_equality(source,trial) or not equal(source,trial):raise ValueError('Local episode editing freeze violation')
                Path(path).write_bytes(trial.read_bytes());Path(svg).write_bytes(preview.read_bytes())
                changes.append({'group_size':len(moved),'dx':dx,'dy':dy,'quality_before':before,'quality_after':quality});accepted=True;break
            if not accepted:break
    final=read_bpmn(path);last=local_quality(final[-1],{i:(u,v) for i,u,v,*_ in final[5]+final[6]},final[5])
    return {'method':'generated-layout group drags; incident-wire rerouting; monotone contact/bend/length acceptance; independent audits','before':initial,'after':last,'accepted_moves':changes,'route_trials':trials,'considered_moves':attempted,'seconds':round(time.monotonic()-started,3),'source_geometry_used':False}
