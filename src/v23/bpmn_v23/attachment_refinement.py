"""Move a document and its caption together, keeping all workflow geometry fixed."""
from pathlib import Path
import copy,tempfile,time
from lxml import etree as ET
from bpmn_refkit.model import read_bpmn,set_di
from bpmn_refkit.geometry import bbox_intersect_seg
from bpmn_universal.contract import NS,Q,BD,DC,semantic_equality
from .document_layout import owners_for,box_gap,straight_link,safe_link,attachment_metrics
from .quality import contacts,path_length
from .typography import text_layout
from .labels import place_labels
from .freeze import equal as di_equal
from .di_geometry import update_geometry as set_di


class AttachmentBackend:
    """Safe incremental use when an existing layout should retain its steps."""
    name='v23-local-information-attachments'
    preserve_labels=True
    def __init__(self,incumbent=None,seconds=12):self.incumbent=Path(incumbent) if incumbent else None;self.seconds=seconds
    def layout(self,source,output,svg):
        from .pipeline import geometry,validate_xml
        from .reference_layout import valid_geometry
        seed=self.incumbent or Path(source);validate_xml(seed)
        if not semantic_equality(source,seed) or not di_equal(source,seed):raise ValueError('Incumbent freeze violation')
        Path(output).write_bytes(seed.read_bytes());labels=place_labels(output,svg,preserve=True)
        if not valid_geometry(geometry(output),labels):raise ValueError('Attachment mode requires a verified layout')
        report=compact_attachments(output,svg,source,self.seconds)
        return {'backend':self.name,'local_attachment_moves':report,'selection':'only independently verified local moves; no workflow reconstruction','reference_target_met':False}


