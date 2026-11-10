"""Constrained role-local compaction with wire topology and text attached.

All Y coordinates, object sizes, endpoint offsets and crossing order are held.
Horizontal coordinates are solved together; no iterative neighbour pushing.
Only a cold-generated, already verified diagram may be supplied by the caller.
"""
from pathlib import Path
from collections import defaultdict
import copy,math,tempfile,warnings
from bpmn_refkit.model import read_bpmn,TAG_TASK
from bpmn_universal.contract import NS,BD,DC,DI,Q,semantic_equality
from .scratch_layout import semantic_document_owners
from .freeze import equal
from .di_geometry import update_geometry
from .window_planner import extract_labels
from .quality import path_length


def add_expr(a,b,scale=1.):
    result=dict(a[0])
    for k,v in b[0].items():result[k]=result.get(k,0)+scale*v
    return {k:v for k,v in result.items() if abs(v)>1e-10},a[1]+scale*b[1]


def shift_expr(a,value):return a[0],a[1]+value
def evaluate(expr,values):return expr[1]+sum(v*values[k] for k,v in expr[0].items())


def solve_coordinates(state,axis=0,width_weight=.5):
    from scipy.optimize import linprog
    from scipy.sparse import lil_matrix
    _,root,_,_,nodes,seq,assocs,docs,member,lanes,boxes,paths=state
    owners=semantic_document_owners(nodes,docs,assocs,boxes);actors={n:n for n in nodes};actors.update(owners)
    if len(actors)!=len(nodes)+len(docs) or not lanes:return None,'incomplete-role-model'
    if axis not in (0,1):raise ValueError('Axis must be 0 or 1')
    original_boxes=boxes;labels=extract_labels(root)
    swap=lambda b:(b[1],b[0],b[3],b[2])
    if axis:
        boxes={n:swap(b) for n,b in boxes.items()};paths={i:[(y,x) for x,y in p] for i,p in paths.items()};labels={n:swap(b) for n,b in labels.items()}
    variables=[];bounds=[];cost=[]
    def variable(lo=None,hi=None,weight=0.):
        i=len(variables);variables.append(i);bounds.append((lo,hi));cost.append(weight);return ({i:1.},0.)
    origin=min(boxes[l][0] for l in lanes)
    actor_expr={n:variable((origin+boxes[n][2]/2 if axis else boxes[member[n]][0]+56+boxes[n][2]/2),None,.002) for n in sorted(nodes)}
    obj_expr={n:shift_expr(actor_expr[o],boxes[n][0]-boxes[o][0]-boxes[o][2]/2) for n,o in actors.items()}
    constraints=[];rhs=[]
    def le(a,b,slack=0.):
        expr=add_expr(a,b,-1);constraints.append(expr[0]);rhs.append(slack-expr[1])
    def eq(a,b):le(a,b,.001);le(b,a,.001)
    bands={}
    if axis:
        previous=None
        for lane in sorted(lanes,key=lambda n:(boxes[n][0],n)):
            start=variable(origin,None);end=variable(origin,None)
            eq(start,previous if previous is not None else ({},origin));le(shift_expr(start,96),end)
            bands[lane]=(start,end);previous=end
        for n,expr in obj_expr.items():
            lane=member[actors[n]];start,end=bands[lane]
            le(shift_expr(start,8),expr);le(shift_expr(expr,boxes[n][2]+8),end)
    point_expr={};vertical=[];horizontal=[];flow_ids={i for i,*_ in seq};uv={i:(u,v) for i,u,v,*_ in seq+assocs}
    for eid,ps in paths.items():
        if eid not in uv:continue
        parent=list(range(len(ps)))
        def find(i):
            while parent[i]!=i:i=parent[i]
            return i
        for i,(a,b) in enumerate(zip(ps,ps[1:])):
            if abs(a[0]-b[0])<.01:parent[find(i+1)]=find(i)
        runs={find(i) for i in range(len(ps))};expressions={r:variable(0,None) for r in runs}
        ex=[expressions[find(i)] for i in range(len(ps))];u,v=uv[eid]
        eq(ex[0],shift_expr(obj_expr[u],ps[0][0]-boxes[u][0]));eq(ex[-1],shift_expr(obj_expr[v],ps[-1][0]-boxes[v][0]))
        point_expr[eid]=ex
        for i,(a,b) in enumerate(zip(ps,ps[1:])):
            if abs(a[0]-b[0])<.01 and abs(a[1]-b[1])>.01:vertical.append((eid,i,ex[i],a,b))
            elif abs(a[1]-b[1])<.01 and abs(a[0]-b[0])>.01:
                left,right=(ex[i],ex[i+1]) if a[0]<b[0] else (ex[i+1],ex[i]);le(left,right,-min(12,abs(a[0]-b[0])))
                # Horizontal sequence length is exact, not an endpoint estimate.
                weight=1. if eid in flow_ids else .25
                for k,val in add_expr(right,left,-1)[0].items():cost[k]+=weight*val
                horizontal.append((eid,i,left,right,a,b))
    label_expr={};objects=[]
    for n in actors:
        x,y,w,h=boxes[n];objects.append((n,obj_expr[n],x,y,w,h,False))
    for n,(x,y,w,h) in labels.items():
        if n in nodes and nodes[n]['kind'] in TAG_TASK:continue
        if n in obj_expr:expr=shift_expr(obj_expr[n],x-boxes[n][0])
        elif n in paths and n in point_expr:
            ps=paths[n];cx,cy=x+w/2,y+h/2
            def distance(index):
                a,b=ps[index:index+2];px=max(min(a[0],b[0]),min(max(a[0],b[0]),cx));py=max(min(a[1],b[1]),min(max(a[1],b[1]),cy));return math.hypot(cx-px,cy-py)
            i=min(range(len(ps)-1),key=distance);a,b=ps[i:i+2]
            f=max(0,min(1,(cx-a[0])/(b[0]-a[0]))) if abs(b[0]-a[0])>.01 else .5
            expr=add_expr(({},0.),point_expr[n][i],1-f);expr=add_expr(expr,point_expr[n][i+1],f)
            old=a[0]*(1-f)+b[0]*f;expr=shift_expr(expr,x-old)
        else:continue
        label_expr[n]=expr;objects.append(('__label_'+n,expr,x,y,w,h,True))
        if axis and n in actors:
            start,end=bands[member[actors[n]]];le(shift_expr(start,8),expr);le(shift_expr(expr,w+8),end)
    # Preserve only the ordering of objects that actually overlap vertically.
    for i,a in enumerate(objects):
        na,ea,xa,ya,wa,ha,la=a
        for b in objects[i+1:]:
            nb,eb,xb,yb,wb,hb,lb=b
            if min(ya+ha,yb+hb)-max(ya,yb)<=.01:continue
            gap=24 if na in nodes and nb in nodes else 8
            if xa+wa<=xb+.01:le(shift_expr(ea,wa),eb,-min(gap,max(0,xb-xa-wa)))
            elif xb+wb<=xa+.01:le(shift_expr(eb,wb),ea,-min(gap,max(0,xa-xb-wb)))
            else:eq(add_expr(ea,eb,-1),({},xa-xb)) # Allowed empty contour corners.
    for eid,index,expr,a,b in vertical:
        u,v=uv[eid];top,bottom=sorted((a[1],b[1]))
        for n,ox,x,y,w,h,islabel in objects:
            if n==u and index==0 or n==v and index==len(paths[eid])-2:continue
            if min(bottom,y+h)-max(top,y)<=.01:continue
            if a[0]<=x+.01:le(expr,ox,-min(2 if islabel else 8,max(0,x-a[0])))
            elif a[0]>=x+w-.01:le(shift_expr(ox,w),expr,-min(2 if islabel else 8,max(0,a[0]-x-w)))
        for other,j,ee,c,d in vertical:
            if (other,j)<=(eid,index) or min(bottom,max(c[1],d[1]))-max(top,min(c[1],d[1]))<=.01:continue
            if abs(a[0]-c[0])<.01:eq(expr,ee)
            elif a[0]<c[0]:le(expr,ee,-min(12,c[0]-a[0]))
            else:le(ee,expr,-min(12,a[0]-c[0]))
        for other,j,left,right,c,d in horizontal:
            if other==eid or not top+.01<c[1]<bottom-.01:continue
            lo,hi=sorted((c[0],d[0]))
            if a[0]<lo-.01:le(expr,left,-min(4,lo-a[0]))
            elif a[0]>hi+.01:le(right,expr,-min(4,a[0]-hi))
            else:le(left,expr);le(expr,right)
    for eid,index,left,right,a,b in horizontal:
        u,v=uv[eid];lo,hi=sorted((a[0],b[0]))
        for n,ox,x,y,w,h,islabel in objects:
            if n==u and index==0 or n==v and index==len(paths[eid])-2:continue
            if not y+.01<a[1]<y+h-.01:continue
            if hi<=x+.01:le(right,ox,-min(2 if islabel else 8,max(0,x-hi)))
            elif lo>=x+w-.01:le(shift_expr(ox,w),left,-min(2 if islabel else 8,max(0,lo-x-w)))
    maximum=variable(0,None,width_weight)
    header_right=origin-8 if axis else max(boxes[l][0]+52 for l in lanes)
    if axis:
        for start,end in bands.values():le(end,maximum)
    for n,expr,x,y,w,h,islabel in objects:
        le(shift_expr(expr,w),maximum)
        le(({},header_right+8),expr)
    for ex in point_expr.values():
        for expr in ex:
            le(expr,maximum)
            le(({},header_right+8),expr)
    matrix=lil_matrix((len(constraints),len(variables)))
    for i,values in enumerate(constraints):
        for j,value in values.items():matrix[i,j]=value
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore',message='Unrecognized options detected')
        result=linprog(cost,A_ub=matrix.tocsr(),b_ub=rhs,bounds=bounds,method='highs',options={'threads':1,'time_limit':4.})
    if not result.success:return None,'constraint-system-infeasible'
    values=result.x;new=dict(boxes)
    for n,expr in obj_expr.items():new[n]=(round(evaluate(expr,values),2),boxes[n][1],*boxes[n][2:])
    caps={n:(round(evaluate(e,values),2),labels[n][1],*labels[n][2:]) for n,e in label_expr.items()}
    routes={eid:[(round(evaluate(expr,values),2),ps[i][1]) for i,expr in enumerate(point_expr[eid])] if eid in point_expr else ps for eid,ps in paths.items()}
    if axis:
        new={n:swap(b) for n,b in new.items()};caps={n:swap(b) for n,b in caps.items()};routes={i:[(y,x) for x,y in ps] for i,ps in routes.items()}
        for lane,(start,end) in bands.items():
            x,y,w,h=original_boxes[lane];top=round(evaluate(start,values),2);bottom=round(evaluate(end,values),2);new[lane]=(x,top,w,round(bottom-top,2))
        first=min(new[l][1] for l in lanes);bottom=max(new[l][1]+new[l][3] for l in lanes)
        for n in set(original_boxes)-actors.keys()-lanes.keys():
            x,y,w,h=original_boxes[n];new[n]=(x,min(y,first),w,bottom-min(y,first))
        return (new,caps,routes),None
    right=max([b[0]+b[2] for n,b in new.items() if n in actors]+[b[0]+b[2] for b in caps.values()]+[x for ps in routes.values() for x,y in ps])+24
    for n in set(boxes)-actors.keys():
        x,y,w,h=boxes[n];new[n]=(x,y,max(100,right-x),h)
    return (new,caps,routes),None


