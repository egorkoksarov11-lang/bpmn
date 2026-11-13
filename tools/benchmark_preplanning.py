"""Paired preparation timings on caller-supplied large BPMN files (no rendering)."""
from pathlib import Path
import argparse,hashlib,json,sys,tempfile,time,statistics
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_refkit.model import read_bpmn
from bpmn_v23.scratch_layout import erase_geometry
from bpmn_v23.composition_plan import coarse_plan,materialize_coarse,plan,materialize


def measure(args,detailed):
    start=time.perf_counter();chosen,report=(plan if detailed else coarse_plan)(*args)
    for p in chosen:(materialize if detailed else materialize_coarse)(p,*args)
    return time.perf_counter()-start,len(chosen)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs',type=Path,nargs='+');parser.add_argument('--output',type=Path,required=True);parser.add_argument('--repeats',type=int,default=3);a=parser.parse_args()
    if a.repeats<1:parser.error('repeats must be positive')
    if any(a.output.resolve()==p.resolve() for p in a.inputs):parser.error('Output must differ from inputs')
    rows=[]
    for index,source in enumerate(a.inputs):
        with tempfile.TemporaryDirectory() as td:
            neutral=Path(td)/'neutral.bpmn';erase_geometry(source,neutral);s=read_bpmn(neutral);args=(s[4],s[7],s[5],s[6],s[8],s[9],s[-2])
            # Warm both implementations; alternate paired order, same process.
            measure(args,False);measure(args,True);samples={'previous':[],'detailed':[]}
            for i in range(a.repeats):
                for detailed in ((False,True) if i%2==0 else (True,False)):
                    seconds,count=measure(args,detailed);samples['detailed' if detailed else 'previous'].append(seconds)
            old=statistics.median(samples['previous']);new=statistics.median(samples['detailed'])
            rows.append({'case':f'large_{index+1}','input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'nodes':len(s[4]),'roles':len(s[9]),'samples_seconds':samples,'previous_median_seconds':old,'detailed_median_seconds':new,'ratio':new/old})
    result={'scope':'warm preliminary plan AND measured candidate materialization; excludes parse, source erasure and final routing','repeats':a.repeats,'cases':rows}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
