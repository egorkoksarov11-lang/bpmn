"""SVG preview driven by saved DI and the same measured typography as validation."""
import base64,math
from lxml import etree as ET
from bpmn_refkit.model import read_bpmn,TAG_TASK,TAG_GATE,TAG_EVENT
from bpmn_universal.contract import NS,Q,B,BD,DC
from .typography import FONT,wrap,width,TASK_FONT,TASK_LINE_HEIGHT
SVG='http://www.w3.org/2000/svg'


def lane_caption(name,height):
    """Keep the full rotated role name inside the 48px lane header."""
    for size in (14,13,12,11,10):
        lines=wrap(name,max(1,height-20),size)
        if len(lines)*(size+1)<=44:return lines,size,False
    return lines,10,True


def render(path,svg_path):
    _,root,process,plane,nodes,seq,assocs,docs,_,lane_names,boxes,paths=read_bpmn(path)
    labels={}
    for elem in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
        owner=elem.getparent().getparent().get('bpmnElement');labels[owner]=tuple(float(elem.get(k)) for k in ('x','y','width','height'))
    extents=list(boxes.values())+list(labels.values())
    points=[p for ps in paths.values() for p in ps]
    minx=min([b[0] for b in extents]+[p[0] for p in points])-25
    miny=min([0]+[b[1] for b in extents]+[p[1] for p in points])-10
    maxx=max([b[0]+b[2] for b in extents]+[p[0] for p in points])+25
    maxy=max([b[1]+b[3] for b in extents]+[p[1] for p in points])+25
    svg=ET.Element(Q(SVG,'svg'),nsmap={None:SVG},viewBox=f'{minx} {miny} {maxx-minx} {maxy-miny}',width=str(maxx-minx),height=str(maxy-miny),role='img')
    def add(parent,tag,**attrs):return ET.SubElement(parent,Q(SVG,tag),{k.replace('_','-'):str(v) for k,v in attrs.items()})
    title=add(svg,'title');title.text=process.get('name') or 'BPMN process'
    defs=add(svg,'defs');style=add(defs,'style')
    style.text="@font-face{font-family:'Open Sans';src:url(data:font/ttf;base64,"+base64.b64encode(FONT.read_bytes()).decode()+")} text{font-family:'Open Sans',sans-serif}"
    for mid,colour in [('flow-arrow','#34485c'),('document-arrow','#517b96')]:
        marker=add(defs,'marker',id=mid,viewBox='0 0 10 10',refX=9,refY=5,markerWidth=8,markerHeight=8,orient='auto-start-reverse',markerUnits='userSpaceOnUse')
        add(marker,'path',d='M1 1 L9 5 L1 9',fill='none',stroke=colour,stroke_width=1.5)
    add(svg,'rect',x=minx,y=miny,width=maxx-minx,height=maxy-miny,fill='white')
    text=add(svg,'text',x=minx+25,y=28,font_size=18,fill='#243a4d');text.text=title.text
    text_overflow=[];lane_fonts={}
    for i,(lane,name) in enumerate(lane_names.items()):
        if lane not in boxes:continue
        x,y,w,h=boxes[lane];group=add(svg,'g',data_bpmn_id=lane)
        add(group,'rect',x=x,y=y,width=w,height=h,fill=['#f1f6fc','#fff','#f0faf5','#fff7ed'][i%4],stroke='#c2d0dc',stroke_width=1)
        add(group,'line',x1=x+48,y1=y,x2=x+48,y2=y+h,stroke='#c2d0dc')
        lines,size,overflow=lane_caption(name,h);lane_fonts[lane]=size
        if overflow:text_overflow.append('lane:'+lane)
        for j,line in enumerate(lines):
            gap=size+1
            t=add(group,'text',x=x+24+(j-(len(lines)-1)/2)*gap,y=y+h/2,transform=f'rotate(-90 {x+24+(j-(len(lines)-1)/2)*gap} {y+h/2})',text_anchor='middle',dominant_baseline='middle',font_size=size,fill='#30465a');t.text=line
    for eid,u,v,direction in assocs:
        group=add(svg,'g',data_bpmn_id=eid)
        attrs=dict(points=' '.join(f'{x},{y}' for x,y in paths[eid]),fill='none',stroke='#517b96',stroke_width=1.2,stroke_dasharray='4 4')
        if direction in ('One','Both','Input','Output'):attrs['marker_end']='url(#document-arrow)'
        if direction=='Both':attrs['marker_start']='url(#document-arrow)'
        add(group,'polyline',**attrs)
    for eid,u,v,name in seq:
        group=add(svg,'g',data_bpmn_id=eid)
        add(group,'polyline',points=' '.join(f'{x},{y}' for x,y in paths[eid]),fill='none',stroke='#34485c',stroke_width=1.6,marker_end='url(#flow-arrow)')
        owner=root.xpath('//*[@id=$id]',id=u)
        if owner and owner[0].get('default')==eid:
            a,b=paths[eid][:2];dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
            if length:
                cx=a[0]+dx/length*12;cy=a[1]+dy/length*12
                add(group,'line',x1=cx-dy/length*5-dx/length*3,y1=cy+dx/length*5-dy/length*3,x2=cx+dy/length*5+dx/length*3,y2=cy-dx/length*5+dy/length*3,stroke='#34485c',stroke_width=1.4)
    for nid,o in nodes.items():
        x,y,w,h=boxes[nid];kind=o['kind'];group=add(svg,'g',data_bpmn_id=nid)
        add(group,'title').text=o.get('name','')
        if kind in TAG_GATE:
            cx=x+w/2;cy=y+h/2
            add(group,'polygon',points=f'{cx},{y} {x+w},{cy} {cx},{y+h} {x},{cy}',fill='#fffaf0',stroke='#997432',stroke_width=1.6)
            if kind=='inclusiveGateway':add(group,'circle',cx=cx,cy=cy,r=min(w,h)*.22,fill='none',stroke='#997432',stroke_width=2)
            elif kind=='eventBasedGateway':
                add(group,'circle',cx=cx,cy=cy,r=min(w,h)*.27,fill='none',stroke='#997432')
                pts=' '.join(f'{cx+min(w,h)*.17*math.sin(i*2*math.pi/5)},{cy-min(w,h)*.17*math.cos(i*2*math.pi/5)}' for i in range(5));add(group,'polygon',points=pts,fill='none',stroke='#997432')
            else:
                symbol='+' if kind=='parallelGateway' else '*' if kind=='complexGateway' else '×'
                t=add(group,'text',x=cx,y=cy+7,text_anchor='middle',font_size=25,fill='#997432');t.text=symbol
        elif kind in TAG_EVENT:
            colour='#3d8063' if kind=='startEvent' else '#9d4c4c' if kind=='endEvent' else '#586f80'
            add(group,'ellipse',cx=x+w/2,cy=y+h/2,rx=w/2,ry=h/2,fill='white',stroke=colour,stroke_width=3 if kind=='endEvent' else 1.5)
            if kind.startswith('intermediate'):add(group,'ellipse',cx=x+w/2,cy=y+h/2,rx=w/2-3,ry=h/2-3,fill='none',stroke=colour)
            element=root.xpath('//*[@id=$id]',id=nid)[0]
            if element.find(Q(B,'timerEventDefinition')) is not None:
                add(group,'circle',cx=x+w/2,cy=y+h/2,r=min(w,h)*.29,fill='none',stroke=colour)
                add(group,'path',d=f'M{x+w/2} {y+h*.28} V{y+h/2} L{x+w*.68} {y+h*.6}',fill='none',stroke=colour)
            elif element.find(Q(B,'messageEventDefinition')) is not None:
                add(group,'rect',x=x+w*.22,y=y+h*.32,width=w*.56,height=h*.36,fill='none',stroke=colour)
                add(group,'path',d=f'M{x+w*.22} {y+h*.32} L{x+w/2} {y+h*.52} L{x+w*.78} {y+h*.32}',fill='none',stroke=colour)
        else:
            add(group,'rect',x=x,y=y,width=w,height=h,rx=10,fill='white',stroke='#344f65',stroke_width=3 if kind=='callActivity' else 1.5)
            # Preserve subprocess/call activity type visually; no invented BPMN logic.
            if kind in ('callActivity','subProcess'):
                add(group,'rect',x=x+w/2-6,y=y+h-15,width=12,height=12,fill='white',stroke='#344f65')
                add(group,'path',d=f'M{x+w/2-4} {y+h-9} H{x+w/2+4} M{x+w/2} {y+h-13} V{y+h-5}',stroke='#344f65')
            lines=wrap(o.get('name',''),max(1,w-24),TASK_FONT);lineh=TASK_LINE_HEIGHT
            available=h-24-(14 if kind in ('callActivity','subProcess') else 0)
            if len(lines)*lineh>available:text_overflow.append(nid)
            for i,line in enumerate(lines):
                t=add(group,'text',x=x+w/2,y=y+h/2-(len(lines)-1)*lineh/2+i*lineh+4-(6 if kind in ('callActivity','subProcess') else 0),text_anchor='middle',font_size=TASK_FONT,fill='#24394b');t.text=line
    for nid,o in docs.items():
        x,y,w,h=boxes[nid];group=add(svg,'g',data_bpmn_id=nid)
        if o['kind']=='dataStoreReference':
            add(group,'path',d=f'M{x} {y+7} C{x} {y-3} {x+w} {y-3} {x+w} {y+7} V{y+h-7} C{x+w} {y+h+3} {x} {y+h+3} {x} {y+h-7} Z',fill='white',stroke='#517b96',stroke_width=1.3)
            add(group,'ellipse',cx=x+w/2,cy=y+7,rx=w/2,ry=7,fill='white',stroke='#517b96',stroke_width=1.3)
        else:
            add(group,'path',d=f'M{x} {y} H{x+w-10} L{x+w} {y+10} V{y+h} H{x} Z M{x+w-10} {y} V{y+10} H{x+w}',fill='white',stroke='#517b96',stroke_width=1.3)
    lookup={**{n:o.get('name','') for n,o in nodes.items()},**{n:o.get('name','') for n,o in docs.items()},**{i:name for i,_,_,name in seq}}
    for owner,(x,y,w,h) in labels.items():
        group=add(svg,'g',data_label_for=owner)
        if owner not in lookup:continue
        size=12;lines=wrap(lookup[owner],max(1,w-8),size)
        if len(lines)*17>h:text_overflow.append('label:'+owner)
        add(group,'rect',x=x,y=y,width=w,height=h,fill='white',fill_opacity='.96',rx=3)
        for i,line in enumerate(lines):
            t=add(group,'text',x=x+w/2,y=y+13+i*17,text_anchor='middle',font_size=size,fill='#6d5126' if owner not in nodes and owner not in docs else '#304b60');t.text=line
    ET.ElementTree(svg).write(str(svg_path),encoding='utf-8',xml_declaration=True)
    return {'font':'Open Sans bundled','task_font_size':TASK_FONT,'label_font_size':12,'lane_font_sizes':lane_fonts,'text_overflow_ids':text_overflow}
