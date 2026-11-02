"""Metamorphic corpus check: arbitrary original DI produces identical planner input."""
from pathlib import Path
import argparse,hashlib,json,random,sys,tempfile
from lxml import etree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_universal.contract import NS,semantic_equality
from bpmn_refkit.model import read_bpmn
from bpmn_v23.scratch_layout import erase_geometry
from bpmn_v23.pipeline import validate_xml
from bpmn_v23.freeze import equal


def digest(path):
    model=read_bpmn(path)
    assert not model[1].xpath('.//bd:BPMNLabel',namespaces=NS)
    return hashlib.sha256(json.dumps({'boxes':model[-2],'paths':model[-1]},sort_keys=True).encode()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args();results=[]
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        for source in sorted(a.input_dir.glob('*.bpmn')):
            try:validate_xml(source)
            except Exception as e:results.append({'id':source.stem,'status':'rejected_input','reason':str(e)});continue
            tree=ET.parse(str(source));rng=random.Random(2371)
            for b in tree.xpath('.//dc:Bounds',namespaces=NS):
                for key,value in zip(('x','y','width','height'),(rng.uniform(-20000,20000),rng.uniform(-20000,20000),rng.uniform(20,2000),rng.uniform(20,2000))):b.set(key,str(value))
            for point in tree.xpath('.//di:waypoint',namespaces=NS):
                point.set('x',str(rng.uniform(-20000,20000)));point.set('y',str(rng.uniform(-20000,20000)))
            altered=td/'altered.bpmn';first=td/'first.bpmn';second=td/'second.bpmn';tree.write(str(altered));erase_geometry(source,first);erase_geometry(altered,second)
            passed=digest(first)==digest(second) and semantic_equality(source,first) and equal(source,first)
            if not passed:raise RuntimeError('DI erasure leak: '+source.stem)
            results.append({'id':source.stem,'status':'passed','canonical_geometry_sha256':digest(first),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps({'protocol':'all original positions, sizes, waypoints and caption bounds randomized; identical canonical planner input required; supported source model and DI structure frozen','seed':2371,'results':results},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
