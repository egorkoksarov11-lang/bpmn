"""Bounded alternating group/role optimization on a generated layout."""
import time
from .window_planner import refine_windows
from .role_refinement import refine_roles


def refine_graph(path,svg,source,seconds=100,max_rounds=2):
    started=time.monotonic();rounds=[]
    for index in range(max_rounds):
        remaining=seconds-(time.monotonic()-started)
        if remaining<2:break
        group=refine_windows(path,svg,source,seconds=min(45,remaining))
        remaining=seconds-(time.monotonic()-started)
        roles=refine_roles(path,svg,source,seconds=min(20,remaining)) if remaining>=1 else {'accepted':False,'reason':'total-budget'}
        rounds.append({'round':index+1,'groups':group,'roles':roles})
        if not group.get('accepted_windows') and not roles.get('accepted'):break
    return {'method':'alternating graph groups, role geometry and routes; stop on stagnation or bounded budget','rounds':rounds,'seconds':round(time.monotonic()-started,3),'names_or_step_numbers_used_for_structure':False}
