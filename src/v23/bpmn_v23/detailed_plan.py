"""Bounded measured planning portfolio before the existing final router."""
import copy,time
from .composition_plan import phase_plans,grid_plan,materialize_coarse
from .lane_ordering import reorder_lanes
from .preview_routes import rehearse


def prepare_candidates(nodes,docs,seq,assocs,member,lanes,canonical):
    args=(nodes,docs,seq,assocs,member,lanes,canonical)
    phases,pr=phase_plans(*args);grids,gr=grid_plan(*args)
    control=next(p for p in phases if p['mode']=='unfolded-phase' and not p['attach_next'])
    alternate=[p for p in phases if p['mode']=='unfolded-phase' and p['attach_next']]
    folded=[p for p in phases if p['mode']=='whole-phase-band']
    shortlist=[control]+alternate[:1]+folded[:1]+grids[:1]
    prepared=[]
    for original in shortlist:
        p=copy.deepcopy(original);p.setdefault('mode','role-grid')
        boxes,r=materialize_coarse(p,*args)
        old_tops={l:boxes[l][1] for l in lanes}
        boxes,r=reorder_lanes(boxes,r,nodes,docs,seq,member,lanes)
        bands=r.get('early_composition',{}).get('feedback_track_bands',{})
        for l,(x,y,w,h) in list(bands.items()):bands[l]=(x,y+boxes[l][1]-old_tops[l],w,h)
        p['role_order']=sorted(lanes,key=lambda l:(boxes[l][1],l))
        p['prepared']={'boxes':boxes,'report':r};prepared.append(p)
    return prepared,{'coarse_plans':pr['evaluated_plans']+gr['evaluated_plans'],'measured_candidates':len(prepared)}


def evaluate_prepared(prepared,nodes,docs,seq,assocs,member,lanes):
    evaluated=[]
    for p in prepared:
        b,r=p['prepared']['boxes'],p['prepared']['report']
        preview,cache=rehearse(nodes,docs,seq,assocs,member,lanes,b,r)
        evaluated.append((preview['score'],p,preview,cache))
    evaluated.sort(key=lambda q:(q[0],q[1]['mode'],q[1]['columns']))
    for index in range(min(2,len(evaluated))):
        score,p,preview,cache=evaluated[index]
        alternate,_=rehearse(nodes,docs,seq,assocs,member,lanes,p['prepared']['boxes'],p['prepared']['report'],True,cache)
        if alternate['score']<score:evaluated[index]=(alternate['score'],p,alternate,cache)
    evaluated.sort(key=lambda q:(q[0],q[1]['mode'],q[1]['columns']))
    chosen=[];details=[]
    control=next(q for q in evaluated if q[1]['mode']=='unfolded-phase' and not q[1]['attach_next'])
    for score,p,preview,_ in evaluated:
        # Missing template routes must never look like a shorter, cleaner graph.
        accepted=preview['unsupported_edges']<=control[2]['unsupported_edges']+2
        details.append({'mode':p['mode'],'columns':p['columns'],'attach_next':p.get('attach_next'), 'accepted':accepted,**{k:v for k,v in preview.items() if k not in ('paths','routing_order','unsupported_ids')}})
        if accepted and len(chosen)<2:
            p=copy.deepcopy(p);r=p['prepared']['report'];r['preplanned_paths']=preview['paths'];r['routing_priority']=preview['routing_order'];r['composition_preview']={k:v for k,v in preview.items() if k not in ('paths','routing_order')};chosen.append(p)
    return chosen,details


def plan_detailed(nodes,docs,seq,assocs,member,lanes,canonical):
    started=time.monotonic();prepared,summary=prepare_candidates(nodes,docs,seq,assocs,member,lanes,canonical)
    measured=time.monotonic();chosen,details=evaluate_prepared(prepared,nodes,docs,seq,assocs,member,lanes)
    return chosen,{'method':'measured four-family portfolio; orthogonal template rehearsal; three-edge beam windows; second route order on best two',**summary,'seconds':round(time.monotonic()-started,6),'measured_preparation_seconds':round(measured-started,6),'route_rehearsal_seconds':round(time.monotonic()-measured,6),'evaluated_plans':summary['coarse_plans'],'source_geometry_used':False,'names_or_numbers_used_for_structure':False,'proxy_is_not_a_route_audit':True,'preview_candidates':details,'chosen_plans':[{'mode':p['mode'],'columns':p['columns'],'attach_next':p.get('attach_next'),'role_order':p['role_order'],'preview_score':p['prepared']['report']['composition_preview']['score']} for p in chosen]}
