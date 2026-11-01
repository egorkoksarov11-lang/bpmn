"""Compact phase columns, local chains and correction branches in original lanes."""
from collections import defaultdict
import math
from .patterns import analyze
from .block_optimize import optimize_slots
from .reference_style import profile
from .role_order import candidate_orders,reorder_boxes
from .typography import wrap
from bpmn_refkit.model import TAG_TASK


def _proposals(nodes,docs,seq,assocs,membership,lane_names,original,secondary_rows=1,chain_depths=(2,3),role_variants=2):
    motifs=analyze(nodes,seq,membership,original)
    lanes=sorted(lane_names,key=lambda n:(original[n][1],n))
    # These are the interquartile style dimensions of the supplied 32 examples;
    # full labels may increase task height, never disappear or change content.
    style=profile();taskw=style['task_width_p75'];taskh=max(style['task_height_median'],max((len(wrap(o.get('name',''),taskw-24,13))*18+24+(14 if o['kind'] in ('callActivity','subProcess') else 0) for o in nodes.values() if o['kind'] in TAG_TASK),default=80))
    taskh=math.ceil(taskh/8)*8
    counts=defaultdict(int)
    for n in motifs['macros']:counts[membership.get(n)]+=1
    dominant=max(lanes,key=lambda l:counts[l]) if lanes else None
    neighbours=defaultdict(list)
    for _,u,v,_ in seq:
        a,b=motifs['owner'][u],motifs['owner'][v]
        if a!=b:neighbours[a].append(b);neighbours[b].append(a)
    doc_owners={}
    for d in docs:
        links=[(v if u==d else u) for _,u,v,_ in assocs if d in (u,v)]
        links=[motifs['owner'][n] for n in links if n in motifs['owner']]
        doc_owners[d]=links[0] if links else next(iter(motifs['macros']))
    for depth in chain_depths:
        occupied=set();slots={};component_start=0;main_order=[]
        for component in motifs['components']:
            col=component_start
            for macro in component['backbone']:
                lane=membership.get(macro);cap=depth if lane==dominant else 1
                while sum(1 for c,l,r in occupied if c==col and l==lane)>=cap:col+=1
                row=0
                while (col,lane,row) in occupied:row+=1
                slots[macro]=(col,row)
                if nodes[macro]['kind']!='startEvent':occupied.add((col,lane,row))
                main_order.append(macro)
            remaining=set(component['nodes'])-set(slots)
            while remaining:
                def connected(n):return sum(v in slots for v in neighbours[n])
                macro=max(sorted(remaining),key=lambda n:(connected(n),-original[n][0]))
                lane=membership.get(macro);anchors=[slots[n] for n in neighbours[macro] if n in slots]
                if not anchors:anchors=[(component_start,0)]
                best=None
                for c in range(component_start,max(col+2,component_start+2)):
                    for row in range(depth+3 if lane==dominant else secondary_rows):
                        if (c,lane,row) in occupied:continue
                        cost=sum(abs(c-ac)*2+abs(row-ar) for ac,ar in anchors)+row*(2.5 if lane==dominant else 6)+max(0,c-col)*4
                        option=(cost,row,c)
                        if best is None or option<best:best=option
                _,row,c=best;slots[macro]=(c,row);occupied.add((c,lane,row));remaining.remove(macro);col=max(col,c)
            component_start=max(c for c,_ in slots.values())+1
        slots,placement_optimization=optimize_slots(slots,motifs,seq,membership,lanes)
        # Decide whether the local decision is alongside or below its task.
        main_next={a:b for component in motifs['components'] for a,b in zip(component['backbone'],component['backbone'][1:])}
        vertical={}
        for macro,gate in motifs['pairs'].items():
            nxt=main_next.get(macro)
            vertical[macro]=False
        rows=defaultdict(lambda:defaultdict(lambda:{'height':0,'docs':[]}))
        for macro,(col,row) in slots.items():
            h=taskh if nodes[macro]['kind'] in TAG_TASK else original[macro][3]
            if vertical.get(macro):h+=76
            rows[membership.get(macro)][row]['height']=max(rows[membership.get(macro)][row]['height'],h+55)
        grouped_docs=defaultdict(list)
        for d,macro in doc_owners.items():grouped_docs[macro].append(d)
        doc_extra={macro:(95 if macro in motifs['pairs'] and len(ds)>1 else 55 if macro in motifs['pairs'] or len(ds)>1 else 0) for macro,ds in grouped_docs.items()}
        for macro,extra in doc_extra.items():
            info=rows[membership.get(macro)][slots[macro][1]];info['doc_extra']=max(info.get('doc_extra',0),extra)

        return_counts=defaultdict(int)
        for eid,u,v,_ in seq:
            if eid in motifs['feedback_edges']:return_counts[membership.get(u)]+=1
        reserves={lane:max(0,(return_counts[lane]-3)*7) for lane in lanes}
        lane_top={};row_top={};bounds={};y=65
        ncols=max((c for c,_ in slots.values()),default=0)+1;stride=taskw+120
        for lane in lanes:
            source_caption=max((len(wrap(o.get('name',''),212,12))*17+6 for n,o in nodes.items() if o['kind']=='startEvent' and membership.get(n)==lane),default=0)
            lane_top[lane]=y;cursor=y+20+reserves[lane]+max(0,source_caption-15)
            for row in range(max(rows[lane],default=0)+1):
                row_top[(lane,row)]=cursor;info=rows[lane][row]
                cursor+=max(info['height'],100)+info.get('doc_extra',0)
            h=max(130,cursor-y+15);bounds[lane]=(30,y,ncols*stride+170,h);y+=h
        for macro,(col,row) in slots.items():
            lane=membership.get(macro);x=170+col*stride;yy=row_top[(lane,row)]+22
            if nodes[macro]['kind'] in TAG_TASK:w,h=taskw,taskh
            else:w,h=original[macro][2:]
            bounds[macro]=(x+(taskw-w)/2,yy,w,h)
            if macro in motifs['pairs']:
                gate=motifs['pairs'][macro];gw,gh=original[gate][2:]
                bounds[gate]=(x+(taskw-gw)/2,yy+h+26,gw,gh) if vertical[macro] else (x+taskw+30,yy+(h-gh)/2,gw,gh)
        for macro in main_order:
            if nodes[macro]['kind']=='startEvent':
                nxt=main_next.get(macro)
                if nxt and membership.get(nxt)==membership.get(macro):
                    x,yy,w,h=bounds[nxt];sw,sh=original[macro][2:];bounds[macro]=(x-60,yy+(h-sh)/2,sw,sh)
        # Documents sit in the bay of their owning local block, not on the spine.
        label_anchors={}
        for macro,ds in grouped_docs.items():
            col,row=slots[macro];lane=membership.get(macro);x,yy,w,h=bounds[macro]
            for index,d in enumerate(sorted(ds)):
                dw,dh=original[d][2:]
                if macro not in motifs['pairs'] and index==0:
                    dx=x+taskw+25;dy=yy+4
                    label_anchors[d]=(dx-20,dy+dh+5,80,58)
                else:
                    bay_index=index if macro in motifs['pairs'] else index-1
                    dx=170+col*stride+bay_index*155;dy=row_top[(lane,row)]+max(rows[lane][row]['height'],100)+4
                    label_anchors[d]=(dx+dw+7,dy+2,110,45)
                bounds[d]=(dx,dy,dw,dh)
        # Independent scenarios may start next to the preceding scenario's
        # side document. Shift only a colliding start glyph, not every event.
        for n,info in nodes.items():
            if info['kind']!='startEvent':continue
            x,yy,w,h=bounds[n]
            for shift in range(17):
                candidate=(x+shift,yy,w,h)
                def too_close(other):
                    return min(candidate[0]+w,other[0]+other[2])-max(candidate[0],other[0])>-8 and min(yy+h,other[1]+other[3])-max(yy,other[1])>-8
                if not any(too_close(b) for other,b in bounds.items() if other!=n and (other in nodes or other in docs)):
                    bounds[n]=candidate;break
        # Preserve other containers; flat lanes are the current supported case.
        for n,b in original.items():
            if n not in bounds:bounds[n]=b
        report={'family':'human-patterns','chain_depth':depth,'secondary_rows':secondary_rows,'task_width':taskw,'column_stride':stride,'body_x':170,'columns':ncols,'paired_decisions':len(motifs['pairs']),
                'main_macros':main_order,'feedback_edges':motifs['feedback_edges'],'slots':{n:list(v) for n,v in slots.items()},
                'source_reference_models':32,'pairs':motifs['pairs'],'document_label_anchors':label_anchors,'document_owners':doc_owners,'role_order':lanes,'return_reserves':reserves,'placement_optimization':placement_optimization}
        yield f'human-blocks-{depth}-secondary-{secondary_rows}',bounds,report
        if depth==2:
            for i,role in enumerate(candidate_orders(bounds,nodes,seq,membership,lanes,limit=role_variants)):
                changed=reorder_boxes(bounds,role['order'],nodes,docs,membership,doc_owners)
                info={**report,'role_order':role['order'],'role_optimization':role}
                yield f'human-blocks-{depth}-secondary-{secondary_rows}-roles-{i+1}',changed,info


def proposals(nodes,docs,seq,assocs,membership,lane_names,original,orient_decisions=False):
    if not lane_names or any(n not in membership for n in nodes):return
    for secondary_rows in (1,2):
        for name,boxes,report in _proposals(nodes,docs,seq,assocs,membership,lane_names,original,secondary_rows=secondary_rows,chain_depths=(2,),role_variants=1):
            yield name,boxes,report
            if orient_decisions:
                from .decision_layout import orient
                changed,info=orient(boxes,report,nodes,docs,seq,assocs,membership)
                if info['orientation_changes']:yield name+'-oriented',changed,info
