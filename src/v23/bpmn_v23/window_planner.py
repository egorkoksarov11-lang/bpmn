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
    for eid,u,v,*_ in seq:
        if u not in nodes or v not in nodes:continue
        a,b=out[u],out[v];left=max(a[0],b[0]);right=min(a[0]+a[2],b[0]+b[2]);top=max(a[1],b[1]);bottom=min(a[1]+a[3],b[1]+b[3])
        if right-left>12 and (a[1]+a[3]<b[1] or b[1]+b[3]<a[1]):
            upper,lower=(a,b) if a[1]<b[1] else (b,a);occupied.append(((left+right)/2-6,upper[1]+upper[3],12,lower[1]-upper[1]-upper[3]))
        elif bottom-top>12 and (a[0]+a[2]<b[0] or b[0]+b[2]<a[0]):
            first,last=(a,b) if a[0]<b[0] else (b,a);occupied.append((first[0]+first[2],(top+bottom)/2-6,last[0]-first[0]-first[2],12))
    for d in moving_docs:
        owner=owners[d];a=out[owner];glyph=out[d];caption=caps.get(d);pieces=[glyph]+([caption] if caption else [])
        x=min(b[0] for b in pieces);y=min(b[1] for b in pieces);w=max(b[0]+b[2] for b in pieces)-x;h=max(b[1]+b[3] for b in pieces)-y;lane=out[member[owner]]
        choices=[(x,y,w,h)]
        for distance in (24,36,52):
            for offset in (0,-32,32):choices.extend([(a[0]+a[2]+distance,a[1]+a[3]/2-h/2+offset,w,h),(a[0]-distance-w,a[1]+a[3]/2-h/2+offset,w,h),(a[0]+a[2]/2-w/2+offset,a[1]-distance-h,w,h),(a[0]+a[2]/2-w/2+offset,a[1]+a[3]+distance,w,h)])
        def valid(b):return b[0]>=lane[0]+56 and b[1]>=lane[1]+8 and b[0]+w<=lane[0]+lane[2]-8 and b[1]+h<=lane[1]+lane[3]-8 and not any(gap(b,q)<6 for q in occupied)
        choices=[b for b in choices if valid(b)]
        if not choices:return None
        block=min(choices,key=lambda b:(abs(gap(b,a)-24)+abs(b[0]-x)*.02+abs(b[1]-y)*.02,b));dx,dy=block[0]-x,block[1]-y
        out[d]=(glyph[0]+dx,glyph[1]+dy,*glyph[2:])
        if caption:caps[d]=(caption[0]+dx,caption[1]+dy,*caption[2:])
        occupied.append(block)
    return out,caps


def joint_routes(boxes,nodes,seq,assocs,paths,affected,internal,obstacles,old_boxes=None,beam_width=3):
    uv={i:(u,v) for i,u,v,*_ in seq+assocs};fixed={i:p for i,p in paths.items() if i not in affected};best=None;cache={}
    def options_for(eid):
        # Geometry and fixed wires are identical in both orders and all beams.
        # Validate them once; only variable-wire overlap and occupied ports vary.
        if eid not in cache:
            u,v=uv[eid];options=compact_route_options(eid,obstacles,uv,fixed)
            if old_boxes is not None:
                options.extend(p for p in reanchored_options(eid,old_boxes,boxes,uv,paths) if safe_poly(eid,p,obstacles,uv) and not overlapping(p,fixed))
                if boxes[u]==old_boxes[u] and boxes[v]==old_boxes[v] and safe_poly(eid,paths[eid],obstacles,uv) and not overlapping(paths[eid],fixed):options.append(paths[eid])
            unique={}
            for p in options:
                p=attach({eid:p},uv,boxes,nodes)[eid]
                if safe_poly(eid,p,obstacles,uv) and not overlapping(p,fixed):unique[tuple(p)]=p
            cache[eid]=list(unique.values())
        return cache[eid]
    for first in (internal,tuple(reversed(internal))):
        order=[i for i in first if i in affected]+sorted(affected-set(first),key=lambda i:(i not in {e[0] for e in seq},path_length(paths[i]),i));beam=[(fixed,0.)]
        for index,eid in enumerate(order):
            next_beam=[];u,v=uv[eid]
            for current,total in beam:
                used={n:{p[0] for i,p in current.items() if uv[i][0]==n}|{p[-1] for i,p in current.items() if uv[i][1]==n} for n in (u,v)}
                choices=[]
                for p in options_for(eid):
                    if p[0] in used[u] or p[-1] in used[v] or overlapping(p,current):continue
                    q=edge_score(eid,p,current,uv);choices.append((q[0]*8+physical_bends(p)*1.5+path_length(p)/200,p))
                for value,p in nsmallest(beam_width if index<2 else 1,choices,key=lambda t:t[0]):next_beam.append(({**current,eid:p},total+value))
            if not next_beam:beam=[];break
            # Incremental scores count each variable/fixed or variable/variable
            # contact once. Fixed/fixed contacts are constant across all choices.
            beam=nsmallest(beam_width if index<2 else 1,next_beam,key=lambda item:item[1])
        for candidate,_ in beam:
            quality=local_quality(candidate,uv,seq)
            if best is None or quality<best[0]:best=quality,candidate
    return None if best is None else best[1]


