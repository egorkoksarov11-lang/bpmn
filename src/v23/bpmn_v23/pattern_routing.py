"""Reserve the semantic spine, then nest correction returns in phase gutters."""
from collections import defaultdict
from bpmn_refkit.geometry import compress


def routing_order(report,nodes,seq,assocs,boxes=None):
    pairs=report.get('pairs',{});owner={n:n for n in nodes}
    for a,b in pairs.items():owner[b]=a
    feedback=set(report['feedback_edges']);priority=[];seen=set()
    def add(ids):
        for eid in ids:
            if eid not in seen:priority.append(eid);seen.add(eid)
    add(eid for eid,u,v,_ in seq if pairs.get(u)==v)
    for a,b in zip(report['main_macros'],report['main_macros'][1:]):add(eid for eid,u,v,_ in seq if owner[u]==a and owner[v]==b)
    add(eid for eid,_,_,_ in assocs)
    def span(edge):
        _,u,v,_=edge
        if boxes:return abs(boxes[u][0]-boxes[v][0])+abs(boxes[u][1]-boxes[v][1])*.2
        return abs(report['slots'][owner[u]][0]-report['slots'][owner[v]][0])
    # Outer return envelopes before inner ones is the usual manual loop pattern.
    add(e[0] for e in sorted((e for e in seq if e[0] in feedback),key=lambda e:(-span(e),e[0])))
    add(eid for eid,_,_,_ in seq)
    return priority


def hints_factory(report,boxes,seq,membership,lane_boxes):
    uv={i:(u,v) for i,u,v,_ in seq};feedback=set(report['feedback_edges']);owner={n:n for n in boxes}
    for a,b in report.get('pairs',{}).items():owner[b]=a
    ordered=defaultdict(list)
    for eid in sorted(feedback,key=lambda e:(-abs(boxes[uv[e][0]][0]-boxes[uv[e][1]][0]),e)):
        ordered[membership.get(uv[eid][0])].append(eid)
    ranks={eid:i for values in ordered.values() for i,eid in enumerate(values)}
    def hints(eid,paths):
        if eid not in uv:return []
        u,v=uv[eid];a=boxes[u];b=boxes[v];lane=membership.get(u)
        if lane not in lane_boxes:return []
        x,y,w,h=a;xx,yy,ww,hh=b;result=[]
        # Column side corridors stay clear of tasks and their local decisions.
        stride=report.get('column_stride',340);origin=report.get('body_x',170);task_width=report.get('task_width',220)
        source_col=report['slots'][owner[u]][0];target_col=report['slots'][owner[v]][0]
        source_x=origin+source_col*stride+stride-25
        target_x=origin+target_col*stride+task_width+15 if owner[v]!=v else origin+target_col*stride-20
        ly=lane_boxes[lane][1];lh=lane_boxes[lane][3]
        channels=[ly+10+7*ranks.get(eid,0),ly+lh-12,min(y,yy)-18,max(y+h,yy+hh)+18]
        if eid not in feedback:channels=[min(y,yy)-18,max(y+h,yy+hh)+18]
        for cy in channels:
            for shift in (0,7,14):
                sx=source_x+shift;tx=target_x-shift
                target=(xx,yy+hh/2)
                source=(x+w,y+h/2)
                result.append(compress([source,(sx,source[1]),(sx,cy),(tx,cy),(tx,target[1]),target]))
                for from_top in (True,False):
                    source=(x+w/2,y if from_top else y+h);stub_y=source[1]+(-12 if from_top else 12)
                    result.append(compress([source,(source[0],stub_y),(sx,stub_y),(sx,cy),(tx,cy),(tx,target[1]),target]))
        return result
    return hints
