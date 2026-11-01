"""Reference-style construction with a measured-density objective and strict freeze."""
from pathlib import Path
from lxml import etree as ET
import copy,tempfile,time
from bpmn_refkit.model import read_bpmn,set_di
from bpmn_refkit.geometry import geometry_audit
from bpmn_universal.engine import save_labels,arrange_flow_labels
from bpmn_universal.cli import deadline
from bpmn_universal.contract import NS,semantic_equality
from .human_layout import proposals
from .reference_style import style_cost
from .pattern_routing import routing_order,hints_factory
from .router import route_graph,refine_paths
from .contours import bounding_ports
from .contours import attach
from .labels import place_labels
from .freeze import equal as di_equal
from .quality import score
from .readability import metrics as reading_metrics,cost as reading_cost,POLICY


def rank(boxes,paths,uv,nodes,docs,seq=None):
    quality=score(paths,uv);style=style_cost(boxes,nodes,docs)
    if seq is None:seq=[(i,u,v,'') for i,(u,v) in uv.items() if u in nodes and v in nodes]
    reading=reading_metrics(boxes,paths,nodes,seq)
    result=reading_cost(reading,quality[0],len(seq),style['penalty'])
    return (round(result,6),quality,style['area_factor'])


def seed_document_labels(root,report,boxes):
    from bpmn_universal.contract import Q,BD,DC
    for d in report['document_owners']:
        shape=root.xpath('.//bd:BPMNShape[@bpmnElement=$id]',namespaces=NS,id=d)[0]
        for old in list(shape.findall(Q(BD,'BPMNLabel'))):shape.remove(old)
        x,y,w,h=boxes[d];lab=ET.SubElement(shape,Q(BD,'BPMNLabel'))
        # Side-caption seed, adjusted later using measured full text.
        ET.SubElement(lab,Q(DC,'Bounds'),x=str(x+w+7),y=str(y+2),width='110',height='45')


