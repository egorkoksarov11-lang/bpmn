"""Reference-style construction with a measured-density objective and strict freeze."""
from pathlib import Path
from lxml import etree as ET
import copy,tempfile,time,json
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
from .return_corridors import hints_factory as return_hints
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
    def __init__(self,candidate_seconds=150,orient_decisions=True,incumbent=None,orientations_only=False,repack_spine=False,scenario_blocks=False,reference_profile=None):
        if not isinstance(candidate_seconds,int) or not 1<=candidate_seconds<=600:raise ValueError('candidate_seconds must be 1..600')
        self.candidate_seconds=candidate_seconds
        self.orient_decisions=orient_decisions
        self.incumbent=Path(incumbent) if incumbent is not None else None
        self.orientations_only=orientations_only
        self.repack_spine=repack_spine or scenario_blocks
        self.scenario_blocks=scenario_blocks
        self.reference_profile=json.loads(Path(reference_profile).read_text()) if reference_profile else None
        if orientations_only and (self.incumbent is None or not orient_decisions):raise ValueError("orientations_only requires a verified incumbent and enabled orientations")
    def candidate_rank(self,path,boxes,paths,uv,nodes,docs,seq):
        base=rank(boxes,paths,uv,nodes,docs,seq)
        if self.reference_profile is None:return base
        from .reference_metrics import features,evaluate
        result=evaluate(features(path),self.reference_profile)
        return (round(100-result['conformity_percent'],6),base[1],base[2])
    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        return proposals(nodes,docs,seq,assocs,member,lanes,original,orient_decisions=self.orient_decisions,repack_spine=self.repack_spine,scenario_blocks=self.scenario_blocks)
    def layout(self,source,output,svg):
        source=Path(source);output=Path(output);svg=Path(svg)
        tree,_,_,_,nodes,seq,assocs,docs,member,lanes,original,oldpaths=read_bpmn(source)
        if not lanes or any(n not in member for n in nodes):
            from .search import SearchBackend
            return SearchBackend(self.candidate_seconds).layout(source,output,svg)
        from .pipeline import geometry,validate_xml
        uv={i:(u,v) for i,u,v,_ in seq+assocs};logs=[];best=None;best_safe=None;selected_safe=False;started=time.monotonic()
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
                parsed=read_bpmn(bp);quality=self.candidate_rank(bp,parsed[-2],parsed[-1],uv,nodes,docs,seq)
                logs.append({'candidate':'verified-incumbent','status':'verified','rank':quality,'source_file':self.incumbent.name,'readability':reading_metrics(parsed[-2],parsed[-1],nodes,seq)})
                best=(quality,'verified-incumbent',bp.read_bytes(),sp.read_bytes(),{})
                selected_safe=not g['excessive_bend_edges']
                if selected_safe:best_safe=best
            for name,boxes,report in self.placements(nodes,docs,seq,assocs,member,lanes,original):
                if best_safe is not None and getattr(self,'max_search_seconds',None) is not None and time.monotonic()-started>self.max_search_seconds:
                    logs.append({'candidate':name,'status':'skipped-search-budget'});break
                if self.orientations_only and not name.endswith('-oriented'):continue
                at=time.monotonic();ob={n:b for n,b in boxes.items() if n in nodes or n in docs}
                pre=geometry_audit(ob,{},[],[],nodes,docs)
                if pre['shape_overlaps']:
                    logs.append({'candidate':name,'status':'rejected','reason':'shape overlap'});continue
                try:
                    with deadline(self.candidate_seconds):
                        routing_boxes={**ob,**{f'__lane_header_{l}':(boxes[l][0],boxes[l][1],48,boxes[l][3]) for l in lanes}}
                        routing_boxes.update({f'__caption_{n}':tuple(b) for n,b in report.get('reserved_captions',{}).items()})
                        hints=None if report.get('external_engine') else hints_factory(report,boxes,seq,member,{l:boxes[l] for l in lanes})
                        fixed=None
                        if report.get('preserve_corridors'):
                            from .axis_corridors import mapped_routes
                            basis_boxes,basis_paths=(read_bpmn(self.incumbent)[-2:] if report.get('route_basis')=='verified-incumbent' else (original,oldpaths))
                            fixed=mapped_routes(report,basis_boxes,basis_paths,boxes,nodes,routing_boxes,uv)
                        paths,details=route_graph(routing_boxes,nodes,seq,assocs,docs,oldpaths,rounds=2,avoid_crowding=True,priority=report.get('routing_priority') or routing_order(report,nodes,seq,assocs,boxes),hints=hints,fixed_paths=fixed)
                        if fixed is not None:details['retained_input_corridors']=len(fixed)
                        paths=attach(paths,uv,boxes,nodes)
                        ct=copy.deepcopy(tree);root=ct.getroot();plane=root.xpath('.//bd:BPMNPlane',namespaces=NS)[0]
                        set_di(root,plane,boxes,paths);save_labels(root,plane,boxes,nodes,paths);arrange_flow_labels(root,plane,ob,seq,paths);seed_document_labels(root,report,boxes)
                        if report.get('reserved_captions'):
                            from .axis_labels import seed_captions
                            seed_captions(root,report['reserved_captions'])
                        bp=td/(name+'.bpmn');sp=td/(name+'.svg');ct.write(str(bp),encoding='utf-8',xml_declaration=True)
                        labels=place_labels(bp,sp);g=geometry(bp);validate_xml(bp)
                        if labels['unplaced_labels'] or labels['rendering']['text_overflow_ids'] or g['label_collision_pairs'] or g['label_line_cuts'] or not g['routing_safety_passed'] or not g['edge_clearance_passed']:raise ValueError({'readability_or_routing_audit_failed':{'unplaced_labels':labels['unplaced_labels'],'label_collisions':g['label_collision_pairs'],'label_line_cuts':g['label_line_cuts'],'clearance_violations':g['edge_object_clearance_violations'],'lane_header_cuts':g['lane_header_cuts'],'invalid_endpoints':g['invalid_endpoints'],'routing_safety_passed':g['routing_safety_passed']}})
                        if not semantic_equality(source,bp) or not di_equal(source,bp):raise ValueError('freeze violation')
                        quality=self.candidate_rank(bp,boxes,paths,uv,nodes,docs,seq)
                        logs.append({'candidate':name,'status':'verified','rank':quality,'seconds':round(time.monotonic()-at,3),'readability':reading_metrics(boxes,paths,nodes,seq),'style':style_cost(boxes,nodes,docs),'layout':report,'routing':details})
                        entry=(quality,name,bp.read_bytes(),sp.read_bytes(),report)
                        safe=not g['excessive_bend_edges']
                        if safe and (best_safe is None or quality<best_safe[0]):best_safe=entry
                        if best is None or quality<best[0]:best=entry;selected_safe=safe
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
                    refinements=refine_paths(ob,uv,paths,rounds=4,avoid_crowding=True,simplify=getattr(self,'simplify_routes',False),hints=(return_hints(nodes,seq,boxes,member,{l:boxes[l] for l in lanes}) if getattr(self,'return_corridors',False) else None if report.get('external_engine') or not report.get('slots') else hints_factory(report,boxes,seq,member,{l:boxes[l] for l in lanes})))
            except TimeoutError:refinements=[];interrupted=True
            paths=attach(paths,uv,boxes,nodes);set_di(root,plane,{},paths);save_labels(root,plane,boxes,nodes,paths);arrange_flow_labels(root,plane,ob,seq,paths)
            rt.write(str(bp),encoding='utf-8',xml_declaration=True);labels=place_labels(bp,sp);g=geometry(bp)
            new_rank=self.candidate_rank(bp,boxes,paths,uv,nodes,docs,seq)
            if new_rank<quality and not labels['unplaced_labels'] and not labels['rendering']['text_overflow_ids'] and not g['label_collision_pairs'] and not g['label_line_cuts'] and g['routing_safety_passed'] and g['edge_clearance_passed'] and not g['excessive_bend_edges'] and semantic_equality(source,bp) and di_equal(source,bp):
                logs.append({'candidate':name+'-refined','status':'verified','rank':new_rank,'readability':reading_metrics(boxes,paths,nodes,seq),'refinement_interrupted':interrupted,'refinements':refinements})
                quality,name,bpmn,svg_bytes=new_rank,name+'-refined',bp.read_bytes(),sp.read_bytes()
                selected_safe=True
            else:
                logs.append({'candidate':name+'-refined','status':'discarded','rank':new_rank,'refinement_interrupted':interrupted,'excessive_bend_edges':g['excessive_bend_edges'],'reason':'did not improve rank or failed independent geometry/text/freeze checks'})
            if not selected_safe:
                if best_safe is None:raise RuntimeError('No verified layout without pathological bends; incumbent retained on disk')
                quality,name,bpmn,svg_bytes,report=best_safe
                logs.append({'candidate':name,'status':'safe-fallback','reason':'higher-ranked intermediate had pathological bends'})
            output.write_bytes(bpmn);svg.write_bytes(svg_bytes)
        return {'selection_policy':getattr(self,'selection_policy',self.reference_profile['version'] if self.reference_profile else POLICY),'backend':self.name,'selected_candidate':name,'quality':quality,'candidates':logs,'seconds':round(time.monotonic()-started,3),'source_reference_models':32,'selection':'best verified empirical-style candidate; no global optimum guarantee','removed_redundant_associations':[]}
