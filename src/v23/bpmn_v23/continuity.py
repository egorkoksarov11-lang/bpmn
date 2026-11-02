"""Local successor continuity measured against a frozen incumbent neighbourhood.

Only DI changes. Existing straight links and distant wires are protected; small
placements and mixed-side elbows are accepted only after the full saved audit.
"""
from pathlib import Path
from statistics import median
import copy,tempfile,time,hashlib
from bpmn_refkit.model import read_bpmn,TAG_TASK,set_di
from bpmn_refkit.geometry import compress
from bpmn_universal.contract import NS,semantic_equality
from bpmn_universal.engine import save_labels,arrange_flow_labels,quick_routes
from bpmn_universal.cli import deadline
from .human_search import HumanStyleBackend
from .patterns import analyze
from .decision_layout import _valid
from .clearance import safe_poly,outward
from .contours import attach,bounding_ports
from .quality import score,edge_score,contacts
from .router import route_graph,overlapping,refine_paths
from .reference_metrics import clean
from .freeze import equal as di_equal
from .labels import place_labels


def neighbourhood(nodes,seq,boxes,radius=.8):
    widths=[boxes[n][2] for n,o in nodes.items() if o['kind'] in TAG_TASK]
    width=median(widths) if widths else 160
    def gap(a,b):
        return max(0,b[0]-a[0]-a[2],a[0]-b[0]-b[2])+max(0,b[1]-a[1]-a[3],a[1]-b[1]-b[3])
    return [i for i,u,v,_ in seq if gap(boxes[u],boxes[v])<=width*radius]


def local_metrics(paths,edge_ids):
    bends=[max(0,len(clean(paths[i]))-2) for i in edge_ids]
    return {'frozen_neighbour_count':len(bends),'straight':sum(b==0 for b in bends),
            'one_bend':sum(b==1 for b in bends),'two_plus_bends':sum(b>=2 for b in bends),
            'bends':sum(bends),'straight_fraction':sum(b==0 for b in bends)/max(1,len(bends))}


def elbow_routes(a,b):
    """Adjacent-side ports are essential: bottom->right needs just one bend."""
    def ports(box):
        x,y,w,h=box
        return [(x+w*f,y) for f in (.5,.2,.35,.65,.8)]+[(x+w*f,y+h) for f in (.5,.2,.35,.65,.8)]+[(x,y+h*f) for f in (.5,.2,.35,.65,.8)]+[(x+w,y+h*f) for f in (.5,.2,.35,.65,.8)]
    seen=set()
    for s in ports(a):
        for t in ports(b):
            for corner in ((s[0],t[1]),(t[0],s[1])):
                p=compress([s,corner,t]);key=tuple(p)
                if key in seen or len(p)<2:continue
                seen.add(key)
                if outward(p[0],p[1],a) and outward(p[-1],p[-2],b):yield p


def shift_options(u,v,boxes):
    """Small moves to share an axis; never infer order from labels or IDs."""
    a,b=boxes[u],boxes[v]
    for axis in (0,1):
        other=1-axis
        if max(a[other],b[other])<min(a[other]+a[other+2],b[other]+b[other+2]):continue
        for moving,fixed in ((u,v),(v,u)):
            x,y=boxes[moving],boxes[fixed]
            if x[axis]+x[axis+2]<y[axis]:delta=y[axis]+15-x[axis]-x[axis+2]
            elif y[axis]+y[axis+2]<x[axis]:delta=y[axis]+y[axis+2]-15-x[axis]
            else:continue
            if abs(delta)>max(a[2],b[2])*.5:continue
            yield moving,axis,delta


def moved_boxes(boxes,node,axis,delta,pairs,owners,mode):
    result=dict(boxes);deltas={node:delta}
    partner=pairs.get(node)
    if partner:
        if mode=='rigid':deltas[partner]=delta
        elif axis==0:
            # Keep a short, straight task->decision gap while allowing the
            # task to share an axis with its predecessor in the adjacent row.
            task=boxes[node];gate=boxes[partner]
            if gate[0]>=task[0]+task[2]:deltas[partner]=max(0,task[0]+delta+task[2]+12-gate[0])
            elif gate[0]+gate[2]<=task[0]:deltas[partner]=min(0,task[0]+delta-12-gate[0]-gate[2])
    for doc,owner in owners.items():
        if owner in deltas:deltas[doc]=deltas[owner]
    for n,d in deltas.items():
        b=list(boxes[n]);b[axis]+=d;result[n]=tuple(b)
    return result,{n for n,d in deltas.items() if abs(d)>.01}


