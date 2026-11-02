"""Rigid lane-content offsets: improve handoff port alignment without shuffling steps."""
from itertools import product
from statistics import median
from bpmn_refkit.model import read_bpmn,TAG_TASK
from .human_search import HumanStyleBackend
from .patterns import analyze
from .readability import graph_returns


def offset_options(nodes,seq,members,boxes,lanes,limit=2):
    lane_list=sorted(lanes,key=lambda n:boxes[n][1]);task_width=median(boxes[n][2] for n,o in nodes.items() if o['kind'] in TAG_TASK);step=round(task_width*.35/5)*5
    returns=graph_returns(nodes,seq)
    def cost(values):
        shifts=dict(zip(lane_list,values));total=0
        for i,u,v,_ in seq:
            if members[u]==members[v]:continue
            a,b=boxes[u],boxes[v];ax=a[0]+shifts[members[u]];bx=b[0]+shifts[members[v]]
            overlap_x=min(ax+a[2],bx+b[2])-max(ax,bx);overlap_y=min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1])
            distance=max(0,-overlap_x)+max(0,-overlap_y)
            total+=(.25 if i in returns else 1)*((100 if overlap_x<8 and overlap_y<8 else 0)+distance*.05)
        return total+max(values)*.1+sum(values)*.02
    if len(lane_list)<=7:options={tuple(v-min(values) for v in values) for values in product((0,step,step*2),repeat=len(lane_list))}
    else:
        current=(0,)*len(lane_list);options={current}
        for _ in range(3):
            for index in range(len(lane_list)):
                trials=[current[:index]+(v,)+current[index+1:] for v in (0,step,step*2)];current=min(trials,key=cost);options.update(trials)
    ranked=sorted((cost(v),v) for v in options if any(v))
    result=[]
    for value,vs in ranked:
        if not result or sum(a!=b for a,b in zip(vs,result[0][1]))>=2:result.append((value,vs))
        if len(result)>=limit:break
    return [{'offsets':dict(zip(lane_list,vs)),'proxy_cost':value,'step':step} for value,vs in result]


class LaneAlignmentBackend(HumanStyleBackend):
    name='v23-rigid-lane-port-alignment'
    def __init__(self,**kwargs):
        super().__init__(orient_decisions=False,**kwargs)
        if self.incumbent is None:raise ValueError('Lane alignment requires an audited incumbent layout')
    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        parsed=read_bpmn(self.incumbent);boxes=parsed[-2];motifs=analyze(nodes,seq,member,original);owners={}
        for d in docs:
            linked=[v if u==d else u for _,u,v,_ in assocs if d in (u,v)];linked=[n for n in linked if n in nodes]
            if not linked:raise ValueError('Document without a visual activity link')
            owners[d]=min(linked,key=lambda n:abs(boxes[d][0]-boxes[n][0])+abs(boxes[d][1]-boxes[n][1]))
        for index,proposal in enumerate(offset_options(nodes,seq,member,boxes,lanes)):
            offsets=proposal['offsets'];growth=max(offsets.values());new=dict(boxes)
            for n in nodes|docs:
                lane=member[n] if n in nodes else member[owners[n]];x,y,w,h=boxes[n];new[n]=(x+offsets[lane],y,w,h)
            for lane in lanes:
                x,y,w,h=boxes[lane];new[lane]=(x,y,w+growth,h)
            for n,b in boxes.items():
                if n not in nodes and n not in docs and n not in lanes:
                    x,y,w,h=b;new[n]=(x,y,w+growth,h)
            report={'family':'lane-port-alignment','external_engine':'rigid-lane-port-alignment','pairs':motifs['pairs'],'main_macros':[n for c in motifs['components'] for n in c['backbone']],'feedback_edges':sorted(graph_returns(nodes,seq)),'slots':{n:(0,0) for n in nodes},'document_owners':owners,'role_order':sorted(lanes,key=lambda l:boxes[l][1]),'alignment':proposal}
            yield f'lane-port-alignment-{index+1}',new,report
