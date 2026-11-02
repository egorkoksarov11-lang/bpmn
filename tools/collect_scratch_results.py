"""Audit every cold reconstruction and compare it to control and manual DI."""
from pathlib import Path
from collections import Counter
import argparse,json,math,sys
from statistics import median
from lxml import etree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from benchmark_reference_fidelity import measure,comparison
from bpmn_refkit.model import read_bpmn,TAG_TASK,TAG_GATE,TAG_EVENT
from bpmn_v23.document_layout import owners_for
from bpmn_v23.pipeline import geometry
from bpmn_v23.freeze import equal
from bpmn_universal.contract import semantic_equality


def physical_bends(points):
    vectors=[(b[0]-a[0],b[1]-a[1]) for a,b in zip(points,points[1:]) if math.dist(a,b)>.001]
    return sum(abs(a[0]*b[1]-a[1]*b[0])>1e-6*math.hypot(*a)*math.hypot(*b) or a[0]*b[0]+a[1]*b[1]<0 for a,b in zip(vectors,vectors[1:]))


def audited_measure(path,owners):
    result=measure(path,owners);m=read_bpmn(path);seq,assocs=m[5:7];paths=m[-1]
    result['sequence_bends_raw_waypoints']=result['sequence_bends'];result['association_bends_raw_waypoints']=result['association_bends']
    result['sequence_bends']=sum(physical_bends(paths[i]) for i,_,_,_ in seq)
    result['association_bends']=sum(physical_bends(paths[i]) for i,_,_,_ in assocs)
    result['straight_fraction']=sum(physical_bends(paths[i])==0 for i,_,_,_ in seq)/max(1,len(seq))
    return result


def correspondence(nodes,seq,reference_boxes,reference_paths,boxes,paths):
    def categories(bb):
        tasks=[bb[n] for n,o in nodes.items() if o['kind'] in TAG_TASK];tw=median(b[2] for b in tasks) if tasks else 180;th=median(b[3] for b in tasks) if tasks else 76
        result={}
        for i,u,v,_ in seq:
            a,b=bb[u],bb[v];dx=b[0]+b[2]/2-a[0]-a[2]/2;dy=b[1]+b[3]/2-a[1]-a[3]/2
            if abs(dy)<=th*.2 and abs(dx)>=tw*.25:direction='right' if dx>0 else 'left'
            elif abs(dx)<=tw*.15 and abs(dy)>=th*.25:direction='down' if dy>0 else 'up'
            else:direction=('right' if dx>0 else 'left')+'-'+('down' if dy>0 else 'up')
            result[i]=direction
        return result
    expected,actual=categories(reference_boxes),categories(boxes)
    def straight_direction(ps):
        if physical_bends(ps) or len(ps)<2:return None
        a,b=ps[0],ps[-1]
        if abs(a[1]-b[1])<.01 and abs(a[0]-b[0])>.01:return 'right' if b[0]>a[0] else 'left'
        if abs(a[0]-b[0])<.01 and abs(a[1]-b[1])>.01:return 'down' if b[1]>a[1] else 'up'
        return None
    straight={i:straight_direction(reference_paths[i]) for i,_,_,_ in seq};straight={i:v for i,v in straight.items() if v is not None}
    misses=[i for i in expected if actual[i]!=expected[i]]
    preserved=[i for i,direction in straight.items() if straight_direction(paths[i])==direction]
    return {'axis_direction_agreement':(len(seq)-len(misses))/max(1,len(seq)),
            'reference_straight_count':len(straight),'reference_straight_preserved':len(preserved),
            'reference_straight_recall':len(preserved)/len(straight) if straight else None,
            'axis_mismatch_ids':misses,'interpretation':'direction of adjacent semantic steps and actual straight-flow preservation; not a percentage of visual similarity'}


def visible_names(model,svg):
    tree=ET.parse(str(svg));nodes,seq,_,docs=model[4:8]
    for n,o in (nodes|docs).items():
        if not o.get('name'):continue
        attr='data-bpmn-id' if n in nodes and o['kind'] in TAG_TASK else 'data-label-for'
        groups=tree.xpath('//*[@'+attr+'=$id]',id=n)
        if not groups:raise ValueError('Missing visible object name: '+n)
        text=''.join(groups[0].xpath('.//*[local-name()="text"]/text()'))
        if ''.join(text.split())!=''.join(o['name'].split()):raise ValueError('Incomplete visible object name: '+n)
    for i,_,_,name in seq:
        if not name:continue
        groups=tree.xpath('//*[@data-label-for=$id]',id=i)
        if not groups or ''.join(''.join(groups[0].xpath('.//*[local-name()="text"]/text()')).split())!=''.join(name.split()):raise ValueError('Incomplete visible branch caption: '+i)
    return True


def main():
    p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--control-dir',type=Path,required=True);p.add_argument('--candidate-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--overlapping-phases',action='store_true');a=p.parse_args()
    candidate=json.loads((a.candidate_dir/'report.json').read_text());control=json.loads((a.control_dir/'report.json').read_text());baseline={r['id']:r for r in control['results']};rows=candidate['results']
    for row in rows:
        identifier=row['id'];source=a.input_dir/(identifier+'.bpmn');previous=baseline[identifier];row['control_status']=previous['status']
        if row['status']=='rejected_input':continue
        original=read_bpmn(source);owners=owners_for(original[4],original[7],original[6],original[-2]);row['manual']=audited_measure(source,owners)
        if previous['status']=='success':
            oldpath=a.control_dir/identifier/'process_08_v23.bpmn';oldmodel=read_bpmn(oldpath);row['previous']=audited_measure(oldpath,owners)
            row['previous_correspondence']=correspondence(original[4],original[5],original[-2],original[-1],oldmodel[-2],oldmodel[-1])
        if row['status']!='success':continue
        out=a.candidate_dir/identifier/'process_08_v23.bpmn';model=read_bpmn(out);g=geometry(out)
        assert row['from_scratch'] and not any(row['geometry_erasure'][k] for k in ('source_positions_used','source_dimensions_used','source_waypoints_used','source_label_bounds_used','external_incumbent_used'))
        assert semantic_equality(source,out) and equal(source,out) and not g['missing_named_flow_labels']
        row['after']=audited_measure(out,owners);row['full_visible_names_preserved']=visible_names(model,out.with_suffix('.svg'))
        row['reference_correspondence']=correspondence(original[4],original[5],original[-2],original[-1],model[-2],model[-1])
        assert row['after']['hard_geometry']
    candidate['versus_previous']=comparison(rows,'previous');candidate['versus_manual']=comparison(rows,'manual')
    candidate['coverage']={'control':dict(Counter(r['status'] for r in control['results'])),'candidate':dict(Counter(r['status'] for r in rows))}
    candidate['lost_successes']=[r['id'] for r in rows if r['control_status']=='success' and r['status']!='success']
    candidate['recovered_successes']=[r['id'] for r in rows if r['control_status']!='success' and r['status']=='success']
    candidate['protocol'].update(input_kind='from-scratch',baseline='scratch-human; input DI fully erased; no external incumbent',candidate='scratch; input DI fully erased; no external incumbent',interpretation='original references used only for assessment; all failures and per-model regressions retained; no claimed 80% visual similarity',sequential_engine_phases=not a.overlapping_phases)
    candidate['protocol']['bend_definition']='actual direction changes; duplicate and forward collinear waypoints do not count; raw waypoint counts retained separately'
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(candidate,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