def placement_options(u,v,boxes,pairs,owners):
    seen=set()
    for n,axis,delta in shift_options(u,v,boxes):
        other=v if n==u else u
        for fraction in (1,.5,.25,.75):
            for mode in ('flexible','rigid'):
                bb,moved=moved_boxes(boxes,n,axis,delta*fraction,pairs,owners,mode)
                if fraction<1:
                    bb,more=moved_boxes(bb,other,axis,-delta*(1-fraction),pairs,owners,mode);moved|=more
                key=tuple((k,bb[k]) for k in sorted(moved))
                if key in seen:continue
                seen.add(key)
                yield bb,moved,f'{mode}-split-{fraction}'


def repair_added_contacts(boxes,nodes,seq,assocs,docs,paths,trial,uv,focal,protected):
    """Rip up the small conflict set together while keeping the new shortcut."""
    from collections import Counter
    old=Counter(i for a,b,_ in contacts(paths,uv) for i in (a,b))
    new=Counter(i for a,b,_ in contacts(trial,uv) for i in (a,b))
    victims=[i for i in new if i!=focal and i not in protected and new[i]>old[i]]
    victims=sorted(victims,key=lambda i:(old[i]-new[i],-len(trial[i]),i))[:6]
    if not victims or len(contacts(trial,uv))-len(contacts(paths,uv))>6:return trial
    fixed={i:p for i,p in trial.items() if i not in victims}
    repaired,_=route_graph(boxes,nodes,seq,assocs,docs,trial,rounds=0,avoid_crowding=True,fixed_paths=fixed)
    refine_paths(boxes,uv,repaired,rounds=1,avoid_crowding=True,protected_ids=set(uv)-set(victims))
    return repaired


