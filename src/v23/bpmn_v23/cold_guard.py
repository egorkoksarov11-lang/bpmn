"""Non-regression guard: build a second internal cold seed for a dense result.

The fallback is generated now from the SAME erased business model. No supplied
incumbent, archived diagram or reference coordinates are accepted by this API.
"""
from pathlib import Path
import math
from bpmn_refkit.model import read_bpmn
from bpmn_universal.contract import semantic_equality
from .freeze import equal
from .local_editing import local_quality
from .attachment_refinement import compact_attachments


def needs_guard(quality,flow_count):
    contacts,bends,length=quality;n=max(1,flow_count)
    return bends/n>1.2 and contacts/n>.5 and length/(200*n)>2.5



def prefer_control(before,candidate,area_ratio):
    pareto=(all(a<=b+1e-6 for a,b in zip(candidate,before)) and any(a<b-1e-6 for a,b in zip(candidate,before)) and area_ratio<=1.25)
    # A substantial reduction in footprint and travel can justify a small
    # increase in crossings/bends. Keep the permitted trade explicit/bounded.
    compact=(area_ratio<=.8 and candidate[2]<=before[2]*.85 and candidate[0]<=max(1,before[0])*1.2 and candidate[1]<=max(1,before[1])*1.1)
    # Fewer elbows alone must not hide a dense tangle of crossings. Permit
    # a bounded bend increase only for a substantial measured wire improvement.
    old_wire=8*before[0]+1.2*before[1]+before[2]/200
    new_wire=8*candidate[0]+1.2*candidate[1]+candidate[2]/200
    reading=(before[0]>=4 and candidate[0]<=before[0]*.8 and candidate[1]<=max(1,before[1])*1.2 and candidate[2]<=before[2]*1.05 and area_ratio<=1.1 and new_wire<=old_wire*.93)
    return pareto or compact or reading,('pareto' if pareto else 'bounded_compactness_trade' if compact else 'bounded_wire_readability_trade' if reading else 'retained_primary')


def protect_cold_result(source,output,svg,*,candidate_seconds=60,search_seconds=200,role_order=None):
    from .scratch_layout import GraphChannelsBackend,semantic_document_owners
    from .pipeline import geometry
    state=read_bpmn(output);uv={i:(u,v) for i,u,v,*_ in state[5]+state[6]};before=local_quality(state[-1],uv,state[5])
    report={'method':'new internal legacy construction from erased input; Pareto or explicitly bounded compactness/travel/wire readability trade','before':before,'triggered':needs_guard(before,len(state[5])),'reference_geometry_used':False,'external_incumbent_used':False}
    if not report['triggered']:return report,None
    candidate=Path(output).with_name('internal_cold_control.bpmn');preview=candidate.with_suffix('.svg')
    try:
        legacy=GraphChannelsBackend(candidate_seconds=candidate_seconds,search_seconds=search_seconds,role_order=role_order)
        result=legacy.layout(source,candidate,preview)
        m=read_bpmn(candidate);anchors=semantic_document_owners(m[4],m[7],m[6],m[-2]);compact_attachments(candidate,preview,source,seconds=min(12,candidate_seconds*2),fixed_owners=anchors)
        m=read_bpmn(candidate);uv={i:(u,v) for i,u,v,*_ in m[5]+m[6]};quality=local_quality(m[-1],uv,m[5]);g=geometry(candidate);old=geometry(output)
        report['candidate_quality']=quality
        area=g['extent']['width']*g['extent']['height'];old_area=old['extent']['width']*old['extent']['height']
        accepted,reason=prefer_control(before,quality,area/max(1,old_area))
        report['selection_reason']=reason
        accepted=accepted and g['routing_safety_passed'] and g['edge_clearance_passed'] and not(g['label_collision_pairs'] or g['label_line_cuts'] or g['excessive_bend_edges'] or g['task_text_overflows'] or g['missing_named_flow_labels'])
        if not semantic_equality(source,candidate) or not equal(source,candidate):raise ValueError('Internal cold guard freeze violation')
        report['selected']=bool(accepted);report['candidate_name']=result['selected_candidate'];report['area_ratio']=area/max(1,old_area)
        if accepted:Path(output).write_bytes(candidate.read_bytes());Path(svg).write_bytes(preview.read_bytes())
        return report,result if accepted else None
    except (RuntimeError,ValueError,TimeoutError) as error:
        report.update(selected=False,error=str(error));return report,None
    finally:
        candidate.unlink(missing_ok=True);preview.unlink(missing_ok=True)
