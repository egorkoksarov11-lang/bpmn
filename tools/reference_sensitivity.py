"""File-level bootstrap diagnostic; never a human-similarity confidence interval."""
import argparse,json,random,statistics,sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src/v23'),str(Path(__file__).resolve().parents[1]/'src/v22')]
from bpmn_v23.reference_metrics import features,calibrate,evaluate

p=argparse.ArgumentParser()
p.add_argument('--report',type=Path,required=True)
p.add_argument('--baseline',type=Path,required=True)
p.add_argument('--candidate',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--resamples',type=int,default=300)
a=p.parse_args()
if not 20<=a.resamples<=10000:p.error('resamples must be 20..10000')
if a.output.resolve() in {a.report.resolve(),a.baseline.resolve(),a.candidate.resolve()}:p.error('Separate output required')
report=json.loads(a.report.read_text());rows=report['reference_features'];rnd=random.Random(23)
scores={'baseline':[],'candidate':[]};candidates={'baseline':features(a.baseline),'candidate':features(a.candidate)}
for _ in range(a.resamples):
    profile=calibrate(rnd.choices(rows,k=len(rows)))
    for k,r in candidates.items():scores[k].append(evaluate(r,profile)['conformity_percent'])
result={'method':'file-level bootstrap; NOT a confidence interval of human similarity; related models may be dependent','resamples':a.resamples,'seed':23,'file_count':len(rows),'unique_raw_hashes':len({r['sha256'] for r in report['reference_files']}),'scores':{k:{'p05':sorted(v)[int(len(v)*.05)],'median':statistics.median(v),'p95':sorted(v)[int(len(v)*.95)]} for k,v in scores.items()},'candidate_improves_baseline_fraction':sum(b>a for a,b in zip(scores['baseline'],scores['candidate']))/a.resamples}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
