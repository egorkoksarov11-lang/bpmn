"""Draft-phase joint geometry/ports search, followed by a verified sealed result.

Input is a cold-generated internal candidate, never a supplied reference DI.
An entire trial is committed atomically after full XML, typography and routing
audits. During draft trials role bands and neighbouring activities may move.
"""
from pathlib import Path
from collections import Counter
import copy,tempfile,time,math
from bpmn_refkit.model import read_bpmn,TAG_TASK
from bpmn_universal.contract import NS,BD,DC,Q,semantic_equality
from .freeze import equal
from .di_geometry import update_geometry
from .labels import place_labels
from .stable_blocks import safe_geometry
from .narrative_planner import interaction_regions,reading_measure,acceptable_trial
from .orthogonal_compaction import solve_coordinates
from .window_planner import extract_labels,joint_routes
from .quality import contacts,path_length
from bpmn_universal.cli import deadline as time_limit


def write_trial(state,path,svg,boxes,paths,caps,release=()):
    tree=copy.deepcopy(state[0]);root=tree.getroot();plane=root.xpath('.//bd:BPMNPlane',namespaces=NS)[0]
    update_geometry(root,plane,boxes,paths)
    for label in list(root.xpath('.//bd:BPMNLabel',namespaces=NS)):
        n=label.getparent().get('bpmnElement')
        if n in release:label.getparent().remove(label);continue
        bound=label.find(Q(DC,'Bounds'))
        if n in caps and bound is not None:
            for k,v in zip(('x','y','width','height'),caps[n]):bound.set(k,str(v))
    tree.write(str(path),encoding='utf-8',xml_declaration=True)
    return place_labels(path,svg,preserve=True)


def draft_placements(region,state):
    ids=region['nodes'];boxes=state[-2];member=state[8];lanes=state[9]
    from .block_layout import topology_order
    order,_=topology_order(state[4],state[5]);rank={n:i for i,n in enumerate(order)}
    if region['kind']=='strand':rank={n:i for i,n in enumerate(ids)}
    from .turn_templates import turn_proposals
    yield from turn_proposals(region,state)
    # Alternatives move a complete interaction, including nodes in other roles.
    # No global serpentine rows: each short local continuation has one turn at
    # most, and the independent continuity metric decides whether it is useful.
    left=max(min(boxes[n][0] for n in ids),max(boxes[l][0]+60 for l in lanes))
    for columns in (1,2,3):
        for align in (True,False):
            proposal={}
            for lane in lanes:
                part=sorted((n for n in ids if member[n]==lane),key=lambda n:rank[n])
                if not part:continue
                x0=left if align else min(boxes[n][0] for n in part);y0=min(boxes[n][1] for n in part)
                w=max(boxes[n][2] for n in part)+40;h=max(boxes[n][3] for n in part)+80
                for j,n in enumerate(part):
                    row,col=divmod(j,columns)
                    proposal[n]=(x0+col*w,y0+row*h,*boxes[n][2:])
            yield f'interaction-cols-{columns}-align-{int(align)}',proposal