def compact_attachments(path,svg,source,seconds=12,fixed_owners=None):
    from .pipeline import geometry
    from .reference_layout import valid_geometry
    if Path(path).resolve()==Path(source).resolve():raise ValueError('Attachment result must be separate from source')
    # Shared typography is prepared once, so unrelated caption repairs do not
    # become an accidental side effect of the first accepted glyph move.
    original_bytes=Path(path).read_bytes();original_geometry=geometry(path)
    labels=place_labels(path,svg,preserve=True);prepared=geometry(path)
    if not valid_geometry(prepared,labels) or prepared['extent']['width']*prepared['extent']['height']>original_geometry['extent']['width']*original_geometry['extent']['height']+.1:
        Path(path).write_bytes(original_bytes)
    started=time.monotonic();initial=read_bpmn(path);sm=read_bpmn(source)
    owners=fixed_owners if fixed_owners is not None else owners_for(sm[4],sm[7],sm[6],sm[-2]);changes=[];trials=0
    before=attachment_metrics(initial[4],initial[7],initial[6],initial[-2],initial[-1],owners)
    with tempfile.TemporaryDirectory(prefix='attachment-moves-',dir=Path(path).parent) as folder:
        trial=Path(folder)/'trial.bpmn';preview=Path(folder)/'trial.svg'
        for d,owner in sorted(owners.items(),key=lambda p:(-before['anchor_gaps'][p[0]],p[0])):
            if time.monotonic()-started>=seconds:break
            tree,root,_,plane,nodes,seq,assocs,docs,member,lanes,boxes,paths=read_bpmn(path)
            x,y,dw,dh=boxes[d];a=boxes[owner];old_gap=box_gap(boxes[d],a)
            if old_gap<=22:continue
            uv={i:(u,v) for i,u,v,_ in seq+assocs};affected=[e for e in assocs if d in e[1:3]]
            unchanged={i:ps for i,ps in paths.items() if i not in {e[0] for e in affected}}
            old_contacts=len(contacts(paths,uv));g_before=geometry(path);area=g_before['extent']['width']*g_before['extent']['height']
            obstacles={n:b for n,b in boxes.items() if n in nodes or n in docs}
            other_labels=[]
            for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
                owner_id=b.getparent().getparent().get('bpmnElement')
                from bpmn_refkit.model import TAG_TASK
                if owner_id!=d and not(owner_id in nodes and nodes[owner_id]['kind'] in TAG_TASK):other_labels.append(tuple(float(b.get(k)) for k in ('x','y','width','height')))
            glyphs=[]
            for distance in (20,28,36):
                for delta in (0,-24,24,-48,48):
                    glyphs.extend([(a[0]+a[2]/2-dw/2+delta,a[1]-distance-dh,dw,dh),(a[0]+a[2]/2-dw/2+delta,a[1]+a[3]+distance,dw,dh),
                        (a[0]-distance-dw,a[1]+a[3]/2-dh/2+delta,dw,dh),(a[0]+a[2]+distance,a[1]+a[3]/2-dh/2+delta,dw,dh)])
            candidates=[]
            lane=boxes.get(member.get(owner));name=docs[d].get('name','')
            for glyph in set(glyphs):
                if box_gap(glyph,a)>=old_gap-.1:continue
                gx,gy,_,_=glyph
                if lane and not(gx>=lane[0]+56 and gy>=lane[1]+8 and gx+dw<=lane[0]+lane[2]-8 and gy+dh<=lane[1]+lane[3]-8):continue
                for size in (12,11,10):
                    for lw in (100,140,180):
                        lh=text_layout(name,lw,1000,(size,),2,1)['required_height']
                        for label in [(gx+dw+7,gy+dh/2-lh/2,lw,lh),(gx-lw-7,gy+dh/2-lh/2,lw,lh),(gx+dw/2-lw/2,gy+dh+7,lw,lh),(gx+dw/2-lw/2,gy-lh-7,lw,lh)]:
                            # Glyph and full caption are a local compound block.
                            if label[0]<(lane[0]+54 if lane else 0):continue
                            if any(box_gap(glyph,b)<8 or box_gap(label,b)<2 for n,b in obstacles.items() if n!=d):continue
                            if any(box_gap(label,b)<2 or box_gap(glyph,b)<2 for b in other_labels):continue
                            if any(bbox_intersect_seg(glyph,p,q,clearance=-8) or bbox_intersect_seg(label,p,q,clearance=-1) for ps in unchanged.values() for p,q in zip(ps,ps[1:])):continue
                            candidates.append((box_gap(glyph,a)+(12-size)*3,glyph,label))
            for _,glyph,label in sorted(candidates,key=lambda c:(c[0],c[1],c[2]))[:18]:
                if time.monotonic()-started>=seconds:break
                trials+=1;new_boxes={**boxes,d:glyph};new_obstacles={**obstacles,d:glyph};new_paths=dict(unchanged);safe=True
                for i,u,v,_ in affected:
                    ps=straight_link(u,v,new_boxes,nodes)
                    if path_length(ps)>path_length(paths[i])+.05 or not safe_link(i,ps,new_obstacles,uv,new_paths,[(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes],nodes):safe=False;break
                    new_paths[i]=ps
                if not safe or len(contacts(new_paths,uv))>old_contacts:continue
                ct=copy.deepcopy(tree);cr=ct.getroot();cp=cr.xpath('.//bd:BPMNPlane',namespaces=NS)[0];set_di(cr,cp,{d:glyph},new_paths)
                shape=cr.xpath('.//bd:BPMNShape[@bpmnElement=$id]',namespaces=NS,id=d)[0];lab=shape.find(Q(BD,'BPMNLabel'))
                if lab is None:lab=ET.SubElement(shape,Q(BD,'BPMNLabel'))
                bounds=lab.find(Q(DC,'Bounds'))
                if bounds is None:bounds=ET.SubElement(lab,Q(DC,'Bounds'))
                for k,v in zip(('x','y','width','height'),label):bounds.set(k,str(round(v,2)))
                ct.write(str(trial),encoding='utf-8',xml_declaration=True);labels=place_labels(trial,preview,preserve=True);g=geometry(trial)
                if valid_geometry(g,labels) and g['extent']['width']*g['extent']['height']<=area+.1 and semantic_equality(source,trial) and di_equal(source,trial):
                    Path(path).write_bytes(trial.read_bytes());Path(svg).write_bytes(preview.read_bytes());changes.append({'document':d,'fixed_owner':owner,'gap_before':old_gap,'gap_after':box_gap(glyph,a)});break
    final=read_bpmn(path)
    return {'changes':changes,'trials':trials,'seconds':round(time.monotonic()-started,3),'before':before,'after':attachment_metrics(final[4],final[7],final[6],final[-2],final[-1],owners),
        'sequence_nodes_and_waypoints_preserved':all(initial[-2][n]==final[-2][n] for n in initial[4]) and all(initial[-1][i]==final[-1][i] for i,_,_,_ in initial[5]),
        'guards':'no new contacts, no longer individual consumer link, no larger page, full text, strict geometry and XML freeze'}
