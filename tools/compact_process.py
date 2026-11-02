"""Explicit document abstraction and handoff-aware cold layout.

This produces a simplified presentation model, keeping a complete source copy
and an audited whitelist. It never rewrites the source file.
"""
from pathlib import Path
import argparse,hashlib,json,math,os,shutil,sys,tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22'),str(ROOT/'tools')]
from bpmn_v23.scratch_layout import ScratchBackend,GraphChannelsBackend
from bpmn_v23.document_policy import apply_first_appearance,allowed_projection_equal
from bpmn_v23.pipeline import run
from bpmn_refkit.model import read_bpmn
from bpmn_universal.contract import semantic_equality
from audit_scratch_result import audit


def generate(source,destination,*,omissions=None,role_order='auto',factors=(1.,1.3,1.6),candidate_seconds=45,search_seconds=45):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if source.is_relative_to(destination):raise ValueError('Input must be outside the result directory')
    if not factors or any(not math.isfinite(f) or f<1 for f in factors):raise ValueError('Spacing factors must be finite and at least 1')
    original=source.read_bytes();destination.parent.mkdir(parents=True,exist_ok=True)
    class PresentationGraph(GraphChannelsBackend):
        name='v23-first-appearance-handoff-aware'
        def placements(self,*args):
            nodes,docs=args[:2]
            for name,boxes,report in super().placements(*args):
                if not name.startswith('semantic-'):continue
                for factor in factors:
                    def scaled(b):
                        x,y,w,h=b;return ((x+w/2)*factor-w/2,(y+h/2)*factor-h/2,w,h)
                    placed={n:scaled(b) if n in nodes or n in docs else tuple(v*factor for v in b) for n,b in boxes.items()}
                    extra={**report,'reserved_captions':{n:scaled(b) for n,b in report.get('reserved_captions',{}).items()},'spacing_factor':factor}
                    if 'lane_order_optimization' in extra:
                        detail=extra['lane_order_optimization'];extra['lane_order_optimization']={**detail,'before':detail['before']*factor,'after':detail['after']*factor}
                    yield name+'-spacing-'+str(factor),placed,extra
    with tempfile.TemporaryDirectory(prefix='compact-process-',dir=destination.parent) as folder:
        stage=Path(folder);prepared=stage/'presentation_input.bpmn';journal=stage/'document_changes.json';result=stage/'result'
        plan=apply_first_appearance(source,prepared,journal,omissions)
        run(prepared,result,ScratchBackend(candidate_seconds=candidate_seconds,role_order=role_order,search_seconds=search_seconds,graph_backend=PresentationGraph))
        checked=audit(prepared,result)
        if not allowed_projection_equal(source,result/'process_08_v23.bpmn',plan):raise ValueError('Unapproved change outside document whitelist')
        if source.read_bytes()!=original:raise ValueError('Source changed')
        backend=json.loads((result/'run_report.json').read_text())['backend_report'];selected=backend['selected_candidate'].removesuffix('-refined')
        layout=next(c['layout'] for c in backend['candidates'] if c['candidate']==selected and 'layout' in c)
        model=read_bpmn(result/'process_08_v23.bpmn');order=sorted(model[9],key=lambda l:model[-2][l][1]);detail=layout.get('lane_order_optimization')
        if model[9] and (detail is None or order!=detail['order_ids']):raise ValueError('Requested role ordering was not applied')
        checked.update(comparison_scope='checks.business_xml_equal compares prepared presentation_input.bpmn to the final layout; original document changes are separately whitelisted',original_business_xml_equal=semantic_equality(source,result/'process_08_v23.bpmn'),authorized_document_delta=True,authorized_removed_reference_count=len(plan['removed_reference_ids']),authorized_removed_association_count=len(plan['removed_association_ids']),original_sha256=hashlib.sha256(original).hexdigest(),document_policy_counts={'before':plan['before'],'after':plan['after']},lane_order_optimization=detail)
        (result/'presentation_audit.json').write_text(json.dumps(checked,ensure_ascii=False,indent=2)+'\n')
        shutil.copy2(prepared,result/prepared.name);shutil.copy2(journal,result/journal.name);(result/'original_full_model.bpmn').write_bytes(original)
        destination.mkdir(parents=True,exist_ok=True)
        for p in result.iterdir():os.replace(p,destination/p.name)
    return {'status':'verified_presentation','information_links':plan['after']['information_links'],'information_objects':plan['after']['information_objects'],'role_order':[model[9][l] for l in order],'vertical_handoff_objective':detail}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--omit-documents',type=Path,help='JSON mapping of reviewed redundant reference IDs to reasons; never inferred from similar names')
    p.add_argument('--role-order',nargs='+',default=['auto'],help='auto, or every lane ID in the desired order')
    p.add_argument('--spacing-factors',nargs='+',type=float,default=[1.,1.3,1.6]);p.add_argument('--candidate-timeout',type=int,default=45);p.add_argument('--search-seconds',type=float,default=45)
    a=p.parse_args();omissions=json.loads(a.omit_documents.read_text()) if a.omit_documents else None;order='auto' if a.role_order==['auto'] else a.role_order
    print(json.dumps(generate(a.input,a.output_dir,omissions=omissions,role_order=order,factors=a.spacing_factors,candidate_seconds=a.candidate_timeout,search_seconds=a.search_seconds),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