def open_draft_bands(state,caps,proposal,owners):
    """Reserve vertical space before collision repair, not after collisions.

    Otherwise a valid vertical fold in role A appears to collide with role B
    before B has been shifted into its new band. Draft coordinates only.
    """
    nodes,seq,assocs,docs,member,lanes,boxes,paths=state[4:];new=dict(boxes);labels=dict(caps);placed=dict(proposal);cursor=min(boxes[l][1] for l in lanes)
    for lane in sorted(lanes,key=lambda l:(boxes[l][1],l)):
        x,y,w,h=boxes[lane];minimum=min([y+16]+[b[1] for n,b in proposal.items() if member[n]==lane]);extra=max(0,y+16-minimum)
        def padding(n):
            # Reserve the real attachment/caption envelope; bare tasks do not
            # need the old unconditional 100px document reserve.
            required=16
            if n in caps:required=max(required,caps[n][1]+caps[n][3]-boxes[n][1]-boxes[n][3]+8)
            for d,o in owners.items():
                if o==n:required=max(required,24+max(boxes[d][3],caps.get(d,(0,0,0,0))[3])+8)
            return required
        bottom=max([y+h]+[b[1]+b[3]+padding(n) for n,b in proposal.items() if member[n]==lane]);height=bottom-y+extra;dy=cursor-y+extra
        for n,b in boxes.items():
            owner=owners.get(n,n)
            if member.get(owner)==lane:
                new[n]=(b[0],b[1]+dy,*b[2:])
                if n in labels:a=labels[n];labels[n]=(a[0],a[1]+dy,*a[2:])
        for n,b in proposal.items():
            if member[n]==lane:placed[n]=(b[0],b[1]+dy,*b[2:])
        new[lane]=(x,cursor,w,height);cursor+=height
    for n in set(boxes)-nodes.keys()-docs.keys()-lanes.keys():
        x,y,w,h=boxes[n];new[n]=(x,y,w,max(h,cursor-y))
    return new,labels,placed


