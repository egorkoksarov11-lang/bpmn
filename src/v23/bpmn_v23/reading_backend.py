"""Use one measured reading objective before and after geometric refinement."""
from bpmn_refkit.model import read_bpmn
from .block_layout import WholeBlockBackend
from .narrative_planner import reading_measure


class ReadableBlocksBackend(WholeBlockBackend):
    name='v23.9-refined-portfolio'
    selection_policy='post-refinement-portfolio-v1'
    unified_reading=True
    portfolio_width=2

    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        old=iter(super().placements(nodes,docs,seq,assocs,member,lanes,original));seen=set()
        def emit(item):
            name,boxes,report=item;key=(tuple(sorted(boxes.items())),tuple(sorted(report.get('reserved_captions',{}).items())))
            if key not in seen:seen.add(key);yield item
        for _ in range(4):
            item=next(old,None)
            if item is not None:yield from emit(item)
        # Complete the basic orientation portfolio before minor coordinate
        # variants spend the candidate quota. These are graph-only constructors.
        from .episode_layout import episode_proposal,reserve_flow_labels
        from .lane_ordering import reorder_lanes
        for rows,seed,vertical in ((2,23,False),(3,71,True)):
            try:
                boxes,report=episode_proposal(nodes,docs,seq,assocs,member,lanes,original,rows=rows,seed=seed,vertical=vertical)
                report=reserve_flow_labels(boxes,report,nodes,docs,seq,lanes)
                boxes,report=reorder_lanes(boxes,report,nodes,docs,seq,member,lanes,self.role_order or 'auto')
                report['candidate_family']=f'episode-orientation-{int(vertical)}'
                yield from emit((f'portfolio-episode-rows-{rows}-vertical-{int(vertical)}',boxes,report))
            except ValueError as error:self.placement_failures.append({'family':'portfolio-orientation','reason':str(error)})
        for item in old:yield from emit(item)

    def candidate_rank(self,path,boxes,paths,uv,nodes,docs,seq):
        previous=super().candidate_rank(path,boxes,paths,uv,nodes,docs,seq)
        self._last_legacy_rank=previous
        left=min(boxes[n][0] for n in nodes);top=min(boxes[n][1] for n in nodes)
        self._last_signature=tuple((n,round((boxes[n][0]-left)/20),round((boxes[n][1]-top)/20)) for n in sorted(nodes))
        quality=reading_measure(read_bpmn(path))
        return round(quality['score']/max(1,len(seq)),6),previous[1],previous[2]

    def capture_candidate(self,entry,safe):
        if not hasattr(self,'portfolio_records'):self.portfolio_records=[]
        self.portfolio_records.append({'entry':entry,'legacy_rank':self._last_legacy_rank,'signature':self._last_signature,
            'family':entry[4].get('candidate_family',entry[4].get('external_engine',entry[1])),'safe':safe})
