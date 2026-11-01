"""Validated, overridable v22 configuration: no hardcoded process IDs."""
from dataclasses import dataclass, field, asdict
from pathlib import Path
import json

@dataclass
class GeometrySettings:
    horizontal_scale:float=.90
    candidate_scales:list[float]=field(default_factory=lambda:[.80,.85,.90,1.0])
    task_gap:float=26.0
    document_gap:float=15.0
    routing_order:str='short-first'
    max_width_growth:float=1.05
    max_avg_flow_length_growth:float=1.35

@dataclass
class SemanticSettings:
    mode:str='strict'  # strict | approved-associations
    approved_association_removals:list[str]=field(default_factory=list)

@dataclass
class OutputSettings:
    svg:bool=True
    png:bool=False
    report:bool=True
    png_width:int=4400

@dataclass
class ExecutionSettings:
    timeout_seconds:int=30

@dataclass
class Settings:
    version:int=22
    geometry:GeometrySettings=field(default_factory=GeometrySettings)
    semantics:SemanticSettings=field(default_factory=SemanticSettings)
    outputs:OutputSettings=field(default_factory=OutputSettings)
    execution:ExecutionSettings=field(default_factory=ExecutionSettings)

    def as_dict(self):return asdict(self)

    @classmethod
    def load(cls,path=None):
        result=cls()
        if path:
            data=json.loads(Path(path).read_text(encoding='utf-8'))
            if set(data)-{'version','geometry','semantics','outputs','execution'}:
                raise ValueError('Unknown top-level config keys: '+str(set(data)-{'version','geometry','semantics','outputs','execution'}))
            if data.get('version',22)!=22:raise ValueError('Config version must be 22')
            for section in ('geometry','semantics','outputs','execution'):
                changes=data.get(section,{})
                obj=getattr(result,section)
                invalid=set(changes)-set(vars(obj))
                if invalid:raise ValueError(f'Unknown keys in {section}: {sorted(invalid)}')
                for k,v in changes.items():setattr(obj,k,v)
        result.check()
        return result

    def check(self):
        g=self.geometry;s=self.semantics
        if not 0.35<=g.horizontal_scale<=1.0:raise ValueError('horizontal_scale must be in [0.35,1]')
        if not g.candidate_scales or any(not isinstance(x,(int,float)) or not .35<=x<=1 for x in g.candidate_scales):
            raise ValueError('candidate_scales must be nonempty and within [0.35,1]')
        if g.task_gap<0 or g.document_gap<0:raise ValueError('Gaps must be nonnegative')
        if g.routing_order not in ('short-first','long-first','name','reverse','flow-first-long','central-first'):
            raise ValueError('Unknown routing_order')
        if g.max_width_growth<1 or g.max_avg_flow_length_growth<1:raise ValueError('growth limits must be >=1')
        if s.mode not in ('strict','approved-associations'):raise ValueError('semantic mode invalid')
        if s.mode=='strict' and s.approved_association_removals:raise ValueError('strict mode forbids removing associations')
        if s.mode=='approved-associations' and not s.approved_association_removals:
            raise ValueError('approved-associations requires explicit IDs')
        if len(s.approved_association_removals)!=len(set(s.approved_association_removals)):
            raise ValueError('Duplicate approved association IDs')
        if not 300<=self.outputs.png_width<=12000:raise ValueError('png_width must be 300..12000')
        if not isinstance(self.execution.timeout_seconds,int) or not 5<=self.execution.timeout_seconds<=600:
            raise ValueError('execution.timeout_seconds must be an integer 5..600')
