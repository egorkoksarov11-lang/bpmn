"""Compare preserved reading axes with graph placements under one hard audit."""
from pathlib import Path
import tempfile,time
from bpmn_refkit.model import read_bpmn
from .quality import score
from .readability import metrics as reading_metrics
from .human_search import HumanStyleBackend
from .axis_layout import AxisBackend


class AdaptiveBackend(HumanStyleBackend):
    name='v23-adaptive-axes-and-graph'
    selection_policy='contact-first-then-empirical-readability; budgeted portfolio'

    def __init__(self,**kwargs):
        super().__init__(orient_decisions=False,**kwargs)
        self.max_search_seconds=max(20,self.candidate_seconds*5)
        self._baseline_limits=None

    def placements(self,*args):
        basis=getattr(self,'_placement_basis',None)
        if basis is not None:args=(*args[:-1],basis)
        for name,boxes,report in AxisBackend.placements(self,*args):
            yield name,boxes,{**report,'route_basis':'verified-incumbent' if basis is not None else 'current-input'}

    def candidate_rank(self,*args):
        base=super().candidate_rank(*args)
        # Crossing count has a physical meaning. It is not hidden behind
        # an improved synthetic style score or a nicer area ratio.
        violation=False
        if self._baseline_limits is not None:
            path,boxes,paths,uv,nodes,docs,seq=args
            reading=reading_metrics(boxes,paths,nodes,seq);limits=self._baseline_limits
            from .pipeline import geometry
            extent=geometry(path)['extent'];area=extent['width']*extent['height']
            violation=(base[1][2]>limits['length']*1.05+.1 or area>limits['extent_area']*1.2 or
                reading['forward_hop_excess']>max(limits['forward_hop_excess']*1.05,limits['forward_hop_excess']+.01) or
                reading['parallel_crowding_per_flow']>limits['parallel_crowding_per_flow']*1.1+.002 or
                reading['hotspot_excess']>limits['hotspot_excess']*1.1+.005)
        return (violation,base[1][0],base[0],base[1][1],base[1][2],base[2])

    def layout(self,source,output,svg):
        from .pipeline import geometry,validate_xml
        from bpmn_universal.contract import semantic_equality
        from .freeze import equal as di_equal
        started=time.monotonic();original_incumbent=self.incumbent;bootstrap=None;guards=None
        try:
            with tempfile.TemporaryDirectory(prefix='adaptive-bootstrap-',dir=Path(output).parent) as td:
                if self.incumbent is None:
                    seed=Path(td)/'seed.bpmn';preview=Path(td)/'seed.svg'
                    try:
                        bootstrap=HumanStyleBackend(candidate_seconds=self.candidate_seconds,orient_decisions=False).layout(source,seed,preview)
                        self.incumbent=seed
                    except (ValueError,RuntimeError,TimeoutError) as error:
                        bootstrap={'failed':str(error)}
                self._placement_basis=None;self.axis_start_above=False
                if self.incumbent is not None:
                    validate_xml(self.incumbent)
                    if not semantic_equality(source,self.incumbent) or not di_equal(source,self.incumbent):raise ValueError('Incumbent freeze violation')
                    current=read_bpmn(source);seed_model=read_bpmn(self.incumbent)
                    uv={i:(u,v) for i,u,v,_ in current[5]+current[6]}
                    reading=reading_metrics(seed_model[-2],seed_model[-1],seed_model[4],seed_model[5]);extent=geometry(self.incumbent)['extent']
                    self._baseline_limits={**{k:reading[k] for k in ('forward_hop_excess','parallel_crowding_per_flow','hotspot_excess')},'length':score(seed_model[-1],uv)[2],'extent_area':extent['width']*extent['height']}
                    # Poor input wires do not imply poor node reading axes.
                    # Recover axes from current nodes/links; keep the verified
                    # incumbent as an output fallback, not a coordinate oracle.
                result=super().layout(source,output,svg)
                guards=self._baseline_limits
        finally:
            self.incumbent=original_incumbent;self._placement_basis=None;self.axis_start_above=False;self._baseline_limits=None
        result['baseline_limits']=guards
        result['nonregression_guards']='wire length +5%, page area +20%, forward jumps +5% or .01, crowding +10% or .002, hotspot +10% or .005; invalid trades lose to incumbent'
        if bootstrap is not None:result['bootstrap']=bootstrap
        result['seconds']=round(time.monotonic()-started,3)
        result['selection_policy']='verified bootstrap, bounded navigation/density/page growth, then contact-first axes'
        return result
