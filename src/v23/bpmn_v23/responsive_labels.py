"""Keep valid author captions; fit full names locally without distant fallbacks."""
import math
from lxml import etree as ET
from bpmn_refkit.model import read_bpmn,TAG_TASK,TAG_GATE,TAG_EVENT
from bpmn_refkit.geometry import bbox_intersect_seg
from bpmn_universal.contract import NS,Q,BD,DC
from .typography import label_layout,width,text_layout
from .render import render
from .contours import label_hits_shape


def gap(a,b):
    return math.hypot(max(a[0]-b[0]-b[2],b[0]-a[0]-a[2],0),max(a[1]-b[1]-b[3],b[1]-a[1]-a[3],0))


def place_responsive_labels(path,svg):
    from .labels import SpatialIndex,overlap
    tree,root,_,_,nodes,seq,_,docs,_,lanes,boxes,paths=read_bpmn(path)
    names={**{n:o.get('name','') for n,o in (nodes|docs).items()},**{i:name for i,_,_,name in seq}}
    for shape in root.xpath('.//bd:BPMNShape',namespaces=NS):
        owner=shape.get('bpmnElement')
        if names.get(owner) and (owner in docs or owner in nodes and nodes[owner]['kind'] in TAG_GATE|TAG_EVENT) and shape.find(Q(BD,'BPMNLabel')) is None:
            x,y,w,h=boxes[owner];lab=ET.SubElement(shape,Q(BD,'BPMNLabel'))
            ET.SubElement(lab,Q(DC,'Bounds'),x=str(x+w/2-60),y=str(y+h+7),width='120',height='36')
    for edge in root.xpath('.//bd:BPMNEdge',namespaces=NS):
        owner=edge.get('bpmnElement')
        if names.get(owner) and edge.find(Q(BD,'BPMNLabel')) is None:
            ps=paths[owner];a,b=max(zip(ps,ps[1:]),key=lambda pair:math.dist(*pair));cx=(a[0]+b[0])/2;cy=(a[1]+b[1])/2
            lab=ET.SubElement(edge,Q(BD,'BPMNLabel'));ET.SubElement(lab,Q(DC,'Bounds'),x=str(cx-40),y=str(cy+7),width='80',height='24')
    occupied=SpatialIndex();segments=SpatialIndex();entries=[]
    for n,b in boxes.items():
        if n in nodes or n in docs:occupied.add(b,(nodes.get(n,{}).get('kind',''),b))
    for ps in paths.values():
        for a,b in zip(ps,ps[1:]):segments.add((min(a[0],b[0]),min(a[1],b[1]),abs(a[0]-b[0]),abs(a[1]-b[1])),(a,b))
    minx=min((boxes[l][0]+54 for l in lanes),default=0)
    original_rects=list(boxes.values())+[tuple(float(b.get(k)) for k in ('x','y','width','height')) for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS)]
    original_points=[p for ps in paths.values() for p in ps]
    miny=min([b[1] for b in original_rects]+[p[1] for p in original_points])
    maxx=max([b[0]+b[2] for b in original_rects]+[p[0] for p in original_points]);maxy=max([b[1]+b[3] for b in original_rects]+[p[1] for p in original_points])
    def valid(b):
        x,y,w,h=b;q=(x-3,y-3,w+6,h+6)
        # Measured caption bounds already include 2px horizontal ink padding.
        # Use the same geometric collision criterion as the independent audit.
        return x>=minx and y>=miny-.01 and x+w<=maxx+.01 and y+h<=maxy+.01 and not any(label_hits_shape(b,o,kind) for kind,o in occupied.query(q)) and not any(bbox_intersect_seg(b,a,c,clearance=1) for a,c in segments.query(q))
    for label in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
        owner=label.getparent().getparent().get('bpmnElement')
        if not names.get(owner) or owner in nodes and nodes[owner]['kind'] in TAG_TASK:continue
        old=tuple(float(label.get(k)) for k in ('x','y','width','height'))
        layout=label_layout(names[owner],old)
        if layout['fits']:
            # Author Bounds often include empty padding. Keep the text centre,
            # but test the actual caption envelope instead of that whitespace.
            nw=min(old[2],math.ceil(max(width(line,layout['font_size']) for line in layout['lines']))+4)
            nh=min(old[3],layout['required_height']);tight=(old[0]+(old[2]-nw)/2,old[1]+(old[3]-nh)/2,nw,nh)
            if label_layout(names[owner],tight)['fits']:
                old=tight
                for k,v in zip(('x','y','width','height'),old):label.set(k,str(round(v,2)))
        entries.append((owner,label,old))
    # Named shapes and documents get their planned caption bays before short
    # flow labels. XML DI element ordering must not decide label ownership.
    entries.sort(key=lambda item:(0 if item[0] in nodes else 1 if item[0] in docs else 2,-len(names[item[0]]),item[0]))
    # Reserve all already-valid captions before repairing any conflicting ones.
    pending=[];far_valid=[];kept=[];unplaced=[];distances=[]
    def targets_for(owner):
        return [boxes[owner]] if owner in boxes else [(min(a[0],b[0]),min(a[1],b[1]),abs(a[0]-b[0]),abs(a[1]-b[1])) for a,b in zip(paths.get(owner,[]),paths.get(owner,[])[1:])]
    for owner,label,old in entries:
        if label_layout(names[owner],old)['fits'] and valid(old):
            occupied.add(old,('',old));kept.append(owner)
            if min((gap(old,t) for t in targets_for(owner)),default=0)>32:far_valid.append((owner,label,old))
        else:pending.append((owner,label,old))
    originally_valid={owner for owner,_,_ in far_valid}
    # Long captions have fewer free bays. Place them before short yes/no and
    # gateway captions, which can fit into smaller remaining spaces.
    pending.sort(key=lambda item:(-len(names[item[0]]),item[0]))
    for owner,label,old in pending+far_valid:
        name=names[owner];candidates=[]
        targets=targets_for(owner)
        anchors=targets
        if owner in paths:
            # A busy midpoint must not hide clear bays along a long segment.
            anchors=targets+[(x+w*f,y+h*f,0,0) for x,y,w,h in targets for f in (.1,.25,.75,.9)]
        for size in (12,11,10):
            for w in sorted({max(36,old[2]),80,110,140,180,220}):
                fit=text_layout(name,w,1000,(size,),2,1);h=fit['required_height']
                # Tighten unused vertical whitespace, preserving the old centre.
                candidates.append((old[0]+(old[2]-w)/2,old[1]+(old[3]-h)/2,w,h,size))
                for x,y,tw,th in anchors:
                    for delta in (0,-12,12,-24,24,-36,36,-48,48,-64,64):
                        candidates.extend([(x+tw/2-w/2+delta,y-h-7,w,h,size),(x+tw/2-w/2+delta,y+th+7,w,h,size),(x+tw+7,y+th/2-h/2+delta,w,h,size),(x-w-7,y+th/2-h/2+delta,w,h,size)])
        def distance(b):return min((gap(b,t) for t in targets),default=0)
        # Captions remain local to their glyph or their own flow segment.
        candidates=sorted(set(candidates),key=lambda c:(abs(distance(c)-7)*5+(12-c[4])*12+math.dist(c[:2],old[:2])*.06,c))
        chosen=next((c[:4] for c in candidates if distance(c)<=32 and valid(c[:4]) and label_layout(name,c[:4])['fits']),None)
        if chosen is None:
            if owner not in originally_valid:unplaced.append(owner)
            chosen=old
        for k,v in zip(('x','y','width','height'),chosen):label.set(k,str(round(v,2)))
        occupied.add(chosen,('',chosen));distances.append({'id':owner,'distance':round(distance(chosen),2)})
    tree.write(str(path),encoding='utf-8',xml_declaration=True)
    all_distances=[{'id':owner,'distance':round(min((gap(tuple(float(label.get(k)) for k in ('x','y','width','height')),t) for t in targets_for(owner)),default=0),2)} for owner,label,_ in entries]
    return {'unplaced_labels':unplaced,'external_labels':len(entries),'preserved_labels':kept,'large_displacements':[],
            'distant_from_owner':[d for d in all_distances if d['distance']>32],'rendering':render(path,svg),'policy':'preserve valid measured bounds; full names; local repair within 32 units; unresolved safe distant captions explicitly reported'}
