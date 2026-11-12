"""Export an early graph-only plan without routing or changing the input BPMN."""
from pathlib import Path
import argparse,copy,json,sys,tempfile,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_refkit.model import read_bpmn
from bpmn_v23.scratch_layout import erase_geometry
from bpmn_v23.composition_plan import plan


def inspect(source,checks=False):
    start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='bpmn-plan-') as td:
        neutral=Path(td)/'neutral.bpmn';erasure=erase_geometry(source,neutral);s=read_bpmn(neutral)
        args=(s[4],s[7],s[5],s[6],s[8],s[9],s[-2]);before=copy.deepcopy(args) if checks else None;chosen,report=plan(*args)
        if checks:
            nodes=copy.deepcopy(s[4]);docs=copy.deepcopy(s[7]);roles={l:'DIFFERENT ROLE NAME' for l in s[9]}
            for o in list(nodes.values())+list(docs.values()):o['name']='UNRELATED TEXT AND 999'
            changed=plan(nodes,docs,s[5],s[6],s[8],roles,s[-2])[0]
            assert chosen==changed,'Structural plan depends on names'
            assert chosen==plan(*args)[0],'Plan is not repeatable'
            shifted=Path(td)/'shifted.bpmn';tree=s[0]
            from bpmn_universal.contract import NS
            for i,b in enumerate(tree.getroot().xpath('.//dc:Bounds',namespaces=NS)):
                b.set('x',str((i*1373)%12001));b.set('y',str((i*977)%9001))
                b.set('width',str(99+i%101));b.set('height',str(23+(i%7)*17))
            for i,w in enumerate(tree.getroot().xpath('.//di:waypoint',namespaces=NS)):
                w.set('x',str((i*311)%7001));w.set('y',str((i*419)%5003))
            tree.write(str(shifted),encoding='utf-8',xml_declaration=True)
            erase_geometry(shifted,neutral);v=read_bpmn(neutral)
            assert chosen==plan(v[4],v[7],v[5],v[6],v[8],v[9],v[-2])[0],'Source coordinates affect plan'
            assert args==before,'Planner mutated its input graph or measured sizes'
            report['checks']={'planning_input_immutable':True,'name_and_number_invariance':True,'repeatability':True,'source_coordinate_invariance':True,'source_geometry_scrambled':True}
    return {'status':'composition_plan_only_not_a_verified_diagram','geometry_erasure':erasure,'analysis':report,'plans':chosen,'total_seconds':round(time.monotonic()-start,6)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--checks',action='store_true');a=parser.parse_args()
    if a.input.resolve()==a.output.resolve():parser.error('Output must differ from input')
    report=inspect(a.input,a.checks);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'output':str(a.output),'planning_seconds':report['analysis']['seconds'],'total_seconds':report['total_seconds'],'checks':report['analysis'].get('checks')},ensure_ascii=False))
