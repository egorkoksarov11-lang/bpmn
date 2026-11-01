"""Measure an example archive without changing its models or input files."""
import argparse,json,sys
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path[:0]=[str(root/'src/v23'),str(root/'src/v22')]
from bpmn_v23.reference_style import measure_zip
parser=argparse.ArgumentParser()
parser.add_argument('--input-zip',type=Path,required=True)
parser.add_argument('--output-profile',type=Path,required=True)
args=parser.parse_args()
if args.input_zip.resolve()==args.output_profile.resolve():raise ValueError('Source archive cannot be overwritten')
if args.output_profile.suffix.lower()!='.json':raise ValueError('Profile must be a .json file')
profile=measure_zip(args.input_zip);args.output_profile.parent.mkdir(parents=True,exist_ok=True)
args.output_profile.write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'models_measured':profile['models_measured'],'tasks_measured':profile['tasks_measured'],'output':str(args.output_profile)},ensure_ascii=False))
