"""Receding three-step planning on a cold-generated layout.

A stays anchored. B/C positions and both internal wires are evaluated jointly;
all incident boundary wires participate in validation. Accepted windows overlap
so the next stage can refine the previous stage's lookahead step.
"""
from pathlib import Path
from collections import defaultdict,deque
from heapq import nsmallest
import copy,math,tempfile,time
from bpmn_refkit.model import read_bpmn,TAG_TASK
from bpmn_universal.contract import NS,semantic_equality
from bpmn_refkit.geometry import compress,bbox_intersect_seg
from .window_metrics import windows,bbox_gap,local_loss,metrics
from .local_editing import local_quality,physical_bends
from .scratch_layout import semantic_document_owners
from .clearance import safe_poly
from .quality import edge_score,path_length,contacts
from .router import overlapping
from .contours import attach
from .di_geometry import update_geometry
from .labels import place_labels
from .freeze import equal


def proposals(window,boxes,member,gap=28):
    a,b,c=window['nodes'];aa,bb,cc=(boxes[n] for n in (a,b,c));ax,ay=aa[0]+aa[2]/2,aa[1]+aa[3]/2
    yielded=set()
    def emit(name,bx,by,cx,cy):
        values=(round(bx,2),round(by,2),round(cx,2),round(cy,2))
        if values in yielded:return None
        yielded.add(values)
        return name,{b:(values[0],values[1],*bb[2:]),c:(values[2],values[3],*cc[2:])}
    if member[a]==member[b]==member[c]:
        right=aa[0]+aa[2]+gap;down=aa[1]+aa[3]+gap;up=aa[1]-gap-bb[3]
        settings=[('horizontal',right,ay-bb[3]/2,right+bb[2]+gap,ay-cc[3]/2),('vertical-down',ax-bb[2]/2,down,ax-cc[2]/2,down+bb[3]+gap),('vertical-up',ax-bb[2]/2,up,ax-cc[2]/2,up-gap-cc[3]),('right-down',right,ay-bb[3]/2,right+bb[2]/2-cc[2]/2,ay+bb[3]/2+gap),('down-right',ax-bb[2]/2,down,ax+bb[2]/2+gap,down+bb[3]/2-cc[3]/2)]
    elif member[a]==member[c]:
        settings=[]
        # Keep the reply step adjacent to its request. The other role may align
        # with either end, or shift slightly to separate entry/exit corridors.
        for cx,cy in [(aa[0]+aa[2]+gap,ay-cc[3]/2),(ax-cc[2]/2,aa[1]+aa[3]+gap),(ax-cc[2]/2,aa[1]-gap-cc[3])]:
            for target in (ax,cx+cc[2]/2,(ax+cx+cc[2]/2)/2):
                for offset in (0,-20,20):settings.append(('request-reply',target-bb[2]/2+offset,bb[1],cx,cy))
    else:
        settings=[]
        cx=aa[0]+aa[2]+gap if member[c]==member[a] else cc[0]
        for x in (ax,cc[0]+cc[2]/2,(ax+cc[0]+cc[2]/2)/2):
            for offset in (0,-20,20):
                by=ay-bb[3]/2 if member[a]==member[b] else bb[1]
                bx=aa[0]+aa[2]+gap if member[a]==member[b] else x-bb[2]/2+offset
                cy=by+bb[3]+gap if member[b]==member[c] else cc[1]
                settings.append(('role-handoff',bx,by,cx,cy))
    # The common human pattern task -> decision -> other role turns the
    # decision down/up first; keeping it inline forces two elbows on the handoff.
    if member[a]==member[b] and member[b]!=member[c]:
        for by in (aa[1]+aa[3]+gap,aa[1]-gap-bb[3]):
            for offset in (0,-20,20):
                settings.insert(0,('vertical-decision-handoff',ax-bb[2]/2,by,ax-cc[2]/2+offset,cc[1]))
    elif member[a]!=member[b] and member[b]==member[c]:
        for cy in (bb[1]+bb[3]+gap,bb[1]-gap-cc[3]):
            settings.insert(0,('handoff-vertical-continuation',ax-bb[2]/2,bb[1],ax-cc[2]/2,cy))
        for cx in (ax+bb[2]/2+gap,ax-bb[2]/2-gap-cc[2]):
            settings.insert(0,('handoff-horizontal-continuation',ax-bb[2]/2,bb[1],cx,bb[1]+bb[3]/2-cc[3]/2))
    elif len({member[a],member[b],member[c]})==3:
        for offset in (0,-20,20):
            settings.insert(0,('vertical-role-chain',ax-bb[2]/2,bb[1],ax-cc[2]/2+offset,cc[1]))
    item=emit('wire-only',bb[0],bb[1],cc[0],cc[1])
    if item is not None:yield item
    for args in settings:
        item=emit(*args)
        if item is not None:yield item


