"""Pixel-measured external labels; one shared layout for saved DI and SVG."""
import math
from collections import defaultdict
from lxml import etree as ET
from bpmn_refkit.model import read_bpmn,TAG_GATE,TAG_EVENT
from bpmn_refkit.geometry import bbox_intersect_seg
from bpmn_universal.contract import NS,Q,BD,DC
from .typography import width,wrap
from .render import render


def overlap(a,b,gap=4):
    return min(a[0]+a[2]+gap,b[0]+b[2])-max(a[0]-gap,b[0])>0 and min(a[1]+a[3]+gap,b[1]+b[3])-max(a[1]-gap,b[1])>0


class SpatialIndex:
    """Broad phase for label boxes and orthogonal path segments."""
    def __init__(self,cell=128):self.cell=cell;self.cells=defaultdict(set);self.items=[]
    def keys(self,rect):
        x,y,w,h=rect
        for i in range(math.floor(x/self.cell),math.floor((x+w)/self.cell)+1):
            for j in range(math.floor(y/self.cell),math.floor((y+h)/self.cell)+1):yield (i,j)
    def add(self,rect,item):
        idx=len(self.items);self.items.append(item)
        for key in self.keys(rect):self.cells[key].add(idx)
    def query(self,rect):
        indices=set()
        for key in self.keys(rect):indices.update(self.cells.get(key,()))
        return (self.items[i] for i in sorted(indices))

