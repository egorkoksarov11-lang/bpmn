"""Use one measured reading objective before and after geometric refinement."""
from bpmn_refkit.model import read_bpmn
from .block_layout import WholeBlockBackend
from .narrative_planner import reading_measure


class ReadableBlocksBackend(WholeBlockBackend):
    name='v23.8-readable-turns'
    selection_policy='human-turns-measured-reading-v1'
    unified_reading=True

    def candidate_rank(self,path,boxes,paths,uv,nodes,docs,seq):
        previous=super().candidate_rank(path,boxes,paths,uv,nodes,docs,seq)
        quality=reading_measure(read_bpmn(path))
        return round(quality['score']/max(1,len(seq)),6),previous[1],previous[2]
