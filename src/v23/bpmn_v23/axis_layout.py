"""Retain reading axes, then solve row separation and column constraints.

This is DI refinement, not coordinate-free graph reconstruction. No archived
coordinates, file names or process IDs are used; only the current input DI.
"""
from collections import defaultdict
from statistics import median
import math
from bpmn_refkit.model import TAG_TASK,TAG_EVENT,TAG_GATE
from .human_search import HumanStyleBackend
from .patterns import analyze
from .readability import graph_returns
from .typography import wrap
from .reference_style import percentile,profile


def clusters(values,tolerance):
    groups=[];mapping={}
    for n,x in sorted(values.items(),key=lambda r:(r[1],r[0])):
        if not groups or x-groups[-1][0]>tolerance:groups.append([x,[]])
        groups[-1][1].append(n);mapping[n]=len(groups)-1
    return mapping


def semantic_axes(values,initial,edges,tolerance,blocked=None):
    """Recover a shared axis from near-aligned connected objects, with a span cap.

    A connected chain cannot drag unrelated far-away nodes onto one axis.
    Column unions also cannot merge two objects occupying the same row.
    """
    parent={g:g for g in set(initial.values())};members=defaultdict(set)
    for n,g in initial.items():members[g].add(n)
    def root(g):
        while parent[g]!=g:g=parent[g]
        return g
    for u,v in sorted(edges,key=lambda e:(abs(values[e[0]]-values[e[1]]),e)):
        a,b=root(initial[u]),root(initial[v])
        if a==b:continue
        joined=members[a]|members[b]
        if max(values[n] for n in joined)-min(values[n] for n in joined)>tolerance:continue
        if blocked is not None and len({blocked[n] for n in joined})!=len(joined):continue
        parent[b]=a;members[a]=joined
    ids=sorted({root(g) for g in parent},key=lambda g:(median(values[n] for n in members[g]),g))
    order={g:i for i,g in enumerate(ids)}
    return {n:order[root(initial[n])] for n in values}


