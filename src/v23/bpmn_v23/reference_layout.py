"""Experimental human-reference refinement with independently checked fallbacks.

Preserving a supplied good layout is a stability check, not evidence of graph
reconstruction. Separate noisy-DI trials are required for that claim.
"""
from pathlib import Path
import tempfile,time
from bpmn_refkit.model import read_bpmn,set_di
from bpmn_refkit.geometry import compress
from bpmn_universal.contract import NS,semantic_equality
from bpmn_universal.cli import deadline
from .adaptive_layout import AdaptiveBackend
from .axis_layout import AxisBackend
from .attachment_axes import attachment_axes
from .labels import place_labels
from .document_layout import refine_links,attachment_metrics,straight_link,safe_link
from .clearance import safe_poly
from .contours import attach,bounding_ports
from .router import route_graph,overlapping
from .freeze import equal as di_equal
from .quality import score
from .di_geometry import update_geometry as set_di


def valid_geometry(g,labels):
    return not (labels['unplaced_labels'] or labels['rendering']['text_overflow_ids'] or g['label_collision_pairs'] or g['label_line_cuts'] or g['excessive_bend_edges'] or g['missing_named_flow_labels']) and g['routing_safety_passed'] and g['edge_clearance_passed']


def prepare_current_geometry(source,target,svg,seconds):
    """Retain safe source corridors, repair unsafe ones, keep captions nearby."""
    from .pipeline import geometry
    from bpmn_universal.contract import DC
    tree,root,_,plane,nodes,seq,assocs,docs,member,lanes,boxes,paths=read_bpmn(source)
    uv={i:(u,v) for i,u,v,_ in seq+assocs};ob={n:b for n,b in boxes.items() if n in nodes or n in docs}
    # Uniform content translation reserves the full role header, without
    # changing any relative step/attachment spacing or any route length.
    shift=max([0]+[boxes[member[n]][0]+56-b[0] for n,b in ob.items() if n in member])
    if shift:
        boxes={n:(x+shift,y,w,h) if n in ob else (x,y,w+shift,h) for n,(x,y,w,h) in boxes.items()}
        paths={i:[(x+shift,y) for x,y in ps] for i,ps in paths.items()}
        for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):b.set('x',str(float(b.get('x'))+shift))
    set_di(root,plane,boxes,paths);tree.write(str(target),encoding='utf-8',xml_declaration=True)
    place_labels(target,svg,preserve=True)
    tree,root,_,plane,nodes,seq,assocs,docs,member,lanes,boxes,paths=read_bpmn(target)
    headers=[(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes]
    ob={n:b for n,b in boxes.items() if n in nodes or n in docs};routing={**ob,**{f'__header_{i}':b for i,b in enumerate(headers)}}
    from .typography import label_layout
    named_flows={i:name for i,_,_,name in seq if name}
    for bounds in root.xpath('.//bd:BPMNEdge/bd:BPMNLabel/dc:Bounds',namespaces=NS):
        owner=bounds.getparent().getparent().get('bpmnElement');b=tuple(float(bounds.get(k)) for k in ('x','y','width','height'))
        if owner in named_flows and label_layout(named_flows[owner],b)['fits']:routing['__text_'+owner]=b
    fixed={};bounded=bounding_ports(paths,uv,boxes,nodes)
    for i,u,v,_ in seq:
        p=compress(bounded[i])
        if len(p)>=2 and all(abs(a[0]-b[0])<.01 or abs(a[1]-b[1])<.01 for a,b in zip(p,p[1:])) and safe_poly(i,p,routing,uv) and not overlapping(p,fixed):fixed[i]=p
    for i,u,v,_ in assocs:
        p=paths[i]
        if len(p)!=2:p=straight_link(u,v,boxes,nodes)
        else:
            from .contours import on_contour
            if not all(on_contour(p[k],boxes[n],nodes.get(n,{}).get('kind','')) for k,n in ((0,u),(-1,v))):p=straight_link(u,v,boxes,nodes)
        if safe_link(i,p,ob,uv,fixed,headers,nodes):fixed[i]=p
    with deadline(seconds):
        paths,_=route_graph(routing,nodes,seq,assocs,docs,paths,rounds=0,fixed_paths=fixed,avoid_crowding=True)
    # Rectangular bounding-port seeds need true diamond/ellipse projection.
    paths=attach(paths,uv,boxes,nodes)
    # Repair captions against the author's retained information corridors first.
    # Shortcuts are considered later against the complete saved label geometry.
    shortened=[]
    set_di(root,plane,boxes,paths);tree.write(str(target),encoding='utf-8',xml_declaration=True)
    labels=place_labels(target,svg,preserve=True);g=geometry(target)
    if not valid_geometry(g,labels):raise ValueError({'source_repair_rejected':{k:g[k] for k in ('routing_safety_passed','label_collision_pairs','label_line_cuts','edge_object_clearance_violations','excessive_bend_edges')},'unplaced_labels':labels['unplaced_labels']})
    return {'retained_corridors':len(fixed),'shortened_information_links':shortened,'content_translation_x':shift}


class ReferenceBackend(AdaptiveBackend):
    name='v23-reference-attachments-responsive-text'
    preserve_labels=True

    def __init__(self,refine_only=False,**kwargs):
        super().__init__(**kwargs);self.refine_only=refine_only

    def placements(self,*args):
        if self.refine_only:return
        for gap in (28,40):
            try:boxes,report=attachment_axes(*args,gap_size=gap)
            except ValueError:continue
            yield f'activity-axes-local-documents-{gap}',boxes,report
        yield from AxisBackend.placements(self,*args)

    def layout(self,source,output,svg):
        from .pipeline import geometry
        started=time.monotonic();original=self.incumbent;notes=[]
        with tempfile.TemporaryDirectory(prefix='reference-layout-',dir=Path(output).parent) as folder:
            folder=Path(folder);seed=folder/'current.bpmn';preview=folder/'current.svg'
            try:
                prepared=prepare_current_geometry(source,seed,preview,self.candidate_seconds)
                notes.append({'candidate':'current-geometry-repaired','status':'verified',**prepared})
                if self.incumbent is None:self.incumbent=seed
                else:
                    m=read_bpmn(seed);current=read_bpmn(self.incumbent);uv={i:(u,v) for i,u,v,_ in m[5]+m[6]}
                    if self.candidate_rank(seed,m[-2],m[-1],uv,m[4],m[7],m[5])<self.candidate_rank(self.incumbent,current[-2],current[-1],uv,m[4],m[7],m[5]):self.incumbent=seed
            except (ValueError,RuntimeError,TimeoutError) as error:notes.append({'candidate':'current-geometry-repaired','status':'rejected','reason':str(error)})
            try:report=super().layout(source,output,svg)
            finally:self.incumbent=original
            # Attachment refinement leaves every workflow waypoint and node fixed.
            tree,root,_,plane,nodes,seq,assocs,docs,member,lanes,boxes,paths=read_bpmn(output)
            owners=attachment_metrics(nodes,docs,assocs,read_bpmn(source)[-2],read_bpmn(source)[-1])['fixed_owners']
            before=attachment_metrics(nodes,docs,assocs,boxes,paths,owners)
            uv={i:(u,v) for i,u,v,_ in seq+assocs};old_score=score(paths,uv)
            refined,changed=refine_links(nodes,docs,seq,assocs,boxes,paths,[(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes])
            candidate=folder/'short-documents.bpmn';view=folder/'short-documents.svg'
            set_di(root,plane,{},refined);tree.write(str(candidate),encoding='utf-8',xml_declaration=True)
            labels=place_labels(candidate,view,preserve=True);g=geometry(candidate)
            accepted=bool(changed) and valid_geometry(g,labels) and score(refined,uv)<=old_score and semantic_equality(source,candidate) and di_equal(source,candidate)
            if accepted:Path(output).write_bytes(candidate.read_bytes());Path(svg).write_bytes(view.read_bytes())
            final=read_bpmn(output)
            report['attachment_refinement']={'accepted':accepted,'changed_links':changed if accepted else [],'before':before,'after':attachment_metrics(nodes,docs,assocs,final[-2],final[-1],owners),'sequence_waypoints_preserved':True}
            from .attachment_refinement import compact_attachments
            report['local_attachment_moves']=compact_attachments(output,svg,source,seconds=max(4,min(20,self.candidate_seconds*2)))
        report['source_trials']=notes;report['seconds']=round(time.monotonic()-started,3)
        report['reference_target_met']=False
        report['limitations']=['experimental; compare manual and noisy DI separately; no universal nonregression or visual similarity claim']
        return report
