"""Single-entry BPMN layout CLI: inspect, optimize, batch, config."""
from __future__ import annotations
import argparse
import signal
from contextlib import contextmanager
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from .settings import Settings
from .contract import UnsupportedBPMN,preflight,semantic_equality,removable_mirror_ids
from .engine import run


def pretty(data):return json.dumps(data,ensure_ascii=False,indent=2)

@contextmanager
def deadline(seconds:int):
    """Limit combinatorial routing for an autonomous batch; Linux/macOS."""
    if not hasattr(signal,'SIGALRM'):
        yield
        return
    def timeout_handler(signum, frame):
        raise TimeoutError(f'BPMN routing exceeded {seconds} seconds')
    old=signal.signal(signal.SIGALRM,timeout_handler)
    signal.setitimer(signal.ITIMER_REAL,seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,old)



def optimize(source:Path,output:Path,settings:Settings,svg=None,png=None,report=None):
    source=Path(source).resolve();output=Path(output).resolve()
    if source==output:raise ValueError('Input cannot be overwritten. Choose a different output path.')
    if source.suffix.lower() not in ('.bpmn','.xml'):raise ValueError('Input extension must be .bpmn or .xml')
    if output.suffix.lower()!='.bpmn':raise ValueError('Output extension must be .bpmn')
    scan=preflight(source)
    if not scan['compatible']:
        raise UnsupportedBPMN('Preflight failed:\n- '+'\n- '.join(scan['errors']))
    semantics=settings.semantics
    approved=set(semantics.approved_association_removals)
    permitted=removable_mirror_ids(source)
    if approved-permitted:
        raise ValueError('Approval list contains associations that are not mechanically redundant mirror pairs: '+str(sorted(approved-permitted)))
    output.parent.mkdir(parents=True,exist_ok=True)
    g=settings.geometry
    with tempfile.TemporaryDirectory(prefix='.bpmn_v22_',dir=output.parent) as temp:
        directory=Path(temp)
        tmp=directory/'result.bpmn'
        tmp_svg=directory/'result.svg' if svg or png else None
        tmp_png=directory/'result.png' if png else None
        with deadline(settings.execution.timeout_seconds):
            data=run(input=str(source),output=str(tmp),svg=str(tmp_svg) if tmp_svg else None,
                 png=str(tmp_png) if tmp_png else None,report=None,
                 scale=g.horizontal_scale,clean_duplicates=bool(approved),approved_ids=approved,
                 task_gap=g.task_gap,document_gap=g.document_gap,
                 candidate_scales=g.candidate_scales,routing_order=g.routing_order,
                 max_width_growth=g.max_width_growth,max_flow_length_growth=g.max_avg_flow_length_growth,
                 png_width=settings.outputs.png_width)
        dropped=set(data.get('removed_redundant_associations',()))
        if dropped!=approved:
            raise RuntimeError('Explicitly approved document association IDs were not all verified as exact mirrored pairs: '+str(sorted(approved-dropped)))
        if not semantic_equality(source,tmp,approved_removed=dropped):
            raise RuntimeError('INDEPENDENT SEMANTIC CHECK FAILED; output rejected')
        after_scan=preflight(tmp)
        if not after_scan['compatible']:
            raise RuntimeError('Generated BPMN failed revalidation: '+str(after_scan['errors']))
        if svg and not tmp_svg.is_file():raise RuntimeError('SVG not generated')
        if png and not tmp_png.is_file():raise RuntimeError('PNG not generated')
        # Move only after all checks. Results from a failed run never overwrite output.
        os.replace(tmp,output)
        if svg:
            svg=Path(svg).resolve();svg.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(tmp_svg,svg)
        if png:
            png=Path(png).resolve();png.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(tmp_png,png)
    data.update({'engine_version':'22.0.0','status':'passed','source':str(source),'output':str(output),
                'supported_profile':'single-process BPMN2 with BPMN-DI; no message flows',
                'preflight':scan,'semantic_check':{'passed':True,'mode':semantics.mode,
                'removed_associations':sorted(dropped)},
                'artifacts':{'bpmn':str(output),'svg':str(svg) if svg else None,'png':str(png) if png else None}})
    if report:
        report=Path(report).resolve();report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(pretty(data)+'\n',encoding='utf-8')
    return data