def axis_proposal(nodes,docs,seq,assocs,member,lanes,original,gap=28,caption_reserve=1.0,start_above=False,responsive=False,attachment_owners=()):
    motifs=analyze(nodes,seq,member,original);objects=nodes|docs
    source_tasks=[original[n] for n,o in nodes.items() if o['kind'] in TAG_TASK]
    sw=median(b[2] for b in source_tasks) if source_tasks else 200
    sh=median(b[3] for b in source_tasks) if source_tasks else 80
    taskw=max(profile()['task_width_p75'],min(260,percentile([b[2] for b in source_tasks],.75) or 220))
    taskh=max(64,max((math.ceil((len(wrap(o.get('name',''),taskw-24,13))*18+24+(14 if o['kind'] in ('callActivity','subProcess') else 0))/8)*8 for o in nodes.values() if o['kind'] in TAG_TASK),default=80))
    owners={}
    for d in docs:
        links=[v if u==d else u for _,u,v,_ in assocs if d in (u,v)]
        links=[n for n in links if n in nodes]
        if not links:raise ValueError('Document without a visual owner')
        owners[d]=min(links,key=lambda n:abs(original[d][0]-original[n][0])+abs(original[d][1]-original[n][1]))
    membership={**member,**{d:member[owner] for d,owner in owners.items()}}
    sizes={};frames={};above={};below={}
    for n,o in objects.items():
        if o['kind'] in TAG_TASK:
            if responsive:
                from .typography import task_layout
                w,h=original[n][2:];fit=task_layout(o.get('name',''),original[n],o['kind'])
                if not fit['fits']:h=max(h,fit['required_height'])
            else:w,h=taskw,taskh
        else:w,h=original[n][2:]
        sizes[n]=(w,h);caption=0;fw=w
        if responsive and o['kind']=='startEvent' and o.get('name'):fw=max(w,140)
        if n in docs or o['kind'] in TAG_GATE|TAG_EVENT:
            caption=len(wrap(o.get('name',''),150,12))*17+6 if o.get('name') else 0
            # Captions use the free bay below the row, not a mandatory
            # 160px horizontal box between consecutive steps.
        frames[n]=fw;above[n]=h/2;below[n]=h/2+((caption+12)*caption_reserve if caption else 0)
        if n in attachment_owners:
            count=attachment_owners.get(n,1) if isinstance(attachment_owners,dict) else 1
            above[n]+=math.ceil(count/2)*72+8
            below[n]+=(math.floor(count/2)*72+8 if count>1 else 0)
    cx={n:original[n][0]+original[n][2]/2 for n in objects}
    cy={n:original[n][1]+original[n][3]/2 for n in objects}
    links=[(u,v) for _,u,v,_ in seq+assocs]
    rows={};orders={}
    for lane in lanes:
        values={n:original[n][1]+original[n][3]/2 for n in objects if membership[n]==lane}
        ids=clusters(values,sh*.22)
        horizontal=[(u,v) for u,v in links if u in values and v in values and abs(cx[u]-cx[v])>=sw*.5 and abs(cy[u]-cy[v])<=sh*.4]
        ids=semantic_axes(values,ids,horizontal,sh*.4)
        rows.update({n:(lane,r) for n,r in ids.items()});orders[lane]=sorted(set(ids.values()))
    cols=clusters(cx,sw*.12)
    vertical=[(u,v) for u,v in links if abs(cy[u]-cy[v])>=sh*.75 and abs(cx[u]-cx[v])<=sw*.3]
    cols=semantic_axes(cx,cols,vertical,sw*.3,blocked=rows)
    # A global axis can be shared by objects in different roles/rows. Only
    # consecutive objects sharing a row impose a width separation constraint.
    constraints=defaultdict(list);byrow=defaultdict(list)
    for n,r in rows.items():byrow[r].append(n)
    for r,ids in byrow.items():
        ordered=sorted(ids,key=lambda n:(cols[n],original[n][0],n))
        for a,b in zip(ordered,ordered[1:]):
            if cols[a]==cols[b]:raise ValueError('Input row has overlapping axis anchors')
            constraints[cols[b]].append((cols[a],frames[a]/2+frames[b]/2+gap))
    caption_specs={}
    if start_above:
        for r,ids in byrow.items():
            half=max(sizes[n][1]/2 for n in ids)
            for n in ids:
                if nodes.get(n,{}).get('kind')=='startEvent' and nodes[n].get('name'):
                    hcap=len(wrap(nodes[n]['name'],212,12))*17+6
                    above[n]=half+hcap+12;below[n]=sizes[n][1]/2;caption_specs[n]=(half,hcap)
    x={};origin=min(original[l][0] for l in lanes)+70
    for c in sorted(set(cols.values())):
        half=max(frames[n]/2 for n in objects if cols[n]==c)
        x[c]=max(origin+half,x.get(c-1,origin)+16)
        for previous,distance in constraints[c]:x[c]=max(x[c],x[previous]+distance)
    width=max(x[cols[n]]+frames[n]/2 for n in objects)-min(original[l][0] for l in lanes)+30
    out={};laneorder=sorted(lanes,key=lambda l:original[l][1]);cursor=65
    for lane in laneorder:
        top=cursor;cursor+=24
        for row in orders[lane]:
            ids=byrow[lane,row];upper=max(above[n] for n in ids);lower=max(below[n] for n in ids)
            cy=cursor+upper
            for n in ids:
                w,h=sizes[n];out[n]=(x[cols[n]]-w/2,cy-h/2,w,h)
            cursor=cy+lower+gap
        cursor+=12;lx=original[lane][0];out[lane]=(lx,top,width,cursor-top)
    for n,b in original.items():
        if n in out:continue
        xx,yy,w,h=b;out[n]=(min(original[l][0] for l in lanes)-30,65,width+30,cursor-65)
    captions={}
    for n,(half,hcap) in caption_specs.items():
        xx,yy,w,h=out[n];cy=yy+h/2
        captions[n]=(max(out[membership[n]][0]+54,xx),cy-half-hcap-12,220,hcap)
    feedback=graph_returns(nodes,seq)
    def priority(edge):
        i,u,v,_=edge;a,b=out[u],out[v]
        compatible=max(a[0],b[0])<min(a[0]+a[2],b[0]+b[2]) or max(a[1],b[1])<min(a[1]+a[3],b[1]+b[3])
        distance=abs(a[0]-b[0])+abs(a[1]-b[1])
        return (i in feedback,not compatible,distance,i)
    report={'external_engine':'axis-separation-constraints','family':'reading-axis-refinement','pairs':motifs['pairs'],'main_macros':[n for c in motifs['components'] for n in c['backbone']],
            'feedback_edges':sorted(feedback),'document_owners':owners,'role_order':laneorder,
            'routing_priority':[i for i,_,_,_ in sorted(seq,key=priority)]+[i for i,_,_,_ in assocs],
            'reserved_captions':captions,'mapped_axes':{'x':[[median(original[n][0]+original[n][2]/2 for n in objects if cols[n]==c),x[c]] for c in sorted(x)],'y':[[median(original[n][1]+original[n][3]/2 for n in objects if rows[n]==r),median(out[n][1]+out[n][3]/2 for n in objects if rows[n]==r)] for r in sorted(byrow,key=lambda r:median(original[n][1]+original[n][3]/2 for n in byrow[r]))]},'axis_columns':cols,'axis_rows':{n:list(r) for n,r in rows.items()},'gap':gap,'caption_reserve':caption_reserve,'task_size':[taskw,taskh],
            'method':'source reading axes, full-text envelopes, DAG separation constraints; geometry hints, not a copied reference'}
    return out,report


class AxisBackend(HumanStyleBackend):
    name='v23-reading-axis-constraints'
    def __init__(self,**kwargs):super().__init__(orient_decisions=False,**kwargs)
    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        for gap,reserve in ((20,0),(32,1)):
            try:boxes,report=axis_proposal(nodes,docs,seq,assocs,member,lanes,original,gap,reserve,getattr(self,'axis_start_above',False))
            except ValueError:continue
            yield f'reading-axes-gap-{gap}-labels-{reserve}-corridors',boxes,{**report,'preserve_corridors':True}
            yield f'reading-axes-gap-{gap}-labels-{reserve}',boxes,report
