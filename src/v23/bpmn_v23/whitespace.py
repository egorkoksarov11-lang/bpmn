"""Remove genuinely empty global strips without shrinking any visible object.

Protected intervals include measured text, shapes and parallel route channels.
A monotone axis map preserves orthogonality and crossing order; diagonal data
links are independently rechecked, and a failed pass is rolled back atomically.
"""
from pathlib import Path
import copy,tempfile
from bpmn_refkit.model import read_bpmn,TAG_TASK
from bpmn_universal.contract import NS,semantic_equality
from .di_geometry import update_geometry
from .freeze import equal
from .labels import place_labels
from .quality import contacts


def axis_map(intervals,minimum_gap=24):
    intervals=sorted(intervals);merged=[]
    for lo,hi in intervals:
        if merged and lo<=merged[-1][1]:merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
        else:merged.append((lo,hi))
    cuts=[(a[1],b[0],b[0]-a[1]-minimum_gap) for a,b in zip(merged,merged[1:]) if b[0]-a[1]>minimum_gap]
    def mapped(value):
        shift=0.
        for lo,hi,amount in cuts:
            if value>=hi:shift+=amount
            elif value>lo:shift+=amount*(value-lo)/(hi-lo)
        return round(value-shift,4)
    return mapped,cuts


def compact_whitespace(path,svg,source):
    from .pipeline import geometry
    reports=[]
    with tempfile.TemporaryDirectory(prefix='whitespace-',dir=Path(path).parent) as folder:
        trial=Path(folder)/'trial.bpmn';preview=trial.with_suffix('.svg')
        for axis in (0,1):
            state=read_bpmn(path);tree,root,_,plane,nodes,seq,assocs,docs,member,lanes,boxes,paths=state
            intervals=[];labels=[]
            for n,b in boxes.items():
                if n in nodes or n in docs:intervals.append((b[axis],b[axis]+b[axis+2]))
            for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
                n=b.getparent().getparent().get('bpmnElement')
                if n in nodes and nodes[n]['kind'] in TAG_TASK:continue
                r=tuple(float(b.get(k)) for k in ('x','y','width','height'));intervals.append((r[axis],r[axis]+r[axis+2]));labels.append(r)
            for ps in paths.values():
                for a,b in zip(ps,ps[1:]):
                    if abs(a[axis]-b[axis])<.01:intervals.append((a[axis]-8,a[axis]+8))
            if axis==0:
                intervals.extend((boxes[l][0],boxes[l][0]+56) for l in lanes)
            else:
                # Lane names are visible objects too: retain enough vertical
                # space for measured rotated captions, even in sparse bands.
                from .render import lane_caption
                for l,name in lanes.items():
                    x,y,w,h=boxes[l];required=next((v for v in range(100,int(h)+1,8) if not lane_caption(name,v)[2]),h)
                    intervals.append((y,y+min(required,h)))
            fn,cuts=axis_map(intervals)
            new={}
            for n,b in boxes.items():
                q=list(b);q[axis]=fn(b[axis])
                if n not in nodes and n not in docs:q[axis+2]=fn(b[axis]+b[axis+2])-q[axis]
                new[n]=tuple(q)
            new_paths={i:[(fn(x),y) if axis==0 else (x,fn(y)) for x,y in ps] for i,ps in paths.items()}
            # Crop trailing blank canvas separately from internal strip removal.
            visible=[b for n,b in new.items() if n in nodes or n in docs]
            right=max([b[0]+b[2] for b in visible]+[fn(b[0]+b[2]) if axis==0 else b[0]+b[2] for b in labels]+[x for ps in new_paths.values() for x,y in ps])+24
            for n,b in list(new.items()):
                if n not in nodes and n not in docs:new[n]=(b[0],b[1],max(56,right-b[0]),b[3])
            old_contacts=len(contacts(paths,{i:(u,v) for i,u,v,*_ in seq+assocs}))
            ct=copy.deepcopy(tree);cr=ct.getroot();cp=cr.xpath('.//bd:BPMNPlane',namespaces=NS)[0];update_geometry(cr,cp,new,new_paths)
            for b in cr.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
                key='x' if axis==0 else 'y';b.set(key,str(fn(float(b.get(key)))))
            ct.write(str(trial),encoding='utf-8',xml_declaration=True);lr=place_labels(trial,preview,preserve=True);g=geometry(trial)
            valid=(g['ambiguous_contacts']<=old_contacts and g['routing_safety_passed'] and g['edge_clearance_passed'] and not(g['label_collision_pairs'] or g['label_line_cuts'] or g['task_text_overflows'] or g['missing_named_flow_labels'] or g['excessive_bend_edges'] or lr['unplaced_labels'] or lr['rendering']['text_overflow_ids']))
            if valid and semantic_equality(source,trial) and equal(source,trial):
                Path(path).write_bytes(trial.read_bytes());Path(svg).write_bytes(preview.read_bytes());reports.append({'axis':axis,'status':'accepted','removed_span':sum(c[2] for c in cuts),'empty_strips':len(cuts)})
            else:reports.append({'axis':axis,'status':'rolled_back','reason':'independent geometry/text/freeze validation'})
    return {'method':'monotone empty-strip removal; fixed object dimensions; protected text and wire channels','passes':reports,'source_geometry_used':False}