def compact_route_options(eid,boxes,uv,paths):
    """Small complete-side shortlist; no A* during speculative window search."""
    u,v=uv[eid];candidates=[];seen=set()
    def ports(b,f):
        x,y,w,h=b;return [(x+w,y+h*f),(x,y+h*f),(x+w*f,y),(x+w*f,y+h)]
    for sf,tf in ((.5,.5),(.2,.8),(.8,.2),(.3,.3),(.7,.7),(.2,.5),(.5,.2),(.8,.5),(.5,.8)):
        for s in ports(boxes[u],sf):
            for t in ports(boxes[v],tf):
                raw=[[s,t],[s,(s[0],t[1]),t],[s,(t[0],s[1]),t]]
                for axis in (0,1):
                    centre=(s[axis]+t[axis])/2
                    raw.append([s,(centre,s[1]),(centre,t[1]),t] if axis==0 else [s,(s[0],centre),(t[0],centre),t])
                for p in raw:
                    p=compress(p);key=tuple(p)
                    if key in seen or len(p)<2:continue
                    seen.add(key)
                    if any(abs(a[0]-b[0])>.01 and abs(a[1]-b[1])>.01 for a,b in zip(p,p[1:])):continue
                    if safe_poly(eid,p,boxes,uv) and not overlapping(p,paths):candidates.append(p)
    return candidates



def reanchored_options(eid,old_boxes,new_boxes,uv,paths):
    p=paths[eid];u,v=uv[eid]
    if len(p)<3:return []
    def port(n,point,near,source):
        old=old_boxes[n];new=new_boxes[n];dx=near[0]-point[0];dy=near[1]-point[1]
        if abs(dx)>=abs(dy):
            f=(point[1]-old[1])/old[3];return (new[0]+new[2] if dx>0 else new[0],new[1]+new[3]*f)
        f=(point[0]-old[0])/old[2];return (new[0]+new[2]*f,new[1]+new[3] if dy>0 else new[1])
    a=port(u,p[0],p[1],True);b=port(v,p[-1],p[-2],False);result=[]
    for x in ((p[1][0],a[1]),(a[0],p[1][1])):
        for y in ((p[-2][0],b[1]),(b[0],p[-2][1])):result.append(compress([a,x,*p[1:-1],y,b]))
    return result


