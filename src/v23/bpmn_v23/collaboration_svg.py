"""SVG pool frames and message-flow notation over the saved collaboration DI."""
import copy
from pathlib import Path
import tempfile
from lxml import etree as ET
from bpmn_universal.contract import B,BD,DC,NS,Q,parse
from .collaboration import extract,write,boxes_paths
from .render import render,SVG,lane_caption
from .typography import label_layout


def render_collaboration(path,svg_path):
    root=parse(path);boxes,paths=boxes_paths(root)
    bounds=list(boxes.values())+[tuple(float(b.get(k)) for k in ('x','y','width','height')) for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS)]
    points=[p for ps in paths.values() for p in ps]
    x0=min([b[0] for b in bounds]+[p[0] for p in points])-25;y0=min([b[1] for b in bounds]+[p[1] for p in points])-40
    x1=max([b[0]+b[2] for b in bounds]+[p[0] for p in points])+25;y1=max([b[1]+b[3] for b in bounds]+[p[1] for p in points])+25
    svg=ET.Element(Q(SVG,'svg'),nsmap={None:SVG},viewBox=f'{x0} {y0} {x1-x0} {y1-y0}',width=str(x1-x0),height=str(y1-y0),role='img')
    def add(parent,tag,**attrs):return ET.SubElement(parent,Q(SVG,tag),{k.replace('_','-'):str(v) for k,v in attrs.items()})
    c=root.find(Q(B,'collaboration'));title=add(svg,'title');title.text=c.get('name') or 'Взаимодействие процессов'
    add(svg,'rect',x=x0,y=y0,width=x1-x0,height=y1-y0,fill='white')
    defs=add(svg,'defs')
    marker=add(defs,'marker',id='message-end',viewBox='0 0 10 10',refX=9,refY=5,markerWidth=9,markerHeight=9,orient='auto',markerUnits='userSpaceOnUse')
    add(marker,'path',d='M1 1 L9 5 L1 9 Z',fill='white',stroke='#5e4e85',stroke_width=1.2)
    start=add(defs,'marker',id='message-start',viewBox='0 0 10 10',refX=5,refY=5,markerWidth=8,markerHeight=8,orient='auto',markerUnits='userSpaceOnUse')
    add(start,'circle',cx=5,cy=5,r=3,fill='white',stroke='#5e4e85',stroke_width=1.2)
    for part in c.findall(Q(B,'participant')):
        x,y,w,h=boxes[part.get('id')];g=add(svg,'g',data_bpmn_id=part.get('id'))
        add(g,'rect',x=x,y=y,width=w,height=h,fill='#f8fafc',stroke='#475569',stroke_width=1.8)
        add(g,'line',x1=x+36,y1=y,x2=x+36,y2=y+h,stroke='#475569')
        # Pool name has a separate 36px header; shrink/wrap as measured text.
        lines,size,overflow=lane_caption(part.get('name',''),h)
        if overflow or len(lines)*(size+1)>34:raise ValueError('Pool title does not fit: '+part.get('id'))
        for i,line in enumerate(lines):
            tx=x+18+(i-(len(lines)-1)/2)*(size+1);ty=y+h/2
            add(g,'text',x=tx,y=ty,transform=f'rotate(-90 {tx} {ty})',font_size=size,text_anchor='middle',dominant_baseline='middle',fill='#23384e').text=line
    with tempfile.TemporaryDirectory(prefix='collaboration-svg-') as directory:
        for i,process in enumerate(root.findall(Q(B,'process'))):
            model=Path(directory)/f'{i}.bpmn';preview=model.with_suffix('.svg');write(extract(root,process.get('id')),model)
            report=render(model,preview)
            if report['text_overflow_ids']:raise ValueError('Text overflow in pool: '+str(report['text_overflow_ids']))
            part_svg=ET.parse(str(preview)).getroot();prefix=f'p{i}-'
            for element in part_svg.iter():
                if element.get('id'):element.set('id',prefix+element.get('id'))
                for attr,value in list(element.attrib.items()):
                    if 'url(#' in value:element.set(attr,value.replace('url(#','url(#'+prefix))
            for element in part_svg:
                if element.tag==Q(SVG,'defs'):
                    for child in element:defs.append(copy.deepcopy(child))
                elif element.get('data-bpmn-id') or element.get('data-label-for'):svg.append(copy.deepcopy(element))
    for message in c.findall(Q(B,'messageFlow')):
        eid=message.get('id');g=add(svg,'g',data_bpmn_id=eid)
        add(g,'title').text=message.get('name','')
        add(g,'polyline',points=' '.join(f'{x},{y}' for x,y in paths[eid]),fill='none',stroke='#5e4e85',stroke_width=1.5,stroke_dasharray='7 5',marker_start='url(#message-start)',marker_end='url(#message-end)')
        label=root.xpath('.//bd:BPMNEdge[@bpmnElement=$id]/bd:BPMNLabel/dc:Bounds',namespaces=NS,id=eid)
        if label and message.get('name'):
            x,y,w,h=tuple(float(label[0].get(k)) for k in ('x','y','width','height'))
            layout=label_layout(message.get('name'),(x,y,w,h))
            if not layout['fits']:raise ValueError('Message label overflow: '+eid)
            add(g,'rect',x=x,y=y,width=w,height=h,fill='white',fill_opacity='.96',rx=3)
            for line,baseline in zip(layout['lines'],layout['baselines']):
                add(g,'text',x=x+w/2,y=y+baseline,font_size=layout['font_size'],text_anchor='middle',fill='#5e4e85').text=line
    ET.ElementTree(svg).write(str(svg_path),encoding='utf-8',xml_declaration=True)
