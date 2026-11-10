"""Atomic 4–8 node edits: no neighbour pushing or external role expansion."""
from pathlib import Path
from collections import Counter
from statistics import median
import copy,hashlib,json,math,tempfile,time
from bpmn_refkit.model import read_bpmn,TAG_TASK
from bpmn_refkit.geometry import bbox_intersect_seg
from bpmn_universal.contract import NS,BD,DC,Q,semantic_equality
from .block_layout import graph_blocks,topology_order
from .freeze import equal
from .window_planner import extract_labels,joint_routes,repack_documents
from .scratch_layout import semantic_document_owners
from .di_geometry import update_geometry
from .labels import place_labels
from .quality import path_length
from .layout_objective import objective
from .local_editing import physical_bends


def measures(state):
    value,detail=objective(state[-2],state[-1],state[4],state[5],state[8],state[7],state[6],extract_labels(state[1]).values())
    n=max(1,len(state[5]));bends=sum(physical_bends(state[-1][i]) for i,*_ in state[5])
    return {'score':value+1.2*n*detail['packing'],'area':detail['area'],'contacts':detail['contacts'],
            'length':sum(path_length(state[-1][i]) for i,*_ in state[5]),'bends':bends,
            'hairpins':detail['window_readability']['serial_hairpins']}


def better(before,after):
    # A few elbows can buy substantially shorter travel/footprint. Crowding,
    # actual collisions and every semantic invariant remain hard constraints.
    return (after['contacts']<=before['contacts'] and after['hairpins']<=before['hairpins']
            and after['area']<=before['area']*1.08 and after['length']<=before['length']*1.08
            and after['bends']<=before['bends']+max(2,math.ceil(before['bends']*.15),3 if after['area']<=before['area']*.75 or after['length']<=before['length']*.85 else 0)
            and after['score']<before['score']-.15)


def placements(group,state):
    boxes=state[-2];nodes=state[4];member=state[8];lanes=state[9]
    order,_=topology_order(nodes,state[5]);rank={n:i for i,n in enumerate(order)}
    anchor=min(group,key=rank.get);ax,ay,aw,ah=boxes[anchor]
    from .block_layout import relax_role_axes
    try:
        local,_=relax_role_axes(nodes,state[7],state[5],state[6],member,lanes,boxes,{'reserved_captions':extract_labels(state[1])},movable=set(group))
        yield 'constrained-role-axes',{n:local[n] for n in group}
    except ValueError:pass
    # Translate the whole episode into nearby free space first.
    minx=min(boxes[n][0] for n in group);maxx=max(boxes[n][0]+boxes[n][2] for n in group)
    values={0.0}
    for _,u,v,*_ in state[5]:
        if v in group and u not in group:
            values.update((boxes[u][0]+boxes[u][2]+28-boxes[v][0],boxes[u][0]+boxes[u][2]/2-boxes[v][0]-boxes[v][2]/2))
        if u in group and v not in group:
            values.add(boxes[v][0]-28-boxes[u][2]-boxes[u][0])
    for lane in {member[n] for n in group}:values.add(boxes[lane][0]+60-minx)
    for dx in sorted(values,key=lambda v:(abs(v),v)):
        if abs(dx)>1:yield 'translate', {n:(boxes[n][0]+dx,boxes[n][1],*boxes[n][2:]) for n in group}
    # Independent per-role row counts; roles and unselected objects stay fixed.
    for columns in (1,2,3,len(group)):
        for direction in (1,-1):
            new={};valid=True
            for lane in lanes:
                part=sorted((n for n in group if member[n]==lane),key=rank.get)
                if not part:continue
                cellw=max(boxes[n][2] for n in part)+28;cellh=max(boxes[n][3] for n in part)+42
                x0=min(boxes[n][0] for n in part);y0=min(boxes[n][1] for n in part)
                cap=min(columns,len(part))
                for i,n in enumerate(part):
                    row,col=divmod(i,cap)
                    if row%2:col=cap-1-col
                    old=boxes[n];new[n]=(x0+col*cellw,y0+direction*row*cellh,*old[2:])
            # Pin the episode entry exactly; external wire ends are immutable.
            dx,dy=ax-new[anchor][0],ay-new[anchor][1]
            new={n:(b[0]+dx,b[1]+dy,*b[2:]) for n,b in new.items()}
            yield f'rows-{columns}-direction-{direction}',new