def repack_documents(boxes,labels,moved,owners,nodes,docs,member,lanes,seq,affected):
    """Keep measured glyph/caption blocks out of prospective direct corridors."""
    from .responsive_labels import gap
    out=dict(boxes);caps=dict(labels);moving_docs=sorted(n for n in moved if n in docs)
    occupied=[b for n,b in out.items() if n in nodes or n in docs and n not in moving_docs]
    occupied+=[b for n,b in caps.items() if n not in moving_docs and n not in affected and not(n in nodes and nodes[n]['kind'] in TAG_TASK)]
    def clear_corridor(rect,u,v):
        return not any(_rect_overlap(rect,b,0) for n,b in out.items() if n not in (u,v) and (n in nodes or n in docs and n not in moving_docs))
    for eid,u,v,*_ in seq:
        if u not in nodes or v not in nodes:continue
        a,b=out[u],out[v];left=max(a[0],b[0]);right=min(a[0]+a[2],b[0]+b[2]);top=max(a[1],b[1]);bottom=min(a[1]+a[3],b[1]+b[3])
        if right-left>12 and (a[1]+a[3]<b[1] or b[1]+b[3]<a[1]):
            upper,lower=(a,b) if a[1]<b[1] else (b,a);corridor=((left+right)/2-6,upper[1]+upper[3],12,lower[1]-upper[1]-upper[3])
            if clear_corridor(corridor,u,v):occupied.append(corridor)
        elif bottom-top>12 and (a[0]+a[2]<b[0] or b[0]+b[2]<a[0]):
            first,last=(a,b) if a[0]<b[0] else (b,a);corridor=(first[0]+first[2],(top+bottom)/2-6,last[0]-first[0]-first[2],12)
            if clear_corridor(corridor,u,v):occupied.append(corridor)
    for d in moving_docs:
        owner=owners[d];a=out[owner];glyph=out[d];caption=caps.get(d);pieces=[glyph]+([caption] if caption else [])
        x=min(b[0] for b in pieces);y=min(b[1] for b in pieces);w=max(b[0]+b[2] for b in pieces)-x;h=max(b[1]+b[3] for b in pieces)-y;lane=out[member[owner]]
        choices=[(x,y,w,h)]
        for distance in (24,36,52):
            for offset in (0,-32,32,-64,64,-96,96,-128,128,-w/2-20,w/2+20):choices.extend([(a[0]+a[2]+distance,a[1]+a[3]/2-h/2+offset,w,h),(a[0]-distance-w,a[1]+a[3]/2-h/2+offset,w,h),(a[0]+a[2]/2-w/2+offset,a[1]-distance-h,w,h),(a[0]+a[2]/2-w/2+offset,a[1]+a[3]+distance,w,h)])
        def valid(b):return b[0]>=lane[0]+56 and b[1]>=lane[1]+8 and b[0]+w<=lane[0]+lane[2]-8 and b[1]+h<=lane[1]+lane[3]-8 and not any(gap(b,q)<6 for q in occupied)
        choices=[b for b in choices if valid(b)]
        if not choices:return None
        block=min(choices,key=lambda b:(abs(gap(b,a)-24)+abs(b[0]-x)*.02+abs(b[1]-y)*.02,b));dx,dy=block[0]-x,block[1]-y
        out[d]=(glyph[0]+dx,glyph[1]+dy,*glyph[2:])
        if caption:caps[d]=(caption[0]+dx,caption[1]+dy,*caption[2:])
        occupied.append(block)
    return out,caps


