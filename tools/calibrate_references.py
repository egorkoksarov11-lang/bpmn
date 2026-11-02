"""Calibrate without overwriting input archives or changing any reference model."""
from pathlib import Path
import argparse,json,zipfile,tempfile,sys,hashlib
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src/v23'),str(Path(__file__).resolve().parents[1]/'src/v22')]
from bpmn_v23.reference_metrics import features,calibrate,evaluate
p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--candidate',type=Path,action='append',default=[]);a=p.parse_args()
if a.output.resolve()==a.archive.resolve() or a.output.resolve() in [c.resolve() for c in a.candidate]:raise ValueError('Separate output required')
a.output.mkdir(exist_ok=True,parents=True);rows=[];files=[];fail=[]
with zipfile.ZipFile(a.archive) as z,tempfile.TemporaryDirectory() as d:
 for idx,i in enumerate(z.infolist()):
  if not i.filename.lower().endswith('.bpmn'):continue
  if i.file_size>25000000:raise ValueError('oversized reference')
  f=Path(d)/f'{idx}.bpmn';f.write_bytes(z.read(i))
  try:
   rows.append(features(f));files.append({'file':i.filename,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
  except Exception as e:fail.append({'file':i.filename,'reason':str(e)})
profile=calibrate(rows);profile['archive_sha256']=hashlib.sha256(a.archive.read_bytes()).hexdigest();loo=[evaluate(r,calibrate(rows[:i]+rows[i+1:]))['conformity_percent'] for i,r in enumerate(rows)]
report={'profile':profile,'failures':fail,'reference_files':files,'reference_features':rows,'leave_one_file_out_scores':loo,'validation_note':'leave-one-file-out is diagnostic only; related process versions may not be independent','candidates':{c.name+'@'+hashlib.sha256(c.read_bytes()).hexdigest()[:12]:evaluate(features(c),profile) for c in a.candidate}}
(a.output/'reference_profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2));(a.output/'reference_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'references':len(rows),'failures':fail,'candidates':{k:v['conformity_percent'] for k,v in report['candidates'].items()}}))
