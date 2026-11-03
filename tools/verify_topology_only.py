"""Metamorphic structural checks: rename every display label, retain the graph.

Geometry envelopes are held fixed: different text may legitimately need a
larger box. This checks grouping/ordering, not identical final pixel positions.
"""
from pathlib import Path
import argparse,copy,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_refkit.model import read_bpmn
from bpmn_v23.stage_episodes import semantic_stages
from bpmn_v23.episode_layout import episode_plan
from bpmn_v23.scratch_layout import semantic_role_order,independent_scenarios


def signature(nodes,seq,member,lanes,boxes,docs,assocs):
    motifs,stages=semantic_stages(nodes,seq,member,boxes)
    slots,_,_=episode_plan(nodes,seq,member,boxes,iterations=160,role_order=semantic_role_order(nodes,seq,member,lanes))
    return {'stages':stages,'pairs':motifs['pairs'],'components':motifs['components'],'feedback':motifs['feedback_edges'],'regions':motifs['graph_regions'],'slots':slots,'role_order':semantic_role_order(nodes,seq,member,lanes),'scenarios':independent_scenarios(nodes,seq,docs,assocs)}


def verify(source):
    before=source.read_bytes();m=read_bpmn(source);nodes,seq,assocs,docs,member,lanes,boxes,paths=m[4:]
    base=signature(nodes,seq,member,lanes,boxes,docs,assocs);variants=[]
    for mode in ['empty','reversed_numbers_and_keywords','unrelated_words']:
        changed=copy.deepcopy(nodes)
        for index,n in enumerate(sorted(changed)):
            changed[n]['name']='' if mode=='empty' else f'{99-index}.987 Отменить уточнить cancel reject approved' if mode=='reversed_numbers_and_keywords' else 'Unrelated text'
        renamed_lanes={l:('' if mode=='empty' else f'{999-i} ZYX') for i,l in enumerate(sorted(lanes))}
        flows=[(i,u,v,'' if mode=='empty' else '999 NO Cancel YES') for i,u,v,_ in seq]
        altered=signature(changed,flows,member,renamed_lanes,boxes,docs,assocs)
        passed=base==altered
        if not passed:raise AssertionError({'case':source.stem,'variant':mode,'changed_components':[k for k in base if base[k]!=altered[k]]})
        variants.append({'variant':mode,'structural_signature_equal':True})
    assert source.read_bytes()==before
    return {'case':source.stem,'source_sha256':hashlib.sha256(before).hexdigest(),'all_variants_equal':True,'variants':variants,'source_unchanged':True,'region_count':len(base['regions']['split_joins'])+len(base['regions']['natural_loops'])}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);args=p.parse_args()
    rows=[verify(f) for f in sorted(args.input_dir.glob('*.bpmn'))];args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps({'protocol':'all node, flow and role display labels replaced; geometry envelopes held fixed; no file mutations; grouping, spine, regions, slots and role/scenario order must be identical','results':rows},ensure_ascii=False,indent=2)+'\n');print([(r['case'],r['all_variants_equal']) for r in rows])