class ContinuityBackend(HumanStyleBackend):
    name='v23-local-successor-continuity'
    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        if self.incumbent is None:raise ValueError('Local continuity requires a verified incumbent')

    def layout(self,source,output,svg):
        from .pipeline import geometry,validate_xml
        source=Path(source);output=Path(output);svg=Path(svg)
        parsed=read_bpmn(self.incumbent);tree,root,_,plane,nodes,seq,assocs,docs,member,lanes,boxes,paths=parsed
        if not semantic_equality(source,self.incumbent) or not di_equal(source,self.incumbent):raise ValueError('Incumbent freeze violation')
        validate_xml(self.incumbent);initial=geometry(self.incumbent)
        if not initial['routing_safety_passed'] or not initial['edge_clearance_passed'] or initial['excessive_bend_edges']:raise ValueError('Unsafe incumbent')
        uv={i:(u,v) for i,u,v,_ in seq+assocs};near=neighbourhood(nodes,seq,boxes);focus=neighbourhood(nodes,seq,boxes,radius=1.0);before=local_metrics(paths,near)
        motifs=analyze(nodes,seq,member,boxes);owners={}
        for d in docs:
            linked=[v if u==d else u for _,u,v,_ in assocs if d in (u,v)];linked=[n for n in linked if n in nodes]
            if linked:owners[d]=min(linked,key=lambda n:abs(boxes[d][0]-boxes[n][0])+abs(boxes[d][1]-boxes[n][1]))
        logs=[];started=time.monotonic();interrupted=False
        def obstacles(bb):
            ob={n:b for n,b in bb.items() if n in nodes or n in docs}
            ob.update({f'__lane_header_{l}':(bb[l][0],bb[l][1],48,bb[l][3]) for l in lanes});return ob
        baseline_quality=score(paths,uv)
        def rank(ps):
            m=local_metrics(ps,focus);return (m['two_plus_bends'],m['bends'],-m['straight'],score(ps,uv))
        quality=rank(paths);baseline_rank=quality
        with tempfile.TemporaryDirectory(prefix='continuity-',dir=output.parent) as td:
            td=Path(td);bp=td/'trial.bpmn';sp=td/'trial.svg';best_bpmn=self.incumbent.read_bytes()
            bp.write_bytes(best_bpmn);labels=place_labels(bp,sp)
            if labels['unplaced_labels'] or labels['rendering']['text_overflow_ids']:raise ValueError('Incumbent text audit failed')
            best_svg=sp.read_bytes()
            def commit(bb,ps,edge,kind):
                nonlocal boxes,paths,quality,best_bpmn,best_svg
                candidate=rank(ps);raw=score(ps,uv)
                # Do not trade a short successor for more crossings or longer
                # total wires. Freeze the neighbourhood before any movement.
                if candidate>=quality or raw[0]>baseline_quality[0] or raw[1]>baseline_quality[1] or raw[2]>baseline_quality[2]+.1:
                    if kind.startswith('axis'):logs.append({'edge':edge,'proposal':kind,'status':'rejected-by-objective','rank':candidate})
                    return False
                if any(len(clean(ps[i]))>2 for i in near if len(clean(paths[i]))==2):
                    logs.append({'edge':edge,'proposal':kind,'status':'rejected-straight-neighbour-regression'});return False
                ct=copy.deepcopy(tree);rr=ct.getroot();pp=rr.xpath('.//bd:BPMNPlane',namespaces=NS)[0]
                set_di(rr,pp,bb,ps);save_labels(rr,pp,bb,nodes,ps);arrange_flow_labels(rr,pp,obstacles(bb),seq,ps)
                ct.write(str(bp),encoding='utf-8',xml_declaration=True);lr=place_labels(bp,sp);g=geometry(bp)
                if lr['unplaced_labels'] or lr['rendering']['text_overflow_ids'] or g['task_text_overflows'] or g['label_collision_pairs'] or g['label_line_cuts'] or g['excessive_bend_edges'] or not g['routing_safety_passed'] or not g['edge_clearance_passed']:
                    logs.append({'edge':edge,'proposal':kind,'status':'rejected-by-audit'});return False
                if not semantic_equality(source,bp) or not di_equal(source,bp):raise ValueError('Freeze violation')
                logs.append({'edge':edge,'proposal':kind,'status':'accepted','before':quality,'after':candidate})
                boxes,paths,quality=bb,ps,candidate;best_bpmn=bp.read_bytes();best_svg=sp.read_bytes();return True
            try:
                with deadline(self.candidate_seconds):
                    for _ in range(3):
                        changed=False
                        for eid in sorted(focus,key=lambda i:(-len(clean(paths[i])),i)):
                            if len(clean(paths[eid]))<=2:continue
                            u,v=uv[eid];ob=obstacles(boxes);bound=bounding_ports(paths,uv,boxes,nodes);others={i:p for i,p in bound.items() if i!=eid}
                            options=[p for p in elbow_routes(boxes[u],boxes[v]) if safe_poly(eid,p,ob,uv) and not overlapping(p,others)]
                            for p in sorted(options,key=lambda p:edge_score(eid,p,others,uv))[:3]:
                                trial=attach({**bound,eid:p},uv,boxes,nodes)
                                if commit(boxes,trial,eid,'mixed-side-elbow'):changed=True;break
                            if len(clean(paths[eid]))<=2:continue
                            for bb,moved,mode in placement_options(u,v,boxes,motifs['pairs'],owners):
                                if not _valid(bb,nodes,docs,member):continue
                                obs=obstacles(bb);bound=bounding_ports(paths,uv,boxes,nodes);fixed={i:p for i,p in bound.items() if not(set(uv[i])&moved) and i!=eid and safe_poly(i,p,obs,uv)}
                                if len(uv)-len(fixed)>12:continue
                                direct=[p for p in quick_routes(eid,obs,uv,fixed,paths[eid]) if len(p)==2 and safe_poly(eid,p,obs,uv) and not overlapping(p,fixed)]
                                if not direct:continue
                                focal=min(direct,key=lambda p:edge_score(eid,p,fixed,uv));fixed[eid]=focal
                                try:
                                    trial,details=route_graph(obs,nodes,seq,assocs,docs,bound,rounds=0,avoid_crowding=True,fixed_paths=fixed)
                                    if score(trial,uv)[0]>baseline_quality[0]:
                                        protected={i for i in near if len(clean(paths[i]))==2}
                                        trial=repair_added_contacts(obs,nodes,seq,assocs,docs,bound,trial,uv,eid,protected)
                                    trial=attach(trial,uv,bb,nodes)
                                except (ValueError,RuntimeError) as error:
                                    logs.append({'edge':eid,'proposal':f'axis-alignment-{mode}','status':'route-failed','reason':str(error)});continue
                                if commit(bb,trial,eid,f'axis-alignment-{mode}'):
                                    changed=True;break
                        if not changed:break
            except TimeoutError:interrupted=True
            output.write_bytes(best_bpmn);svg.write_bytes(best_svg)
        return {'backend':self.name,'selected_candidate':'local-continuity' if any(c['status']=='accepted' for c in logs) else 'verified-incumbent',
                'quality':quality,'baseline_quality':baseline_rank,'frozen_neighbour_ids':near,'optimization_neighbour_ids':focus,'optimization_radius_task_widths':1.0,
                'continuity_before':before,'continuity_after':local_metrics(paths,near),
                'changes':logs,'incumbent_sha256':hashlib.sha256(self.incumbent.read_bytes()).hexdigest(),'interrupted':interrupted,'seconds':round(time.monotonic()-started,3),
                'constraints':'no increase relative to incumbent in contacts, total bends or total wire length; protect existing straight neighbours; full geometry/text/semantic/DI audits'}
