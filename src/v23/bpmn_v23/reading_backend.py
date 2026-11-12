"""Use one measured reading objective before and after geometric refinement."""
from bpmn_refkit.model import read_bpmn
from .block_layout import WholeBlockBackend
from .narrative_planner import reading_measure


class ReadableBlocksBackend(WholeBlockBackend):
    name='v23.8-early-composition-plan'
    selection_policy='human-turns-measured-reading-v1'
    unified_reading=True

    def candidate_rank(self,path,boxes,paths,uv,nodes,docs,seq):
        previous=super().candidate_rank(path,boxes,paths,uv,nodes,docs,seq)
        quality=reading_measure(read_bpmn(path))
        return round(quality['score']/max(1,len(seq)),6),previous[1],previous[2]

    def _initial_families(self,nodes,docs,seq,assocs,member,lanes,original):
        from .composition_plan import plan,materialize
        import time
        try:selected,self.preplanning_report=plan(nodes,docs,seq,assocs,member,lanes,original)
        except ValueError as error:selected=[];self.preplanning_report={'status':'fallback','reason':str(error),'source_geometry_used':False}
        old=iter(super()._initial_families(nodes,docs,seq,assocs,member,lanes,original))
        first=next(old,None)
        if first is not None:yield first
        attempts=[]
        for index,p in enumerate(selected):
            started=time.monotonic()
            try:
                boxes,report=materialize(p,nodes,docs,seq,assocs,member,lanes,original)
                attempts.append({'index':index,'status':'materialized','seconds':round(time.monotonic()-started,4)})
                self.preplanning_report['materialization']=attempts
                yield f'early-plan-{index}-columns-{p["columns"]}',boxes,report
            except ValueError as error:
                attempts.append({'index':index,'status':'rejected','seconds':round(time.monotonic()-started,4),'reason':str(error)})
        self.preplanning_report['materialization']=attempts
        yield from old
