"""Jitter current DI and discard original wire corridors; retain all business XML."""
from pathlib import Path
from tempfile import TemporaryDirectory
from random import Random
import argparse,json,sys,zipfile
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src/v23'),str(Path(__file__).resolve().parents[1]/'src/v22')]
from bpmn_refkit.model import read_bpmn,set_di
from bpmn_refkit.geometry import compress
from bpmn_universal.contract import semantic_equality
from bpmn_v23.freeze import equal


def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--indices',nargs='+',type=int,default=[1,6,11,16,21,26]);p.add_argument('--magnitude',type=float,default=.12);a=p.parse_args()
    if a.archive.resolve()==a.output.resolve():p.error('Separate output required')
    if not 0<a.magnitude<=.3:p.error('magnitude must be in (0,.3]')
    with zipfile.ZipFile(a.archive) as z,TemporaryDirectory() as td,zipfile.ZipFile(a.output,'w',zipfile.ZIP_DEFLATED) as out:
        names=[n for n in z.namelist() if n.lower().endswith('.bpmn')];manifest=[]
        for index in a.indices:
            name=names[index-1];source=Path(td)/'source.bpmn';target=Path(td)/'perturbed.bpmn';source.write_bytes(z.read(name))
            tree,root,_,plane,nodes,seq,assocs,docs,_,_,boxes,_=read_bpmn(source);rng=Random(23+index);changed=dict(boxes)
            for n in sorted(nodes|docs):
                x,y,w,h=boxes[n];changed[n]=(x+rng.uniform(-1,1)*w*a.magnitude,y+rng.uniform(-1,1)*h*a.magnitude,w,h)
            paths={}
            for eid,u,v,_ in seq+assocs:
                a1,b=changed[u],changed[v];sx,sy=a1[0]+a1[2]/2,a1[1]+a1[3]/2;tx,ty=b[0]+b[2]/2,b[1]+b[3]/2
                if abs(tx-sx)>abs(ty-sy):
                    start=(a1[0]+a1[2] if tx>sx else a1[0],sy);end=(b[0] if tx>sx else b[0]+b[2],ty);mid=(start[0]+end[0])/2
                    paths[eid]=compress([start,(mid,sy),(mid,ty),end])
                else:
                    start=(sx,a1[1]+a1[3] if ty>sy else a1[1]);end=(tx,b[1] if ty>sy else b[1]+b[3]);mid=(start[1]+end[1])/2
                    paths[eid]=compress([start,(sx,mid),(tx,mid),end])
            set_di(root,plane,changed,paths);tree.write(str(target),encoding='utf-8',xml_declaration=True)
            assert semantic_equality(source,target) and equal(source,target)
            out.writestr(f'{index:02}--'+name,target.read_bytes());manifest.append({'index':index,'file':name,'semantics_unchanged':True,'DI_structure_unchanged':True})
        out.writestr('perturbation_manifest.json',json.dumps({'seed_rule':'23 + original file index','magnitude':a.magnitude,'original_routes_discarded':True,'models':manifest},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