class HumanStyleBackend:
    name='v23-human-pattern-construction'
    def __init__(self,candidate_seconds=150,orient_decisions=True,incumbent=None,orientations_only=False,repack_spine=False,scenario_blocks=False):
        if not isinstance(candidate_seconds,int) or not 1<=candidate_seconds<=600:raise ValueError('candidate_seconds must be 1..600')
        self.candidate_seconds=candidate_seconds
        self.orient_decisions=orient_decisions
        self.incumbent=Path(incumbent) if incumbent is not None else None
        self.orientations_only=orientations_only
        self.repack_spine=repack_spine or scenario_blocks
        self.scenario_blocks=scenario_blocks
        if orientations_only and (self.incumbent is None or not orient_decisions):raise ValueError("orientations_only requires a verified incumbent and enabled orientations")
    def layout(self,source,output,svg):
        source=Path(source);output=Path(output);svg=Path(svg)
        tree,_,_,_,nodes,seq,assocs,docs,member,lanes,original,oldpaths=read_bpmn(source)
        if not lanes or any(n not in member for n in nodes):
            from .search import SearchBackend
            return SearchBackend(self.candidate_seconds).layout(source,output,svg)
        from .pipeline import geometry,validate_xml
        uv={i:(u,v) for i,u,v,_ in seq+assocs};logs=[];best=None;started=time.monotonic()
        with tempfile.TemporaryDirectory(prefix='human-layout-',dir=output.parent) as td:
            td=Path(td)
            if self.incumbent is not None:
                # An incumbent is optional and must match the full frozen model.
                # It is copied into staging before typography/geometry checks.
                bp=td/'verified-incumbent.bpmn';sp=td/'verified-incumbent.svg'
                bp.write_bytes(self.incumbent.read_bytes());validate_xml(bp)
                if not semantic_equality(source,bp) or not di_equal(source,bp):raise ValueError('Incumbent freeze violation')
                labels=place_labels(bp,sp);g=geometry(bp)
                if labels['unplaced_labels'] or labels['rendering']['text_overflow_ids'] or g['label_collision_pairs'] or g['label_line_cuts'] or not g['routing_safety_passed'] or not g['edge_clearance_passed']:raise ValueError('Incumbent readability or routing audit failed')
                if not semantic_equality(source,bp) or not di_equal(source,bp):raise ValueError('Incumbent freeze violation')
                parsed=read_bpmn(bp);quality=rank(parsed[-2],parsed[-1],uv,nodes,docs,seq)
                logs.append({'candidate':'verified-incumbent','status':'verified','rank':quality,'source_file':self.incumbent.name,'readability':reading_metrics(parsed[-2],parsed[-1],nodes,seq)})
                best=(quality,'verified-incumbent',bp.read_bytes(),sp.read_bytes(),{})
            for name,boxes,report in proposals(nodes,docs,seq,assocs,member,lanes,original,orient_decisions=self.orient_decisions,repack_spine=self.repack_spine,scenario_blocks=self.scenario_blocks):
                if self.orientations_only and not name.endswith('-oriented'):continue
                at=time.monotonic();ob={n:b for n,b in boxes.items() if n in nodes or n in docs}
                pre=geometry_audit(ob,{},[],[],nodes,docs)
                if pre['shape_overlaps']:
                    logs.append({'candidate':name,'status':'rejected','reason':'shape overlap'});continue
                try:
                    with deadline(self.candidate_seconds):
                        routing_boxes={**ob,**{f'__lane_header_{l}':(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes}}
                        hints=hints_factory(report,boxes,seq,member,{l:boxes[l] for l in lanes})
                        paths,details=route_graph(routing_boxes,nodes,seq,assocs,docs,oldpaths,rounds=2,avoid_crowding=True,priority=routing_order(report,nodes,seq,assocs,boxes),hints=hints)
                        paths=attach(paths,uv,boxes,nodes)
                        ct=copy.deepcopy(tree);root=ct.getroot();plane=root.xpath('.//bd:BPMNPlane',namespaces=NS)[0]
                        set_di(root,plane,boxes,paths);save_labels(root,plane,boxes,nodes,paths);arrange_flow_labels(root,plane,ob,seq,paths);seed_document_labels(root,report,boxes)
                        bp=td/(name+'.bpmn');sp=td/(name+'.svg');ct.write(str(bp),encoding='utf-8',xml_declaration=True)
                        labels=place_labels(bp,sp);g=geometry(bp);validate_xml(bp)
                        if labels['unplaced_labels'] or labels['rendering']['text_overflow_ids'] or g['label_collision_pairs'] or g['label_line_cuts'] or not g['routing_safety_passed'] or not g['edge_clearance_passed']:raise ValueError({'readability_or_routing_audit_failed':{'unplaced_labels':labels['unplaced_labels'],'label_collisions':g['label_collision_pairs'],'label_line_cuts':g['label_line_cuts'],'clearance_violations':g['edge_object_clearance_violations'],'lane_header_cuts':g['lane_header_cuts'],'invalid_endpoints':g['invalid_endpoints'],'routing_safety_passed':g['routing_safety_passed']}})
                        if not semantic_equality(source,bp) or not di_equal(source,bp):raise ValueError('freeze violation')
                        quality=rank(boxes,paths,uv,nodes,docs,seq)
                        logs.append({'candidate':name,'status':'verified','rank':quality,'seconds':round(time.monotonic()-at,3),'readability':reading_metrics(boxes,paths,nodes,seq),'style':style_cost(boxes,nodes,docs),'layout':report,'routing':details})
                        if best is None or quality<best[0]:best=(quality,name,bp.read_bytes(),sp.read_bytes(),report)
                except (ValueError,RuntimeError,TimeoutError) as error:
                    logs.append({'candidate':name,'status':'rejected','reason':str(error),'seconds':round(time.monotonic()-at,3)})
            if best is None:raise RuntimeError({'no_verified_human_style_layout':logs})
            quality,name,bpmn,svg_bytes,report=best
            # Human editing proceeds from a good whole layout, then improves wires.
            bp=td/'best.bpmn';sp=td/'best.svg';bp.write_bytes(bpmn);sp.write_bytes(svg_bytes)
            rt,root,_,plane,_,_,_,_,_,_,boxes,paths=read_bpmn(bp)
            paths=bounding_ports(paths,uv,boxes,nodes);ob={n:b for n,b in boxes.items() if n in nodes or n in docs}
            ob.update({f'__lane_header_{l}':(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes})
            interrupted=False
            try:
                with deadline(min(120,self.candidate_seconds)):
                    refinements=refine_paths(ob,uv,paths,rounds=4,avoid_crowding=True,hints=hints_factory(report,boxes,seq,member,{l:boxes[l] for l in lanes}) if report.get('slots') else None)
            except TimeoutError:refinements=[];interrupted=True
            paths=attach(paths,uv,boxes,nodes);set_di(root,plane,{},paths);save_labels(root,plane,boxes,nodes,paths);arrange_flow_labels(root,plane,ob,seq,paths)
            rt.write(str(bp),encoding='utf-8',xml_declaration=True);labels=place_labels(bp,sp);g=geometry(bp)
            new_rank=rank(boxes,paths,uv,nodes,docs,seq)
            if new_rank<quality and not labels['unplaced_labels'] and not labels['rendering']['text_overflow_ids'] and not g['label_collision_pairs'] and not g['label_line_cuts'] and g['routing_safety_passed'] and g['edge_clearance_passed'] and semantic_equality(source,bp) and di_equal(source,bp):
                logs.append({'candidate':name+'-refined','status':'verified','rank':new_rank,'readability':reading_metrics(boxes,paths,nodes,seq),'refinement_interrupted':interrupted,'refinements':refinements})
                quality,name,bpmn,svg_bytes=new_rank,name+'-refined',bp.read_bytes(),sp.read_bytes()
            output.write_bytes(bpmn);svg.write_bytes(svg_bytes)
        return {'selection_policy':POLICY,'backend':self.name,'selected_candidate':name,'quality':quality,'candidates':logs,'seconds':round(time.monotonic()-started,3),'source_reference_models':32,'selection':'best verified empirical-style candidate; no global optimum guarantee','removed_redundant_associations':[]}