def _rect_overlap(a,b,gap=4):return min(a[0]+a[2]+gap,b[0]+b[2])-max(a[0]-gap,b[0])>0 and min(a[1]+a[3]+gap,b[1]+b[3])-max(a[1]-gap,b[1])>0


def refine_windows(path,svg,source,seconds=35,max_windows=24):
    from .pipeline import geometry
    if not math.isfinite(seconds) or seconds<=0 or max_windows<=0:raise ValueError('Positive finite window budget and window count required')
    started=time.monotonic();initial=read_bpmn(path);initial_bytes=Path(path).read_bytes();initial_svg=Path(svg).read_bytes();nodes,seq,assocs,docs,member,lanes,boxes,paths=initial[4:];uv={i:(u,v) for i,u,v,*_ in seq+assocs}
    best_bytes=initial_bytes;best_svg=initial_svg;best_quality=None;best_accepted=0
    before=local_quality(paths,uv,seq);before_metrics=metrics(boxes,paths,nodes,seq,member,docs,assocs);logs=[];accepted=0;attempts=0;visited=0
    if not lanes or any(n not in member for n in nodes):return {'status':'skipped-incomplete-role-model','accepted_windows':0}
    ww=windows(nodes,seq)
    # Choose a small problem region, then progress in graph order through it.
    inc=defaultdict(int);out=defaultdict(list)
    for i,u,v,*_ in seq:inc[v]+=1;out[u].append(v)
    roots=sorted(n for n,o in nodes.items() if o['kind']=='startEvent' or not inc[n]);distance={n:0 for n in roots};queue=deque(roots)
    while queue:
        u=queue.popleft()
        for v in out[u]:
            if v not in distance:distance[v]=distance[u]+1;queue.append(v)
    ww=sorted(ww,key=lambda w:(-local_loss(paths,uv,seq,w,member),w['nodes']))[:max_windows]
    ww.sort(key=lambda w:(distance.get(w['nodes'][1],10**6),w['nodes']))
    with tempfile.TemporaryDirectory(prefix='three-step-',dir=Path(path).parent) as folder:
        trial=Path(folder)/'trial.bpmn';preview=trial.with_suffix('.svg')
        for w in ww:
            if time.monotonic()-started>seconds:break
            visited+=1;window_deadline=min(started+seconds,time.monotonic()+max(2.5,seconds/max(1,len(ww))*2))
            state=read_bpmn(path);tree,root,_,plane,nodes,seq,assocs,docs,member,lanes,boxes,paths=state;uv={i:(u,v) for i,u,v,*_ in seq+assocs};old=local_quality(paths,uv,seq);old_local=local_loss(paths,uv,seq,w,member);owners=semantic_document_owners(nodes,docs,assocs,boxes)
            labels={b.getparent().getparent().get('bpmnElement'):tuple(float(b.get(k)) for k in ('x','y','width','height')) for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS)}
            candidates=[]
            for name,placement in proposals(w,boxes,member):
                if time.monotonic()>window_deadline:break
                attempts+=1;moved={n for n,b in placement.items() if any(abs(x-y)>.1 for x,y in zip(b,boxes[n]))}
                if not moved and name!='wire-only':continue
                new={**boxes,**placement};shifts={n:(new[n][0]-boxes[n][0],new[n][1]-boxes[n][1]) for n in moved};new_labels=dict(labels)
                for n in list(moved):
                    dx,dy=shifts[n]
                    if n in new_labels:x,y,tw,th=new_labels[n];new_labels[n]=(x+dx,y+dy,tw,th)
                    for d,owner in owners.items():
                        if owner!=n:continue
                        x,y,dw,dh=boxes[d];new[d]=(x+dx,y+dy,dw,dh);moved.add(d)
                        if d in new_labels:x,y,lw,lh=new_labels[d];new_labels[d]=(x+dx,y+dy,lw,lh)
                affected={i for i,(u,v) in uv.items() if u in moved or v in moved}|set(w['edges'])
                packed=repack_documents(new,new_labels,moved,owners,nodes,docs,member,lanes,seq,affected)
                if packed is None:continue
                new,new_labels=packed
                role=lambda n:member.get(owners.get(n,n))
                if any(role(n) not in lanes or new[n][0]<boxes[role(n)][0]+56 or new[n][1]<boxes[role(n)][1]+8 or new[n][0]+new[n][2]>boxes[role(n)][0]+boxes[role(n)][2]-8 or new[n][1]+new[n][3]>boxes[role(n)][1]+boxes[role(n)][3]-8 for n in moved):continue
                if any(_rect_overlap(new[n],b) for n in moved for v,b in new.items() if v!=n and (v in nodes or v in docs)):continue
                affected={i for i,(u,v) in uv.items() if u in moved or v in moved}|set(w['edges']);fixed={i:p for i,p in paths.items() if i not in affected}
                if any(bbox_intersect_seg(new[n],a,b,clearance=-7.9) for n in moved for p in fixed.values() for a,b in zip(p,p[1:])):continue
                obstacles={n:b for n,b in new.items() if n in nodes or n in docs};obstacles.update({f'__header_{l}':(b[0],b[1],48,b[3]) for l,b in boxes.items() if l in lanes})
                obstacles.update({'__text_'+n:b for n,b in new_labels.items() if n not in affected and not(n in nodes and nodes[n]['kind'] in TAG_TASK)})
                routed=joint_routes(new,nodes,seq,assocs,paths,affected,w['edges'],obstacles,old_boxes=boxes)
                if routed is None:continue
                quality=local_quality(routed,uv,seq);new_local=local_loss(routed,uv,seq,w,member)
                # A neutral frontier move may improve the current window while
                # length is transferred to its still-unplaced boundary step.
                if quality[0]>old[0] or quality[1]>before[1]+1 or quality[2]>before[2]*1.01 or new_local>=old_local-.02:continue
                if sum(path_length(routed[i]) for i,*_ in assocs)>sum(path_length(paths[i]) for i,*_ in assocs)*1.05+.1:continue
                candidates.append((quality[0]*8+quality[1]*1.2+quality[2]/200+new_local*.5,name,new,new_labels,routed,quality,new_local,moved,affected))
            for _,name,new,new_labels,routed,quality,new_local,moved,affected in sorted(candidates,key=lambda c:c[0])[:3]:
                ct=copy.deepcopy(tree);cr=ct.getroot();cp=cr.xpath('.//bd:BPMNPlane',namespaces=NS)[0];update_geometry(cr,cp,{n:new[n] for n in moved},routed)
                for b in cr.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
                    n=b.getparent().getparent().get('bpmnElement')
                    if n in affected:b.getparent().getparent().remove(b.getparent())
                    elif n in moved and n in new_labels:
                        for k,v in zip(('x','y','width','height'),new_labels[n]):b.set(k,str(v))
                ct.write(str(trial),encoding='utf-8',xml_declaration=True);lr=place_labels(trial,preview,preserve=True);g=geometry(trial)
                if lr['unplaced_labels'] or lr['rendering']['text_overflow_ids'] or not g['routing_safety_passed'] or not g['edge_clearance_passed'] or g['label_collision_pairs'] or g['label_line_cuts'] or g['task_text_overflows'] or g['missing_named_flow_labels'] or g['excessive_bend_edges']:continue
                if any(d['id'] in affected|moved for d in lr['distant_from_owner']):continue
                if not semantic_equality(source,trial) or not equal(source,trial):raise ValueError('Three-step freeze violation')
                Path(path).write_bytes(trial.read_bytes());Path(svg).write_bytes(preview.read_bytes());accepted+=1
                if quality[0]<=before[0] and quality[1]<=before[1] and quality[2]<=before[2]*1.01 and quality<before and (best_quality is None or quality<best_quality):
                    best_bytes=Path(path).read_bytes();best_svg=Path(svg).read_bytes();best_quality=quality;best_accepted=accepted
                logs.append({'window':list(w['nodes']),'plan':name,'quality_before':old,'quality_after':quality,'local_before':old_local,'local_after':new_local,'boundary_edges_reconnected':len(affected-set(w['edges']))});break
    trial_accepted=accepted
    final=read_bpmn(path);after=local_quality(final[-1],uv,seq)
    # Commit a whole staged pass only if the complete wire score also improves.
    after_metrics=metrics(final[-2],final[-1],nodes,seq,member,docs,assocs)
    continuity_gain=after_metrics['simple_window_fraction']>before_metrics['simple_window_fraction']+.01 or after_metrics['excess_wire_mean_task_units']<before_metrics['excess_wire_mean_task_units']-.05
    retained=after[0]<=before[0] and after[1]<=before[1] and after[2]<=before[2]*1.01 and (after[1]<before[1] or after[2]<before[2]-.1 or after[0]<before[0] or continuity_gain)
    if best_quality is not None and (not retained or best_quality<after):
        Path(path).write_bytes(best_bytes);Path(svg).write_bytes(best_svg);final=read_bpmn(path);after=best_quality;retained=True;accepted=best_accepted
    elif not retained:Path(path).write_bytes(initial_bytes);Path(svg).write_bytes(initial_svg);final=initial;after=before
    for index,log in enumerate(logs):log['retained']=retained and index<accepted
    return {'method':'overlapping A-B-C windows; anchored A; joint B/C placement; paired-wire beam search in both orders; boundary reconnection; full freeze/geometry/text audits','accepted_windows':accepted if retained else 0,'trial_windows_accepted':trial_accepted,'whole_pass_retained':retained,'placement_attempts':attempts,'windows_visited':visited,'best_verified_prefix_windows':best_accepted,'before':before,'after':after,'diagnostics_before':before_metrics,'diagnostics_after':metrics(final[-2],final[-1],nodes,seq,member,docs,assocs),'stages':logs,'seconds':round(time.monotonic()-started,3),'source_reference_geometry_used':False}
