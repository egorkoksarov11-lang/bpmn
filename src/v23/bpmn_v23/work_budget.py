"""Scoped routing work quotas; wall deadlines remain emergency safety guards."""
from contextlib import contextmanager
from contextvars import ContextVar

CURRENT=ContextVar('bpmn_routing_work',default=None)


@contextmanager
def routing_work(fixed=False,astar_nodes=12000,adaptive=True):
    state={'fixed':fixed,'astar_node_quota':astar_nodes,'adaptive':adaptive,'astar_calls':0,'astar_expansions':0,'astar_quota_hits':0,'adaptive_joint_calls':0,'maximum_joint_beam':0}
    token=CURRENT.set(state)
    try:yield state
    finally:CURRENT.reset(token)


def current_work():return CURRENT.get()