def joint_routes(boxes,nodes,seq,assocs,paths,affected,internal,obstacles,old_boxes=None,beam_width=3,fixed_seed=None):
    from .layout_objective import wire_cost
    uv={i:(u,v) for i,u,v,*_ in seq+assocs};fixed={i:(fixed_seed or {}).get(i,p) for i,p in paths.items() if i not in affected};best=None;cache={}
    info={i for i,u,v,*_ in assocs if u not in nodes or v not in nodes}
    def valid(eid,p,other):
        if eid in info and len(p)==2:
            from .document_layout import safe_link
            return safe_link(eid,p,obstacles,uv,other,nodes=nodes)
        return safe_poly(eid,p,obstacles,uv,nodes=nodes) and not overlapping(p,other)
    def options_for(eid):
        # Geometry and fixed wires are identical in both orders and all beams.
        # Validate them once; only variable-wire overlap and occupied ports vary.
        if eid not in cache:
            u,v=uv[eid];options=compact_route_options(eid,obstacles,uv,fixed)
            if old_boxes is not None:
                options.extend(p for p in reanchored_options(eid,old_boxes,boxes,uv,paths) if safe_poly(eid,p,obstacles,uv) and not overlapping(p,fixed))
                if boxes[u]==old_boxes[u] and boxes[v]==old_boxes[v] and valid(eid,paths[eid],fixed):options.append(paths[eid])
            if eid in info:
                from .document_layout import straight_link
                options.append(straight_link(u,v,boxes,nodes))
            unique={}
            for p in options:
                p=attach({eid:p},uv,boxes,nodes)[eid]
                if valid(eid,p,fixed):unique[tuple(p)]=p
            cache[eid]=list(unique.values())
        return cache[eid]
    for first in (internal,tuple(reversed(internal))):
        order=[i for i in first if i in affected]+sorted(affected-set(first),key=lambda i:(i not in {e[0] for e in seq},path_length(paths[i]),i));beam=[(fixed,0.)]
        for index,eid in enumerate(order):
            next_beam=[];u,v=uv[eid]
            for current,total in beam:
                used={n:{p[0] for i,p in current.items() if uv[i][0]==n}|{p[-1] for i,p in current.items() if uv[i][1]==n} for n in (u,v)}
                choices=[]
                options=options_for(eid)
                if not options:
                    from .router import astar
                    def ports(n):
                        x,y,w,h=boxes[n];return [(x,y+h/2),(x+w,y+h/2),(x+w/2,y),(x+w/2,y+h)]
                    raw=astar(eid,obstacles,uv,current,[(s,t) for s in ports(u) for t in ports(v)],avoid_crowding=True,bend_penalty=240,crossing_penalty=1600,max_seconds=.4)
                    if raw is not None:
                        pp=attach({eid:raw},uv,boxes,nodes)[eid]
                        if safe_poly(eid,pp,obstacles,uv,nodes=nodes):options=[pp]
                for p in options:
                    if p[0] in used[u] or p[-1] in used[v] or overlapping(p,current):continue
                    q=edge_score(eid,p,current,uv)
                    from .readability import edge_crowding
                    choices.append((wire_cost(p,q[0])+3*edge_crowding(p,current,12)/200,p))
                for value,p in nsmallest(beam_width if index<2 else min(2,beam_width),choices,key=lambda t:t[0]):next_beam.append(({**current,eid:p},total+value))
            if not next_beam:beam=[];break
            # Incremental scores count each variable/fixed or variable/variable
            # contact once. Fixed/fixed contacts are constant across all choices.
            beam=nsmallest(beam_width if index<2 else min(2,beam_width),next_beam,key=lambda item:item[1])
        for candidate,_ in beam:
            quality=local_quality(candidate,uv,seq)
            rank=8*quality[0]+sum(wire_cost(candidate[i]) for i in affected)
            if best is None or rank<best[0]:best=rank,candidate
    return None if best is None else best[1]


def _rect_overlap(a,b,gap=4):return min(a[0]+a[2]+gap,b[0]+b[2])-max(a[0]-gap,b[0])>0 and min(a[1]+a[3]+gap,b[1]+b[3])-max(a[1]-gap,b[1])>0


def extract_labels(root):
    return {b.getparent().getparent().get('bpmnElement'):tuple(float(b.get(k)) for k in ('x','y','width','height')) for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS)}


