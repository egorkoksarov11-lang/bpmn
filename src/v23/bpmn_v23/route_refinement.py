"""Improve wires in a verified incumbent without moving any business object."""
from .human_search import HumanStyleBackend


class RouteRefinementBackend(HumanStyleBackend):
    name='v23-few-bend-return-corridors'
    simplify_routes=True
    return_corridors=True

    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        if self.incumbent is None:raise ValueError('Verified incumbent required')

    def placements(self,*args):
        return iter(())