def place_labels(path,svg,preserve=False):
    if preserve:
        from .responsive_labels import place_responsive_labels
        return place_responsive_labels(path,svg)
    tree,root,_,_,nodes,seq,_,docs,_,lanenames,boxes,paths=read_bpmn(path)
    names={**{n:o.get('name','') for n,o in nodes.items()},**{n:o.get('name','') for n,o in docs.items()},**{i:name for i,_,_,name in seq}}
    shapes={s.get('bpmnElement'):s for s in root.xpath('.//bd:BPMNShape',namespaces=NS)}
    # External labels for every displayed event/gateway/document, including names
    # that older preview code silently truncated.
    for owner,shape in shapes.items():
        external=owner in docs or owner in nodes and nodes[owner]['kind'] in TAG_GATE|TAG_EVENT
        if external and names.get(owner) and shape.find(Q(BD,'BPMNLabel')) is None:
            lab=ET.SubElement(shape,Q(BD,'BPMNLabel'));x,y,w,h=boxes[owner]
            ET.SubElement(lab,Q(DC,'Bounds'),x=str(x+w/2-70),y=str(y+h+10),width='140',height='24')
    occupied=[b for n,b in boxes.items() if n in nodes or n in docs]
    shape_index=SpatialIndex();segment_index=SpatialIndex()
    for b in occupied:shape_index.add(b,b)
    for points in paths.values():
        for a,c in zip(points,points[1:]):
            segment_index.add((min(a[0],c[0]),min(a[1],c[1]),abs(a[0]-c[0]),abs(a[1]-c[1])),(a,c))
    entries=[]
    for label in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
        owner=label.getparent().getparent().get('bpmnElement')
        from bpmn_refkit.model import TAG_TASK
        if owner in nodes and nodes[owner]['kind'] in TAG_TASK:continue
        if not names.get(owner):continue
        old=tuple(float(label.get(k)) for k in ('x','y','width','height'))
        w=min(220,max(32,math.ceil(width(names[owner],12))+10))
        lines=wrap(names[owner],w-8,12);h=len(lines)*17+6
        x=old[0]+old[2]/2-w/2;y=old[1]
        entries.append((0 if owner in nodes else 1 if owner in docs else 2,owner,label,(x,y,w,h)))
    entries.sort(key=lambda item:(item[0],-item[3][2]*item[3][3],item[1]))
    minx=min([boxes[l][0]+54 for l in lanenames if l in boxes] or [40])
    unplaced=[];distances=[];owner_distances=[]
    for _,owner,label,(x,y,w,h) in entries:
        candidates=[(max(minx,x),max(55,y),w,h)]
        for r in range(12,361,12):
            for dx,dy in ((0,-r),(0,r),(-r,0),(r,0),(-r,-r),(r,-r),(-r,r),(r,r)):
                candidates.append((x+dx,y+dy,w,h))
        # These additional positions escape dense local intersections; their
        # displacement is reported, never hidden behind a zero-overlap claim.
        candidates.extend((max(minx,x+dx),max(55,y+dy),w,h) for dy in range(-360,361,24) for dx in range(-360,361,24))
        if owner in paths:
            for a,c in zip(paths[owner],paths[owner][1:]):
                for fraction in (.25,.5,.75):
                    cx=a[0]+(c[0]-a[0])*fraction;cy=a[1]+(c[1]-a[1])*fraction
                    candidates.extend([(cx-w/2,cy-h-7,w,h),(cx-w/2,cy+7,w,h),(cx+7,cy-h/2,w,h),(cx-w-7,cy-h/2,w,h)])
        if owner in paths:
            for alternate_width in sorted({max(72,round(w*.75)),max(72,round(w*.5))}):
                alternate_height=len(wrap(names[owner],alternate_width-8,12))*17+6
                for a,c in zip(paths[owner],paths[owner][1:]):
                    for fraction in (.15,.25,.4,.5,.6,.75,.85):
                        cx=a[0]+(c[0]-a[0])*fraction;cy=a[1]+(c[1]-a[1])*fraction
                        candidates.extend([(cx-alternate_width/2,cy-alternate_height-7,alternate_width,alternate_height),
                                           (cx-alternate_width/2,cy+7,alternate_width,alternate_height),
                                           (cx+7,cy-alternate_height/2,alternate_width,alternate_height),
                                           (cx-alternate_width-7,cy-alternate_height/2,alternate_width,alternate_height)])
        if owner in boxes:
            ox,oy,ow,oh=boxes[owner]
            for alternate_width in sorted({max(88,round(w*.8)),max(88,round(w*.6))}):
                alternate_height=len(wrap(names[owner],alternate_width-8,12))*17+6
                for delta in range(-120,121,12):
                    candidates.extend([(ox+ow/2-alternate_width/2+delta,oy-alternate_height-7,alternate_width,alternate_height),
                                       (ox+ow/2-alternate_width/2+delta,oy+oh+7,alternate_width,alternate_height),
                                       (ox+ow+7,oy+oh/2-alternate_height/2+delta,alternate_width,alternate_height),
                                       (ox-alternate_width-7,oy+oh/2-alternate_height/2+delta,alternate_width,alternate_height)])
        def owner_gap(b):
            targets=[(min(a[0],c[0]),min(a[1],c[1]),abs(a[0]-c[0]),abs(a[1]-c[1])) for a,c in zip(paths[owner],paths[owner][1:])] if owner in paths else [boxes[owner]] if owner in boxes else []
            return min((math.hypot(max(t[0]-b[0]-b[2],b[0]-t[0]-t[2],0),max(t[1]-b[1]-b[3],b[1]-t[1]-t[3],0)) for t in targets),default=0)
        candidates=sorted(set(candidates),key=lambda b:((owner_gap(b)-7)**2*25+((b[0]-x)**2+(b[1]-y)**2)*.01+abs(b[2]-w)*.1+max(0,b[3]-h)*.3,b[1],b[0]))
        def valid(b):
            x,y,w,h=b;query=(x-4,y-4,w+8,h+8)
            return x>=minx and y>=55 and not any(overlap(b,o) for o in shape_index.query(query)) and not any(bbox_intersect_seg(b,a,c,clearance=-3) for a,c in segment_index.query(query))
        chosen=next((b for b in candidates if valid(b)),None)
        if chosen is None:unplaced.append(owner);chosen=(x,y,w,h)
        for k,v in zip(('x','y','width','height'),chosen):label.set(k,str(round(v,2)))
        owner_distances.append({'id':owner,'distance':round(owner_gap(chosen),2)})
        distances.append({'id':owner,'distance':round(math.hypot(chosen[0]-x,chosen[1]-y),2)})
        occupied.append(chosen);shape_index.add(chosen,chosen)
    tree.write(str(path),encoding='utf-8',xml_declaration=True)
    rendering=render(path,svg)
    return {'unplaced_labels':unplaced,'external_labels':len(entries),'large_displacements':[d for d in distances if d['distance']>100],'distant_from_owner':[d for d in owner_distances if d['distance']>48],'rendering':rendering}