def refine_windows(path,svg,source,seconds=60,max_windows=None):
    from .pipeline import geometry
    from .group_space import repair_space
    from .layout_objective import objective,wire_cost
    from collections import Counter
    if not math.isfinite(seconds) or seconds<=0 or max_windows is not None and max_windows<=0:raise ValueError('Positive finite window budget and window count required')
    started=time.monotonic();initial=read_bpmn(path);initial_bytes=Path(path).read_bytes();initial_svg=Path(svg).read_bytes();nodes,seq,assocs,docs,member,lanes,boxes,paths=initial[4:];uv={i:(u,v) for i,u,v,*_ in seq+assocs}
    if not lanes or any(n not in member for n in nodes):return {'status':'skipped-incomplete-role-model','accepted_windows':0}
    before=local_quality(paths,uv,seq);initial_score,initial_detail=objective(boxes,paths,nodes,seq,member,docs,assocs,extract_labels(initial[1]).values());best_score=initial_score;best_bytes=initial_bytes;best_svg=initial_svg;best_count=0
    logs=[];rejections=Counter();attempts=0;visited=0;accepted=0;temps=0
    all_windows=windows(nodes,seq);candidates_windows=sorted(all_windows,key=lambda w:(-sum(physical_bends(paths[i]) for i in w['edges']),-local_loss(paths,uv,seq,w,member),w['nodes']))
    if max_windows is not None:candidates_windows=candidates_windows[:max_windows]
    # Two complete worklists, alternating difficult-first and topology order.
    # Do not repeatedly spend the whole budget on the same 24 blocked windows.
    worklist=candidates_windows+list(reversed(candidates_windows))
    with tempfile.TemporaryDirectory(prefix='adaptive-group-',dir=Path(path).parent) as folder:
        trial=Path(folder)/'trial.bpmn';preview=trial.with_suffix('.svg')
        for w in worklist:
            if time.monotonic()-started>seconds:break
            visited+=1;window_deadline=min(started+seconds,time.monotonic()+max(1.2,seconds/max(1,len(candidates_windows))))
            state=read_bpmn(path);tree,root,_,plane,nodes,seq,assocs,docs,member,lanes,boxes,paths=state;uv={i:(u,v) for i,u,v,*_ in seq+assocs};old=local_quality(paths,uv,seq);old_local=local_loss(paths,uv,seq,w,member);labels=extract_labels(root)
            old_score,_=objective(boxes,paths,nodes,seq,member,docs,assocs,labels.values());owners=semantic_document_owners(nodes,docs,assocs,boxes);candidates=[]
            for name,placement in proposals(w,boxes,member):
                if time.monotonic()>window_deadline:rejections['window-budget']+=1;break
                attempts+=1
                if name=='wire-only':new=dict(boxes);new_labels=dict(labels);moved=set();space={'neighbor_roots_moved':0,'expanded_role_bands':0}
                else:
                    repaired,reason=repair_space(boxes,labels,placement,nodes,docs,owners,member,lanes,w['nodes'][0])
                    if repaired is None:rejections[reason]+=1;continue
                    new,new_labels,moved,space=repaired
                    if not moved:continue
                moved_objects=moved&(nodes.keys()|docs.keys());affected={i for i,(u,v) in uv.items() if u in moved_objects or v in moved_objects}|set(w['edges'])
                packed=repack_documents(new,new_labels,moved_objects,owners,nodes,docs,member,lanes,seq,affected)
                if packed is None:rejections['document-bay']+=1;continue
                new,new_labels=packed
                obstacles={n:b for n,b in new.items() if n in nodes or n in docs};obstacles.update({f'__header_{l}':(new[l][0],new[l][1],48,new[l][3]) for l in lanes})
                # Translate unchanged internal paths with a uniformly shifted
                # role/group. Only invalidated corridors need reconstruction.
                role_order=sorted(lanes,key=lambda l:(boxes[l][1],l))
                def mapped_y(y):
                    # Insert role space into existing corridors. Horizontal
                    # lines keep a common Y, vertical lines keep their X.
                    lane=next((l for l in role_order if boxes[l][1]<=y<boxes[l][1]+boxes[l][3]),role_order[0] if y<boxes[role_order[0]][1] else role_order[-1])
                    return y+space.get('role_offsets',{}).get(lane,0)
                seed={i:compress([(x,mapped_y(y)) for x,y in p]) for i,p in paths.items()}
                for i,b in list(new_labels.items()):
                    if i in uv:new_labels[i]=(b[0],mapped_y(b[1]),b[2],b[3])
                info={i for i,u,v,*_ in assocs if u in docs or v in docs}
                def seed_safe(i,p):
                    if i in info and len(p)==2:
                        from .document_layout import safe_link
                        return safe_link(i,p,obstacles,uv,{},nodes=nodes)
                    return safe_poly(i,p,obstacles,uv,nodes=nodes)
                for i,p in seed.items():
                    if i not in w['edges'] and seed_safe(i,p):affected.discard(i)
                for i,p in seed.items():
                    if i not in affected and not seed_safe(i,p):affected.add(i)
                from .quality import overlap_pairs
                for i,j in overlap_pairs(seed):affected.update((i,j))
                if len(affected)>24:rejections['reroute-region-limit']+=1;continue
                obstacles.update({'__text_'+n:b for n,b in new_labels.items() if n not in affected and not(n in nodes and nodes[n]['kind'] in TAG_TASK)})
                routed=joint_routes(new,nodes,seq,assocs,paths,affected,w['edges'],obstacles,old_boxes=boxes,fixed_seed=seed)
                if routed is None:rejections['no-joint-route']+=1;continue
                quality=local_quality(routed,uv,seq);estimate,detail=objective(new,routed,nodes,seq,member,docs,assocs,new_labels.values());new_local=local_loss(routed,uv,seq,w,member)
                # Metric tradeoffs are soft inside the uncommitted group. All
                # business/contour/text/overlap requirements remain mandatory.
                if quality[0]>before[0]*1.1+1 or quality[1]>before[1]*1.15+1 or quality[2]>before[2]*1.1 or detail['area']>initial_detail['area']*1.25:rejections['bounded-quality-trade']+=1;continue
                if estimate>=old_score-.02 and (temps>=2 or new_local>=old_local*.8 or estimate>old_score*1.015):rejections['no-readability-gain']+=1;continue
                candidates.append((estimate,name,new,new_labels,routed,moved,affected,space))
            for _,name,new,new_labels,routed,moved,affected,space in sorted(candidates,key=lambda c:c[0])[:3]:
                ct=copy.deepcopy(tree);cr=ct.getroot();cp=cr.xpath('.//bd:BPMNPlane',namespaces=NS)[0];update_geometry(cr,cp,{n:new[n] for n in moved},routed)
                for b in cr.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
                    n=b.getparent().getparent().get('bpmnElement')
                    if n in affected:b.getparent().getparent().remove(b.getparent())
                    elif n in new_labels:
                        for k,v in zip(('x','y','width','height'),new_labels[n]):b.set(k,str(v))
                ct.write(str(trial),encoding='utf-8',xml_declaration=True);lr=place_labels(trial,preview,preserve=True);g=geometry(trial)
                if lr['unplaced_labels'] or lr['rendering']['text_overflow_ids'] or not g['routing_safety_passed'] or not g['edge_clearance_passed'] or g['label_collision_pairs'] or g['label_line_cuts'] or g['task_text_overflows'] or g['missing_named_flow_labels'] or g['excessive_bend_edges']:rejections['full-geometry-or-text-audit']+=1;continue
                if any(d['id'] in affected|moved for d in lr['distant_from_owner']):rejections['caption-distance']+=1;continue
                if not semantic_equality(source,trial) or not equal(source,trial):raise ValueError('Adaptive group freeze violation')
                actual=read_bpmn(trial);value,detail=objective(actual[-2],actual[-1],nodes,seq,member,docs,assocs,extract_labels(actual[1]).values())
                if value>=old_score-.02 and (temps>=2 or value>old_score*1.015):rejections['post-label-objective']+=1;continue
                Path(path).write_bytes(trial.read_bytes());Path(svg).write_bytes(preview.read_bytes());accepted+=1;temps=temps+1 if value>=old_score else 0
                logs.append({'window':list(w['nodes']),'plan':name,'quality_before':old,'quality_after':local_quality(actual[-1],uv,seq),'objective_before':old_score,'objective_after':value,'boundary_edges_reconnected':len(affected-set(w['edges'])),**space})
                if value<best_score-.02:best_score=value;best_bytes=trial.read_bytes();best_svg=preview.read_bytes();best_count=accepted
                break
    Path(path).write_bytes(best_bytes);Path(svg).write_bytes(best_svg);final=read_bpmn(path)
    for index,log in enumerate(logs):log['retained']=index<best_count
    return {'method':'graph-only overlapping windows; adaptive neighbor displacement and role expansion; consistent readability objective; best verified prefix','accepted_windows':best_count,'trial_windows_accepted':accepted,'whole_pass_retained':best_count>0,'placement_attempts':attempts,'windows_visited':visited,'distinct_windows_available':len(all_windows),'window_limit':max_windows,'rejections':dict(rejections),'before':before,'after':local_quality(final[-1],uv,seq),'objective_before':initial_score,'objective_after':best_score,'diagnostics_before':initial_detail['window_readability'],'diagnostics_after':metrics(final[-2],final[-1],nodes,seq,member,docs,assocs),'stages':logs,'seconds':round(time.monotonic()-started,3),'source_reference_geometry_used':False,'names_or_step_numbers_used_for_structure':False}