def safe_geometry(g,lr):
    return (g['routing_safety_passed'] and g['edge_clearance_passed'] and
            not(g['label_collision_pairs'] or g['label_line_cuts'] or g['task_text_overflows'] or
                g['missing_named_flow_labels'] or g['excessive_bend_edges'] or lr['unplaced_labels'] or lr['rendering']['text_overflow_ids']))


def refine_blocks(path,svg,source,seconds=60,max_accept=12):
    from .pipeline import geometry
    started=time.monotonic();initial=read_bpmn(path);before=measures(initial);logs=[];reject=Counter();trials=0
    if not initial[9] or any(n not in initial[8] for n in initial[4]):return {'accepted_blocks':0,'reason':'incomplete-role-model'}
    blocks=[g for g in graph_blocks(initial[4],initial[5],initial[8]) if 4<=len(g)<=8]
    # The worst long or sprawling episodes get a share of the bounded budget.
    def priority(group):
        ps=[p for i,p in initial[-1].items() if any(n in group for n in next((e[1:3] for e in initial[5]+initial[6] if e[0]==i),(None,None)))]
        return -sum(path_length(p) for p in ps),group
    blocks.sort(key=priority)
    with tempfile.TemporaryDirectory(prefix='stable-blocks-',dir=Path(path).parent) as directory:
        trial=Path(directory)/'trial.bpmn';preview=trial.with_suffix('.svg')
        for group in blocks:
            if time.monotonic()-started>=seconds or len(logs)>=max_accept:break
            state=read_bpmn(path);old=measures(state);nodes,seq,assocs,docs,member,lanes,boxes,paths=state[4:];uv={i:(u,v) for i,u,v,*_ in seq+assocs}
            owners=semantic_document_owners(nodes,docs,assocs,boxes);labels=extract_labels(state[1]);affected_objects=set(group)|{d for d,o in owners.items() if o in group}
            deadline=min(started+seconds,time.monotonic()+max(2,seconds/max(1,len(blocks))))
            for name,proposal in placements(group,state):
                if time.monotonic()>=deadline:break
                new=dict(boxes);new.update(proposal);caps=dict(labels)
                for n in affected_objects:
                    owner=owners.get(n,n);dx=new[owner][0]-boxes[owner][0];dy=new[owner][1]-boxes[owner][1]
                    if n in docs:new[n]=(boxes[n][0]+dx,boxes[n][1]+dy,*boxes[n][2:])
                    if n in caps:caps[n]=(caps[n][0]+dx,caps[n][1]+dy,*caps[n][2:])
                moved={n for n in affected_objects if new[n]!=boxes[n]}
                if not moved:continue
                # Never expand a role or push another object to make room.
                def in_role(n):
                    x,y,w,h=new[n];lx,ly,lw,lh=boxes[member[owners.get(n,n)]]
                    return x>=lx+56 and y>=ly+8 and x+w<=lx+lw-8 and y+h<=ly+lh-8
                from .labels import overlap
                if not all(in_role(n) for n in moved) or any(overlap(new[a],new[b],gap=5) for a in moved for b in nodes.keys()|docs.keys() if a!=b):reject['occupied-slot']+=1;continue
                affected={i for i,(u,v) in uv.items() if u in moved or v in moved}
                if len(affected)>24:reject['boundary-size']+=1;continue
                packed=repack_documents(new,caps,moved,owners,nodes,docs,member,lanes,seq,affected)
                if packed is None:reject['document-slot']+=1;continue
                new,caps=packed;moved={n for n in affected_objects if new[n]!=boxes[n]}
                fixed={i:p for i,p in paths.items() if i not in affected}
                if any(bbox_intersect_seg(new[n],a,b,clearance=-7.9) for n in moved for p in fixed.values() for a,b in zip(p,p[1:])):reject['fixed-wire']+=1;continue
                obstacles={n:b for n,b in new.items() if n in nodes or n in docs}
                obstacles.update({f'__header_{l}':(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes})
                obstacles.update({'__text_'+n:b for n,b in caps.items() if n not in affected and not(n in nodes and nodes[n]['kind'] in TAG_TASK)})
                internal=tuple(i for i,u,v,*_ in seq if u in group and v in group)
                trials+=1;routed=joint_routes(new,nodes,seq,assocs,paths,affected,internal,obstacles,old_boxes=boxes,beam_width=3)
                if routed is None:reject['ports-or-corridors']+=1;continue
                tree=copy.deepcopy(state[0]);root=tree.getroot();plane=root.xpath('.//bd:BPMNPlane',namespaces=NS)[0]
                update_geometry(root,plane,{n:new[n] for n in moved},{i:routed[i] for i in affected})
                for bound in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
                    n=bound.getparent().getparent().get('bpmnElement')
                    if n in caps and n in moved:
                        for key,value in zip(('x','y','width','height'),caps[n]):bound.set(key,str(value))
                for edge in plane.findall(Q(BD,'BPMNEdge')):
                    if edge.get('bpmnElement') in affected:
                        for label in edge.findall(Q(BD,'BPMNLabel')):edge.remove(label)
                tree.write(str(trial),encoding='utf-8',xml_declaration=True);lr=place_labels(trial,preview,preserve=True)
                # Generic caption placement can tidy an unrelated caption as
                # a side effect. Restore outside anchors before the audit.
                scope=affected_objects|affected;caption_tree=read_bpmn(trial)[0]
                for bound in caption_tree.getroot().xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
                    n=bound.getparent().getparent().get('bpmnElement')
                    if n in labels and n not in scope:
                        for key,value in zip(('x','y','width','height'),labels[n]):bound.set(key,str(value))
                caption_tree.write(str(trial),encoding='utf-8',xml_declaration=True)
                from .render import render
                lr['rendering']=render(trial,preview);g=geometry(trial)
                if not safe_geometry(g,lr):reject['independent-audit']+=1;continue
                actual=read_bpmn(trial);scope=affected_objects|affected;newcaps=extract_labels(actual[1])
                frozen=(all(actual[-2][n]==b for n,b in boxes.items() if n not in affected_objects)
                        and all(actual[-1][i]==p for i,p in fixed.items())
                        and all(n in newcaps and max(abs(x-y) for x,y in zip(b,newcaps[n]))<.06 for n,b in labels.items() if n not in scope))
                if not frozen:reject['external-anchor-changed']+=1;continue
                after=measures(actual)
                if not better(old,after):reject['balanced-score']+=1;continue
                if not semantic_equality(source,trial) or not equal(source,trial):raise ValueError('Stable block semantic/DI freeze violation')
                Path(path).write_bytes(trial.read_bytes());Path(svg).write_bytes(preview.read_bytes())
                logs.append({'nodes':list(group),'plan':name,'before':old,'after':after,'moved_objects':sorted(moved),'boundary_edges':sorted(affected-set(internal)),
                             'outside_nodes_moved':0,'outside_paths_changed':0,'role_bands_moved':0});break
    return {'method':'atomic whole-block placement and joint ports; immutable outside anchors','accepted_blocks':len(logs),'trials':trials,
            'rejections':dict(reject),'blocks':logs,'before':before,'after':measures(read_bpmn(path)),'seconds':round(time.monotonic()-started,3)}


def geometry_digest(path):
    m=read_bpmn(path)
    value={'boxes':m[-2],'paths':m[-1],'labels':extract_labels(m[1])}
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def finalize_geometry(path,svg,max_passes=4):
    """Reach and verify a fixed point of measured label normalization."""
    original=read_bpmn(path);before=geometry_digest(path)
    for index in range(max_passes):
        previous=geometry_digest(path);place_labels(path,svg,preserve=True);now=read_bpmn(path)
        if now[-2]!=original[-2] or now[-1]!=original[-1]:raise ValueError('Finalization moved a shape or wire')
        if geometry_digest(path)==previous:
            return {'idempotent':True,'passes':index+1,'geometry_before':before,'geometry_after':previous,'shapes_moved':0,'paths_changed':0}
    raise ValueError('Measured label normalization did not reach a fixed point')