def compact_orthogonal(path,svg,source):
    from .pipeline import geometry
    from .labels import place_labels
    from .stable_blocks import safe_geometry,measures
    state=read_bpmn(path);before=measures(state)
    try:solution,error=solve_coordinates(state)
    except ImportError:return {'accepted':False,'reason':'scipy-unavailable'}
    if solution is None:return {'accepted':False,'reason':error}
    boxes,caps,paths=solution
    with tempfile.TemporaryDirectory(prefix='orthogonal-compact-',dir=Path(path).parent) as td:
        trial=Path(td)/'trial.bpmn';preview=trial.with_suffix('.svg');tree=copy.deepcopy(state[0]);root=tree.getroot();plane=root.xpath('.//bd:BPMNPlane',namespaces=NS)[0]
        update_geometry(root,plane,boxes,paths)
        for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
            n=b.getparent().getparent().get('bpmnElement')
            if n in caps:
                for k,v in zip(('x','y','width','height'),caps[n]):b.set(k,str(v))
        tree.write(str(trial),encoding='utf-8',xml_declaration=True);labels=place_labels(trial,preview,preserve=True);g=geometry(trial);after=measures(read_bpmn(trial))
        valid=(safe_geometry(g,labels) and after['contacts']<=before['contacts'] and after['length']<=before['length']+.1
               and after['score']<before['score']-.1)
        if valid:
            if not semantic_equality(source,trial) or not equal(source,trial):raise ValueError('Orthogonal compaction freeze violation')
            Path(path).write_bytes(trial.read_bytes());Path(svg).write_bytes(preview.read_bytes())
        return {'method':'coupled orthogonal envelope/port/track compaction','accepted':bool(valid),'before':before,'after':after,
                'reason':None if valid else 'independent-audit-or-no-gain','shapes_resized':0,'source_geometry_used':False}
