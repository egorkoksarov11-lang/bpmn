"""Independently audit a saved cold reconstruction, without running layout."""
from pathlib import Path
import argparse, hashlib, json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_refkit.model import read_bpmn
from bpmn_universal.contract import semantic_equality
from bpmn_v23.freeze import equal
from bpmn_v23.pipeline import geometry,validate_xml
from bpmn_v23.document_layout import owners_for
from collect_scratch_results import audited_measure,visible_names,correspondence


def audit(source,folder):
    output=folder/'process_08_v23.bpmn';svg=output.with_suffix('.svg')
    validate_xml(source);validate_xml(output)
    original,model=read_bpmn(source),read_bpmn(output)
    backend=json.loads((folder/'run_report.json').read_text())['backend_report']
    erased=backend['geometry_erasure'];g=geometry(output)
    owners=owners_for(original[4],original[7],original[6],original[-2])
    checks={
        'from_scratch':backend['from_scratch'] is True,
        'source_geometry_erased':not any(erased[k] for k in ('source_positions_used','source_dimensions_used','source_waypoints_used','source_label_bounds_used','external_incumbent_used','source_lane_order_used')),
        'business_xml_equal':semantic_equality(source,output),
        'di_identity_equal':equal(source,output),
        'all_visible_names':visible_names(model,svg),
        'routing_safety':g['routing_safety_passed'],
        'clearance':g['edge_clearance_passed'],
        'labels_clear':not(g['label_collision_pairs'] or g['label_line_cuts'] or g['missing_named_flow_labels']),
        'task_text_fits':not g['task_text_overflows'],
        'bend_limit':not g['excessive_bend_edges'],
    }
    if not all(checks.values()):raise ValueError(checks)
    return {'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'checks':checks,'counts':dict(nodes=len(model[4]),sequence_flows=len(model[5]),information_links=len(model[6]),information_objects=len(model[7]),lanes=len(model[9])),
            'manual':audited_measure(source,owners),'after':audited_measure(output,owners),
            'reference_correspondence':correspondence(original[4],original[5],original[-2],original[-1],model[-2],model[-1]),
            'selected_candidate':backend['selected_candidate'],'seconds':backend['seconds'],
            'reference_target_met':False,'interpretation':'strict correctness checks passed; metrics and direction agreement do not establish 80% visual similarity'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    result=audit(a.input,a.output_dir);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'checks':result['checks'],'counts':result['counts']}))


if __name__=='__main__':main()