def main(argv=None):
    parser=argparse.ArgumentParser(prog='bpmn-layout',description='BPMN reference-style compact layout (safe v22 profile)')
    sub=parser.add_subparsers(dest='command',required=True)
    ins=sub.add_parser('inspect',help='Validate BPMN compatibility and list supported elements')
    ins.add_argument('--input',required=True,type=Path);ins.add_argument('--json',type=Path)
    opt=sub.add_parser('optimize',help='Optimize a single diagram without changing business semantics')
    opt.add_argument('--input',required=True,type=Path);opt.add_argument('--output',required=True,type=Path)
    opt.add_argument('--config',type=Path);opt.add_argument('--svg',type=Path);opt.add_argument('--png',type=Path);opt.add_argument('--report',type=Path)
    batch=sub.add_parser('batch',help='Optimize all .bpmn files in a folder')
    batch.add_argument('--input-dir',required=True,type=Path);batch.add_argument('--output-dir',required=True,type=Path)
    batch.add_argument('--config',type=Path);batch.add_argument('--recursive',action='store_true')
    batch.add_argument('--summary',type=Path)
    cfg=sub.add_parser('config',help='Print the default JSON configuration');cfg.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.command=='config':
            body=pretty(Settings().as_dict())+'\n'
            if args.output:
                args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(body,encoding='utf-8')
            else:print(body,end='')
            return 0
        if args.command=='inspect':
            data=preflight(args.input)
            if args.json:
                args.json.parent.mkdir(parents=True,exist_ok=True);args.json.write_text(pretty(data)+'\n',encoding='utf-8')
            print(pretty(data));return 0 if data['compatible'] else 2
        if args.command=='optimize':
            s=Settings.load(args.config)
            data=optimize(args.input,args.output,s,svg=args.svg,png=args.png,report=args.report)
            print(pretty({'status':'passed','bpmn':data['output'],'associations_removed':data['removed_redundant_associations'],
                          'crossings_before':data['geometry_before']['crossings'],'crossings_after':data['geometry_after']['crossings'],
                          'bends_before':data['geometry_before']['total_bends'],'bends_after':data['geometry_after']['total_bends']}))
            return 0
        if args.command=='batch':
            s=Settings.load(args.config)
            if not args.input_dir.is_dir():raise NotADirectoryError(str(args.input_dir))
            if args.input_dir.resolve()==args.output_dir.resolve():raise ValueError('Input/output dirs must differ')
            inputs=sorted(args.input_dir.rglob('*.bpmn') if args.recursive else args.input_dir.glob('*.bpmn'))
            cases=[]
            for f in inputs:
                dest=args.output_dir / f.relative_to(args.input_dir)
                try:
                    data=optimize(f,dest,s,svg=dest.with_suffix('.svg') if s.outputs.svg else None,
                                  png=dest.with_suffix('.png') if s.outputs.png else None,
                                  report=dest.with_suffix('.json') if s.outputs.report else None)
                    cases.append({'input':str(f),'output':str(dest),'status':'passed','semantics':True,
                                  'crossings':data['geometry_after']['crossings'],'bends':data['geometry_after']['total_bends']})
                except Exception as exc:
                    cases.append({'input':str(f),'status':'failed','reason':str(exc)})
            summary={'total':len(cases),'passed':sum(c['status']=='passed' for c in cases),
                     'failed':sum(c['status']=='failed' for c in cases),'cases':cases}
            if args.summary:
                args.summary.parent.mkdir(parents=True,exist_ok=True)
                args.summary.write_text(pretty(summary)+'\n',encoding='utf-8')
            print(pretty({'total':summary['total'],'passed':summary['passed'],'failed':summary['failed']}))
            return 0 if summary['failed']==0 else 2
    except (ValueError,UnsupportedBPMN,RuntimeError,OSError,KeyError,TimeoutError) as err:
        print(f'ERROR: {err}',file=sys.stderr);return 2
    return 1

if __name__=='__main__':sys.exit(main())