def refine_narrative(path,svg,source,seconds=60):
    from .pipeline import geometry
    from .scratch_layout import semantic_document_owners
    from .group_space import repair_space
    if not math.isfinite(seconds) or seconds<=0:raise ValueError('Positive finite draft budget required')
    started=time.monotonic();deadline=started+seconds;initial=read_bpmn(path);before=reading_measure(initial);accepted=[];rejected=Counter();trials=0;rejected_reading=[]
    if not initial[9] or any(n not in initial[8] for n in initial[4]):return {'accepted':0,'reason':'incomplete-role-model'}
    regions=interaction_regions(initial[4],initial[5],initial[8])
    with tempfile.TemporaryDirectory(prefix='narrative-draft-',dir=Path(path).parent) as td:
        trial=Path(td)/'trial.bpmn';preview=trial.with_suffix('.svg')
        def consider(state,boxes,paths,caps,kind,release=(),meta=None):
            nonlocal trials
            if time.monotonic()>deadline:return False
            trials+=1
            # Avoid expensive typography checks for obviously inferior drafts.
            lr=write_trial(state,trial,preview,boxes,paths,caps,release)
            g=geometry(trial)
            if not safe_geometry(g,lr):rejected['geometry-or-text']+=1;return False
            after=reading_measure(read_bpmn(trial));old=reading_measure(read_bpmn(path))
            # A temporary expanded draft is not the incumbent. Both guards are
            # needed: improve the committed result and respect the initial cap.
            if not acceptable_trial(before,old,after):
                rejected['reading-trade-rejected']+=1
                rejected_reading.append({'kind':kind,'before':old,'after':after})
                rejected_reading.sort(key=lambda r:r['after']['score']);del rejected_reading[8:]
                return False
            if not semantic_equality(source,trial) or not equal(source,trial):raise ValueError('Narrative refinement semantic/DI freeze violation')
            Path(path).write_bytes(trial.read_bytes());Path(svg).write_bytes(preview.read_bytes())
            accepted.append({'kind':kind,'before':old,'after':after,**(meta or {})});return True
        # Alternate true object/track compaction with free role boundaries.
        # This can shrink empty vertical bands while keeping all original ports
        # and crossings of this generated draft; it does not claim to undo them.
        for axis,weight in ((1,1.5),(0,1.5),(1,.5)):
            if time.monotonic()>deadline:break
            state=read_bpmn(path);solution,error=solve_coordinates(state,axis=axis,width_weight=weight)
            if solution is None:rejected[error]+=1;continue
            consider(state,solution[0],solution[2],solution[1],f'coupled-axis-{axis}',meta={'role_boundaries_variable':bool(axis)})
        # Crossing bundles are chosen from the actual routed graph. Route the
        # whole bundle jointly, including incident gateway links, rather than
        # greedily repairing one line with all others frozen in place.
        state=read_bpmn(path);uv={i:(u,v) for i,u,v,*_ in state[5]+state[6]};bundles=[]
        for i,j,*_ in contacts(state[-1],uv):
            ends=set(uv[i]+uv[j]);group={i,j}
            for n in ends:
                if state[4].get(n,{}).get('kind','').endswith('Gateway'):group.update(k for k,(u,v) in uv.items() if n in (u,v))
            if len(group)<=12 and group not in bundles:bundles.append(group)
        for affected in bundles[:12]:
            if time.monotonic()>deadline-1:break
            state=read_bpmn(path);boxes,paths=state[-2:];caps=extract_labels(state[1]);nodes,seq,assocs,docs,member,lanes=state[4:10]
            obstacles={n:b for n,b in boxes.items() if n in nodes or n in docs};obstacles.update({f'__header_{l}':(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes})
            obstacles.update({'__text_'+n:b for n,b in caps.items() if n not in affected and not(n in nodes and nodes[n]['kind'] in TAG_TASK)})
            internal=tuple(i for i,*_ in seq if i in affected)
            try:
                with time_limit(max(1,min(8,int(deadline-time.monotonic())))):
                    routed=joint_routes(boxes,nodes,seq,assocs,paths,affected,internal,obstacles,old_boxes=boxes,beam_width=5)
            except TimeoutError:rejected['bundle-budget']+=1;continue
            if routed is None:rejected['bundle-no-safe-ports']+=1;continue
            consider(state,boxes,routed,caps,'joint-crossing-bundle',release=affected,meta={'edges':sorted(affected)})
        # Fold an entire later interaction sequence, preserving translated
        # internal paths. A local chain cannot close global empty columns alone.
        from .paragraph_layout import paragraph_candidates
        from .clearance import safe_poly
        from .document_layout import safe_link
        from .quality import overlap_pairs
        for name,new,caps,fixed in paragraph_candidates(read_bpmn(path)):
            if time.monotonic()>deadline-2:break
            state=read_bpmn(path);nodes,seq,assocs,docs,member,lanes,boxes,paths=state[4:];uv={i:(u,v) for i,u,v,*_ in seq+assocs};info={i for i,*_ in assocs}
            obstacles={n:b for n,b in new.items() if n in nodes or n in docs};obstacles.update({f'__header_{l}':(new[l][0],new[l][1],48,new[l][3]) for l in lanes})
            obstacles.update({'__text_'+n:b for n,b in caps.items() if n in nodes or n in docs if not(n in nodes and nodes[n]['kind'] in TAG_TASK)})
            release=set()
            for i,p in fixed.items():
                if not(safe_link(i,p,obstacles,uv,{},nodes=nodes) if i in info and len(p)==2 else safe_poly(i,p,obstacles,uv,nodes=nodes)):release.add(i)
            for i,j in overlap_pairs(fixed):release.update((i,j))
            fixed={i:p for i,p in fixed.items() if i not in release};affected=set(paths)-fixed.keys()
            obstacles.update({'__text_'+n:b for n,b in caps.items() if n in fixed})
            try:
                with time_limit(max(1,min(8,int(deadline-time.monotonic())))):
                    routed=joint_routes(new,nodes,seq,assocs,paths,affected,tuple(i for i,*_ in seq if i in affected),obstacles,old_boxes=boxes,beam_width=4,fixed_seed=fixed)
            except TimeoutError:rejected['paragraph-budget']+=1;continue
            if routed is None:rejected['paragraph-no-safe-ports']+=1;continue
            write_trial(state,trial,preview,new,routed,caps,affected);draft=read_bpmn(trial)
            for axis in (1,0,1):
                if time.monotonic()>deadline:break
                solution,error=solve_coordinates(draft,axis=axis,width_weight=1.5)
                if solution is not None:
                    new,caps,routed=solution;write_trial(draft,trial,preview,new,routed,caps);draft=read_bpmn(trial)
            if consider(draft,new,routed,caps,name,meta={'translated_fixed_paths':len(fixed),'rerouted_paths':len(affected)}):break
        # Elastic interaction trials are deliberately before sealing: resizing
        # a band or moving a blocking neighbour is legal inside this transaction.
        def priority(r):return (0 if r['kind']=='local_strand' else 1),-sum(path_length(initial[-1][i]) for i,u,v,*_ in initial[5] if u in r['nodes'] and v in r['nodes']),r['nodes']
        for region in sorted(regions,key=priority)[:10]:
            if time.monotonic()>deadline-2:break
            if not 3<=len(region['nodes'])<=12:continue
            for name,proposal in draft_placements(region,read_bpmn(path)):
                if time.monotonic()>deadline-1:break
                state=read_bpmn(path);nodes,seq,assocs,docs,member,lanes,boxes,paths=state[4:];caps=extract_labels(state[1]);owners=semantic_document_owners(nodes,docs,assocs,boxes)
                draft_boxes,draft_caps,proposal=open_draft_bands(state,caps,proposal,owners)
                # Place the workflow first, then enumerate real document bays;
                # old attachment positions must not veto a useful draft fold.
                repaired,error=repair_space(draft_boxes,draft_caps,proposal,nodes,docs,owners,member,lanes,region['nodes'][0],max_neighbors=12,defer_documents=True)
                if repaired is None:rejected['draft-'+error]+=1;continue
                new,captions,moved,space=repaired;uv={i:(u,v) for i,u,v,*_ in seq+assocs};affected={i for i,(u,v) in uv.items() if new[u]!=boxes[u] or new[v]!=boxes[v]}
                if not affected or len(affected)>80:rejected['draft-boundary-size']+=1;continue
                from .window_planner import repack_documents
                packed=repack_documents(new,captions,set(docs),owners,nodes,docs,member,lanes,seq,affected)
                if packed is None:rejected['draft-document-bays']+=1;continue
                new,captions=packed
                affected={i for i,(u,v) in uv.items() if new[u]!=boxes[u] or new[v]!=boxes[v]}
                obstacles={n:b for n,b in new.items() if n in nodes or n in docs};obstacles.update({f'__header_{l}':(new[l][0],new[l][1],48,new[l][3]) for l in lanes})
                obstacles.update({'__text_'+n:b for n,b in captions.items() if n not in affected and not(n in nodes and nodes[n]['kind'] in TAG_TASK)})
                internal=tuple(i for i,u,v,*_ in seq if u in region['nodes'] and v in region['nodes'])
                try:
                    with time_limit(max(1,min(8,int(deadline-time.monotonic())))):
                        routed=joint_routes(new,nodes,seq,assocs,paths,affected,internal,obstacles,old_boxes=boxes,beam_width=3)
                except TimeoutError:rejected['draft-budget']+=1;continue
                if routed is None:rejected['draft-no-safe-ports']+=1;continue
                # Evaluate the complete rewritten block together with compressed
                # bands, so temporary role expansion cannot hide a useful fold.
                write_trial(state,trial,preview,new,routed,captions,affected)
                draft=read_bpmn(trial)
                for axis in (1,0,1):
                    if time.monotonic()>deadline:break
                    solution,error=solve_coordinates(draft,axis=axis,width_weight=1.5)
                    if solution is not None:
                        new,captions,routed=solution
                        write_trial(draft,trial,preview,new,routed,captions)
                        draft=read_bpmn(trial)
                if consider(draft,new,routed,captions,'elastic-'+name,meta={'region':region,**space}):break
    return {'method':'interaction hierarchy; draft elastic bands; coupled ports; measured reading continuity; sealed only after independent audit',
            'accepted':len(accepted),'trials':trials,'edits':accepted,'rejections':dict(rejected),'best_rejected_reading':rejected_reading,'regions':regions,'before':before,'after':reading_measure(read_bpmn(path)),
            'source_geometry_used':False,'names_or_numbers_used':False,'seconds':round(time.monotonic()-started,3)}
