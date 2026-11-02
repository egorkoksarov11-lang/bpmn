"""Cold reconstruction with wider generated channels; no input DI is reused."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_v23 import scratch_layout as sl
from bpmn_v23.pipeline import run
Original=sl.GraphChannelsBackend
class SpacedGraph(Original):
    name='v23-semantic-layers-wider-channels'
    def __init__(self,**kwargs):
        super().__init__(**kwargs);self.max_search_seconds=45
    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        for name,boxes,report in super().placements(nodes,docs,seq,assocs,member,lanes,original):
            if not name.startswith('semantic-'):continue
            for factor in (1.6,2.0):
                def centre_scale(b):
                    x,y,w,h=b;return ((x+w/2)*factor-w/2,(y+h/2)*factor-h/2,w,h)
                new={n:centre_scale(b) if n in nodes or n in docs else tuple(v*factor for v in b) for n,b in boxes.items()}
                captions={n:centre_scale(b) for n,b in report.get('reserved_captions',{}).items()}
                yield name+'-spacing-'+str(factor),new,{**report,'reserved_captions':captions,'spacing_factor':factor,'spacing_policy':'scale generated centres; retain measured glyph/text sizes; no original positions'}
def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--candidate-timeout',type=int,default=60)
    args=parser.parse_args()
    sl.GraphChannelsBackend=SpacedGraph
    try:
        print(json.dumps(run(args.input,args.output_dir,sl.ScratchBackend(candidate_seconds=args.candidate_timeout)),indent=2))
    finally:
        sl.GraphChannelsBackend=Original

if __name__=='__main__':main()
