#!/usr/bin/env python3
"""BPMN compact layout v21: preserve task sizes, compact columns, re-route edges.

Requirements: pip install lxml cairosvg; install bpmn_refkit v19 package included
in the release archive. All task/flow/lane business semantics are immutable.
Only reciprocal *visual* document association duplicates may be removed by
--clean-duplicates, with explicit report and semantic whitelist.

python BPMN_compact_reference_v21.py --input input.bpmn --output output.bpmn \
    --svg output.svg --png output.png --report metrics.json --scale .76 --clean-duplicates
"""
from __future__ import annotations
import argparse, copy, heapq, json, math, sys, time
from pathlib import Path
from collections import defaultdict
from lxml import etree as ET
from bpmn_refkit.model import (read_bpmn, Q, BD, DC, semantic_digest,
    exact_business_signature, validate_di, set_di, lane_boxes)
from bpmn_refkit.geometry import (geometry_audit, compress, metric_length,
    bbox_intersect_seg, segment_intersection, segment_overlap)
from bpmn_refkit.renderer import svg_render


def render_labels_from_bpmn(svg_path, root, nodes):
    """Use BPMNLabel DI in SVG previews, so the preview matches BPMN editors.
    Existing renderer places event captions to the right regardless of obstacles.
    Only preview text is changed; editable BPMN remains authoritative.
    """
    import textwrap
    ns='http://www.w3.org/2000/svg'
    nsmap={'d':'http://www.omg.org/spec/BPMN/20100524/DI',
           'c':'http://www.omg.org/spec/DD/20100524/DC'}
    tree=ET.parse(str(svg_path)); svg=tree.getroot()
    label_texts=set()
    labels=[]
    for shape in root.xpath('.//d:BPMNShape', namespaces=nsmap):
        id=shape.get('bpmnElement'); info=nodes.get(id)
        if info is None or info.get('kind') not in ('startEvent','endEvent','exclusiveGateway','parallelGateway'):
            continue
        name=info.get('name') or ''
        if not name:continue
        bd=shape.find(Q('BPMNLabel',BD))
        if bd is None:continue
        b=bd.find(Q('Bounds',DC))
        if b is None:continue
        box=tuple(float(b.get(i)) for i in ('x','y','width','height'))
        labels.append((id,info['kind'],name,box))
        if info['kind'].endswith('Gateway'):
            label_texts.update(textwrap.wrap(name,26)[:3])
        else:
            label_texts.update(textwrap.wrap(name,25)[:3])
    for el in list(svg):
        if el.tag==f'{{{ns}}}text' and (el.text or '').strip() in label_texts:
            svg.remove(el)
    for id,kind,name,(x,y,w,h) in labels:
        font='13' if kind.endswith('Gateway') else '13'
        maxchars=max(18,round(w/7.5))
        chunks=textwrap.wrap(name,maxchars,break_long_words=False,break_on_hyphens=False)
        chunks=chunks[:max(1,round(h/16))]
        start=y+max(14,(h-(len(chunks)-1)*15)/2+5)
        for idx,t in enumerate(chunks):
            textel=ET.SubElement(svg,f'{{{ns}}}text',{'x':str(x+w/2),'y':str(start+idx*15),
                 'text-anchor':'middle','font-family':'Arial,sans-serif','font-size':font,
                 'fill':'#526477'})
            textel.text=t
    tree.write(str(svg_path),encoding='utf-8',xml_declaration=True)


def prune_reciprocal_associations(root, plane, assocs, docs, allow=False, approved_ids=None):
    """Remove only mirror association between SAME task and SAME doc ref.

    Keep document -> task for reference used by task. The opposite edge is
    redundant on the drawing, but removal is an intentional XML change and is
    reported separately from the 0-diff process flow guarantee.
    """
    if not allow:return [],assocs
    approved_ids=set(approved_ids or [])
    groups=defaultdict(list)
    for i,u,v,dir in assocs:
        if (u in docs) ^ (v in docs):groups[frozenset((u,v))].append((i,u,v,dir))
    removed=[]
    for key,items in groups.items():
        if len(items)!=2:continue
        left,right=items
        if left[1]!=right[2] or left[2]!=right[1]:continue
        outgoing=[z for z in items if z[1] not in docs and z[2] in docs]
        incoming=[z for z in items if z[1] in docs and z[2] not in docs]
        if len(outgoing)!=1 or len(incoming)!=1:continue
        doomed=outgoing[0][0]
        if doomed not in approved_ids:continue
        element=root.xpath(f'.//b:association[@id="{doomed}"]',namespaces={'b':'http://www.omg.org/spec/BPMN/20100524/MODEL'})
        di_edge=[v for v in plane.findall(Q('BPMNEdge',BD)) if v.get('bpmnElement')==doomed]
        if len(element)!=1 or len(di_edge)!=1:continue
        element[0].getparent().remove(element[0]);plane.remove(di_edge[0])
        removed.append(doomed)
    return sorted(removed),[v for v in assocs if v[0] not in removed]


def compact_x(boxes, nodes, docs, scale=.73, gap_task=26, gap_doc=15):
    """Project shapes to narrower x-coordinates, then enforce hard no-overlap constraints.

    The constraint graph retains left/right order only for shapes whose Y ranges
    overlap, so unrelated vertical stacks can use the same columns. Object W/H
    are never changed. At equal X, tie-break by BPMN ID for determinism.
    """
    k0=min(v[0] for v in boxes.values())
    order=sorted(boxes,key=lambda id:(boxes[id][0],id))
    out={};x={}
    for idx,k in enumerate(order):
        ox,oy,ow,oh=boxes[k]
        result=k0+(ox-k0)*scale
        for left in order[:idx]:
            xx,yy,ww,hh=boxes[left]
            if min(oy+oh,yy+hh)-max(oy,yy)<9:continue
            # Only order shapes that were nonoverlapping in the original.
            if xx+ww>ox+1e-3:continue
            margin=gap_doc if k in docs or left in docs else gap_task
            result=max(result,x[left]+ww+margin)
        x[k]=round(result,2)
        out[k]=(x[k],oy,ow,oh)
    return out


def border_pt(b,p,eps=1):
    x,y,w,h=b;xx,yy=p
    return ((abs(xx-x)<eps or abs(xx-x-w)<eps) and y-eps<=yy<=y+h+eps) or ((abs(yy-y)<eps or abs(yy-y-h)<eps) and x-eps<=xx<=x+w+eps)


def good_poly(eid,poly,boxes,uv):
    if len(poly)<2:return False
    u,v=uv[eid]
    if not border_pt(boxes[u],poly[0]) or not border_pt(boxes[v],poly[-1]):return False
    for a,b in zip(poly,poly[1:]):
        if abs(a[0]-b[0])>.1 and abs(a[1]-b[1])>.1:return False
        if abs(a[0]-b[0])+abs(a[1]-b[1])<1:return False
        for k,box in boxes.items():
            # terminal segments may touch their source and target borders;
            # they must not traverse the interiors of either one.
            if bbox_intersect_seg(box,a,b,clearance=1.2):return False
    return True


def matching_port(oldpt,oldbox,newbox):
    ox,oy,ow,oh=oldbox;nx,ny,nw,nh=newbox
    if abs(oldpt[0]-ox)<.5:return (nx,oldpt[1])
    if abs(oldpt[0]-(ox+ow))<.5:return (nx+nw,oldpt[1])
    if abs(oldpt[1]-oy)<.5:return (nx+(oldpt[0]-ox),ny)
    if abs(oldpt[1]-(oy+oh))<.5:return (nx+(oldpt[0]-ox),ny+nh)
    return (nx+nw/2,ny+nh/2)


def initial_path(old,bu,bv,nu,nv,scale,x0):
    pp=[(round(x0+(p[0]-x0)*scale,2),p[1]) for p in old]
    p0=matching_port(old[0],bu,nu);p1=matching_port(old[-1],bv,nv)
    if len(pp)<2:return [p0,p1]
    # Preserve truly straight vertical links by reanchoring BOTH shapes on a
    # shared X column. This prevents a small 2-point route from turning into
    # an artificial zigzag after horizontal compaction.
    if len(old)==2 and abs(old[0][0]-old[1][0])<.1:
        overlap_left=max(nu[0],nv[0])+3
        overlap_right=min(nu[0]+nu[2],nv[0]+nv[2])-3
        if overlap_right>overlap_left:
            preferred=(p0[0]+p1[0])/2
            common=round(max(overlap_left,min(overlap_right,preferred)),2)
            if border_pt(nu,(common,p0[1])) and border_pt(nv,(common,p1[1])):
                return [(common,p0[1]),(common,p1[1])]
    # Same for horizontal neighbors on a shared Y axis.
    if len(old)==2 and abs(old[0][1]-old[1][1])<.1:
        lower=max(nu[1],nv[1])+3
        upper=min(nu[1]+nu[3],nv[1]+nv[3])-3
        if upper>lower:
            common=round(max(lower,min(upper,(p0[1]+p1[1])/2)),2)
            if border_pt(nu,(p0[0],common)) and border_pt(nv,(p1[0],common)):
                return [(p0[0],common),(p1[0],common)]
    pp[0]=p0;pp[-1]=p1
    if len(pp)>=3:
        if abs(old[0][0]-old[1][0])<.1:pp[1]=(p0[0],pp[1][1])
        if abs(old[-1][0]-old[-2][0])<.1:pp[-2]=(p1[0],pp[-2][1])
    pp=compress(pp)
    # Insert orthogonal corner at discontinuities created by reanchoring.
    ortho=[pp[0]]
    for nxt in pp[1:]:
        prev=ortho[-1]
        if abs(prev[0]-nxt[0])>.1 and abs(prev[1]-nxt[1])>.1:
            # Try a hook near the terminal or source rather than a diagonal.
            if len(ortho)==1:ortho.append((nxt[0],prev[1]))
            else:ortho.append((prev[0],nxt[1]))
        ortho.append(nxt)
    return compress(ortho)


def ports(b):
    x,y,w,h=b
    return [(x+w,y+h/2,'R'),(x,y+h/2,'L'),(x+w/2,y+h,'B'),(x+w/2,y,'T')]


def penalty_cross(poly,otherpaths,eid,ignore=None):
    value=0
    for k,p in otherpaths.items():
        if k==eid or k==ignore:continue
        for a,b in zip(poly,poly[1:]):
            for c,d in zip(p,p[1:]):
                if segment_intersection(a,b,c,d):value+=3000
                ov=segment_overlap(a,b,c,d)
                if ov>2:value+=5000+ov*2
    return value


def route_cost(poly,otherpaths,eid):
    return metric_length(poly)*.7 + (len(poly)-2)*160 + penalty_cross(poly,otherpaths,eid)


def ports_candidates(bu,bv,orig=None):
    x,y,w,h=bu;xx,yy,ww,hh=bv
    dx=xx+ww/2-(x+w/2);dy=yy+hh/2-(y+h/2)
    if abs(dx)>=abs(dy)*.7:
        prefer=('R','L') if dx>0 else ('L','R')
    else:prefer=('B','T') if dy>0 else ('T','B')
    src=ports(bu);tgt=ports(bv)
    pairs=[]
    if orig and border_pt(bu,orig[0]) and border_pt(bv,orig[-1]):pairs.append((orig[0],orig[-1]))
    def get(p,name):return next((a,b) for a,b,d in p if d==name)
    pairs.append((get(src,prefer[0]),get(tgt,prefer[1])))
    for a,b in [('B','T'),('R','L'),('T','B'),('L','R')]:pairs.append((get(src,a),get(tgt,b)))
    seen=set();out=[]
    for z in pairs:
        if z not in seen:out.append(z);seen.add(z)
    return out


def quick_routes(eid,boxes,uv,paths,base_path=None):
    u,v=uv[eid];bu,bv=boxes[u],boxes[v]
    minx=min(bu[0],bv[0]);maxx=max(bu[0]+bu[2],bv[0]+bv[2]);miny=min(bu[1],bv[1]);maxy=max(bu[1]+bu[3],bv[1]+bv[3])
    xs={round(q,2) for q in (minx-17,maxx+17,(minx+maxx)/2,bu[0]-16,bu[0]+bu[2]+16,bv[0]-16,bv[0]+bv[2]+16)}
    ys={round(q,2) for q in (miny-17,maxy+17,(miny+maxy)/2,bu[1]-16,bu[1]+bu[3]+16,bv[1]-16,bv[1]+bv[3]+16)}
    for box in boxes.values():
        x,y,w,h=box
        if minx-90<=x<=maxx+90:
            xs.update((round(x-12,2),round(x+w+12,2)))
        if miny-80<=y<=maxy+80:
            ys.update((round(y-12,2),round(y+h+12,2)))
    xs=sorted(xs,key=lambda x:abs(x-(minx+maxx)/2))[:27]
    ys=sorted(ys,key=lambda y:abs(y-(miny+maxy)/2))[:27]
    result=[];seen=set()
    # Re-anchoring on a shared axis: prefer one straight connection rather
    # than routing through two center-aligned endpoints with an artificial hook.
    sx=bu[0]+bu[2]/2; tx=bv[0]+bv[2]/2
    sy=bu[1]+bu[3]/2; ty=bv[1]+bv[3]/2
    direct=[]
    if bu[1]+bu[3]<bv[1]-4:
        for xx in (sx,tx,(sx+tx)/2,max(bu[0],bv[0])+5,min(bu[0]+bu[2],bv[0]+bv[2])-5):
            if bu[0]+3<=xx<=bu[0]+bu[2]-3 and bv[0]+3<=xx<=bv[0]+bv[2]-3:
                direct.append([(xx,bu[1]+bu[3]),(xx,bv[1])])
    if bv[1]+bv[3]<bu[1]-4:
        for xx in (sx,tx,(sx+tx)/2,max(bu[0],bv[0])+5,min(bu[0]+bu[2],bv[0]+bv[2])-5):
            if bu[0]+3<=xx<=bu[0]+bu[2]-3 and bv[0]+3<=xx<=bv[0]+bv[2]-3:
                direct.append([(xx,bu[1]),(xx,bv[1]+bv[3])])
    if bu[0]+bu[2]<bv[0]-4:
        for yy in (sy,ty,(sy+ty)/2,max(bu[1],bv[1])+5,min(bu[1]+bu[3],bv[1]+bv[3])-5):
            if bu[1]+3<=yy<=bu[1]+bu[3]-3 and bv[1]+3<=yy<=bv[1]+bv[3]-3:
                direct.append([(bu[0]+bu[2],yy),(bv[0],yy)])
    if bv[0]+bv[2]<bu[0]-4:
        for yy in (sy,ty,(sy+ty)/2,max(bu[1],bv[1])+5,min(bu[1]+bu[3],bv[1]+bv[3])-5):
            if bu[1]+3<=yy<=bu[1]+bu[3]-3 and bv[1]+3<=yy<=bv[1]+bv[3]-3:
                direct.append([(bu[0],yy),(bv[0]+bv[2],yy)])
    for pp in direct:
        cp=compress(pp);key=tuple(cp)
        if key not in seen and good_poly(eid,cp,boxes,uv):result.append(cp);seen.add(key)
    for s,t in ports_candidates(bu,bv,base_path):
        poss=[[s,t],[s,(t[0],s[1]),t],[s,(s[0],t[1]),t]]
        for q in xs:poss.append([s,(q,s[1]),(q,t[1]),t])
        for q in ys:poss.append([s,(s[0],q),(t[0],q),t])
        for route in poss:
            p=compress(route);key=tuple(p)
            if key in seen:continue
            seen.add(key)
            if good_poly(eid,p,boxes,uv):result.append(p)
    return result


def inclusive_cross(a,b,c,d):
    eps=.01
    if abs(a[1]-b[1])<eps and abs(c[0]-d[0])<eps:
        return min(a[0],b[0])-eps<=c[0]<=max(a[0],b[0])+eps and min(c[1],d[1])-eps<=a[1]<=max(c[1],d[1])+eps
    if abs(a[0]-b[0])<eps and abs(c[1]-d[1])<eps:
        return min(c[0],d[0])-eps<=a[0]<=max(c[0],d[0])+eps and min(a[1],b[1])-eps<=c[1]<=max(a[1],b[1])+eps
    return False


def astar_route(eid,boxes,uv,paths,sourceports=None,top_n=3,avoid_paths=None):
    """Sparse orthogonal visibility graph using A* with bend/length cost.

    Only invoked for edges whose simple geometries hit shapes; a deterministic
    geometric fallback that does not modify the BPMN process model.
    """
    u,v=uv[eid];bu,bv=boxes[u],boxes[v]
    x0=min(bu[0],bv[0]);x1=max(bu[0]+bu[2],bv[0]+bv[2]);y0=min(bu[1],bv[1]);y1=max(bu[1]+bu[3],bv[1]+bv[3])
    pad=210
    relevant={k:z for k,z in boxes.items() if z[0]<x1+pad and z[0]+z[2]>x0-pad and z[1]<y1+pad and z[1]+z[3]>y0-pad}
    xs={round(x0-pad,2),round(x1+pad,2)};ys={round(y0-pad,2),round(y1+pad,2)}
    for x,y,w,h in relevant.values():
        xs.update((x-13,x+w+13,x+w/2));ys.update((y-13,y+h+13,y+h/2))
    pairs=sourceports or ports_candidates(bu,bv)
    for s,t in pairs:xs.update((s[0],t[0]));ys.update((s[1],t[1]))
    xs=sorted(round(q,2) for q in xs);ys=sorted(round(q,2) for q in ys)
    xi={v:i for i,v in enumerate(xs)};yi={v:i for i,v in enumerate(ys)}
    def free(a,b):
        return not any(bbox_intersect_seg(ob,a,b,clearance=1.1) for ob in relevant.values())
    options=[]
    for si,ti in pairs[:top_n]:
        src=(xi[round(si[0],2)],yi[round(si[1],2)]);tgt=(xi[round(ti[0],2)],yi[round(ti[1],2)])
        q=[];heapq.heappush(q,(0.,0.,src[0],src[1],-1))
        dist={(src[0],src[1],-1):0.};parents={}
        endstate=None;visited=0
        while q and visited<40000:
            f,g,i,j,d=heapq.heappop(q)
            state=(i,j,d)
            if g>dist.get(state,math.inf)+.001:continue
            visited+=1
            if (i,j)==tgt:
                endstate=state;break
            for dd,(di,dj) in enumerate(((1,0),(-1,0),(0,1),(0,-1))):
                ii=i+di;jj=j+dj
                if not (0<=ii<len(xs) and 0<=jj<len(ys)):continue
                pa=(xs[i],ys[j]);pb=(xs[ii],ys[jj])
                if not free(pa,pb):continue
                if avoid_paths:
                    obstructed=False
                    for linked in avoid_paths.values():
                        for oa,ob in zip(linked,linked[1:]):
                            if inclusive_cross(pa,pb,oa,ob) or segment_overlap(pa,pb,oa,ob)>2:
                                obstructed=True;break
                        if obstructed:break
                    if obstructed:continue
                step=(abs(pb[0]-pa[0])+abs(pb[1]-pa[1]))*.8
                turn=0 if d<0 or d==dd else 165
                # Penalize exact line reuse; crossing interactions are checked when selecting candidates.
                ng=g+step+turn
                other=(ii,jj,dd)
                if ng>=dist.get(other,math.inf)-.001:continue
                dist[other]=ng;parents[other]=state
                heuristic=(abs(pb[0]-ti[0])+abs(pb[1]-ti[1]))*.8
                heapq.heappush(q,(ng+heuristic,ng,ii,jj,dd))
        if endstate is not None:
            p=[];state=endstate
            while True:
                p.append((xs[state[0]],ys[state[1]]))
                if state not in parents:break
                state=parents[state]
            path=compress(p[::-1])
            if good_poly(eid,path,boxes,uv):options.append(path)
    if not options:return None
    return min(options,key=lambda p:route_cost(p,paths,eid))


def pack_routes(original_boxes,new_boxes,original_paths,seq,assocs,scale,ordering="short-first"):
    uv={i:(u,v) for i,u,v,_ in seq+assocs}
    x0=min(z[0] for z in original_boxes.values())
    initial={i:initial_path(original_paths[i],original_boxes[u],original_boxes[v],new_boxes[u],new_boxes[v],scale,x0) for i,u,v,_ in seq+assocs}
    order=sorted(uv,key=lambda eid:(eid not in {z[0] for z in seq},len(initial[eid])-2,metric_length(initial[eid]),eid))
    if ordering=="long-first":order.sort(key=lambda eid:(eid not in {z[0] for z in seq},-metric_length(initial[eid]),eid))
    elif ordering=="name":order=sorted(order)
    elif ordering=="reverse":order=list(reversed(order))
    elif ordering=="flow-first-long":order.sort(key=lambda eid:(eid not in {z[0] for z in seq},-len(initial[eid]),-metric_length(initial[eid]),eid))
    elif ordering=="central-first":order.sort(key=lambda eid:(eid not in {z[0] for z in seq},abs(initial[eid][0][0]-initial[eid][-1][0]),eid))
    paths={};decisions={'quick':0,'astar':0,'transformed':0,'failed':[]}
    for eid in order:
        p=initial[eid]
        variants=quick_routes(eid,new_boxes,uv,paths,p)
        if good_poly(eid,p,new_boxes,uv):variants.append(p)
        if not variants:
            pp=astar_route(eid,new_boxes,uv,paths,ports_candidates(new_boxes[uv[eid][0]],new_boxes[uv[eid][1]],p),top_n=3)
            if pp:variants=[pp];decisions['astar']+=1
        if not variants:
            decisions['failed'].append(eid)
            return None,decisions
        best=min(variants,key=lambda q:route_cost(q,paths,eid))
        paths[eid]=best
        if best==p:decisions['transformed']+=1
        else:decisions['quick']+=1
    return paths,decisions


def refine_conflicts(boxes,paths,seq,assocs,nodes,docs,rounds=3):
    """Reconsider both sides of each crossing AFTER all routes were placed.

    Greedy single-pass routing misses conflicts with edges created later. This
    post-pass reanchors gateway and document connections (including noncentral
    ports) and commits only globally improving alternatives.
    """
    uv={i:(u,v) for i,u,v,_ in seq+assocs}
    changed=[]
    for it in range(rounds):
        audit=geometry_audit(boxes,paths,seq,assocs,nodes,docs)
        problematic=set()
        for typ,examples in audit['crossing_examples'].items():
            for pair in examples:
                if isinstance(pair,list) and len(pair)==2:
                    problematic.update(pair)
        if not problematic:break
        applied=0
        for eid in sorted(problematic):
            if eid not in paths:continue
            old=paths[eid];before=route_cost(old,paths,eid)
            candidates=quick_routes(eid,boxes,uv,paths,old)
            winner=old;value=before
            for candidate in candidates:
                cost=route_cost(candidate,paths,eid)
                if cost<value-0.01:
                    winner=candidate;value=cost
            if winner!=old:
                paths[eid]=winner;changed.append({'edge':eid,'old':old,'new':winner})
                applied+=1
        if not applied:break
    return changed


def lane_compact_horizontal(root,plane,lane_names,boxes):
    # Width is a frame property, not a task property.
    max_x=max(v[0]+v[2] for v in boxes.values())
    for el in plane.findall(Q('BPMNShape',BD)):
        if el.get('bpmnElement') not in lane_names:continue
        bb=el.find(Q('Bounds',DC))
        if bb is None:continue
        x=float(bb.get('x'))
        bb.set('width',str(round(max_x-x+78,2)))


def shape_label_bounds(root,plane,boxes,nodes,flowpaths):
    """Place BPMNLabels with explicit obstacle and route clearance.

    Evaluate several top/bottom/side offsets instead of defaulting to one huge
    caption rectangle. Track captions already placed as obstacles as well.
    """
    result=[]; occupied=[]
    shape_items=[s for s in plane.findall(Q('BPMNShape',BD))
                 if s.get('bpmnElement') in nodes]
    shape_items.sort(key=lambda s:(nodes[s.get('bpmnElement')]['kind'] not in ('endEvent','startEvent'),
                                   s.get('bpmnElement')))
    for shape in shape_items:
        id=shape.get('bpmnElement');info=nodes[id]
        name=info.get('name','');kind=info.get('kind','')
        if not name or kind not in ('exclusiveGateway','parallelGateway','endEvent','startEvent'):continue
        x,y,w,h=boxes[id]
        label_w=min(216,max(85,round(min(len(name),31)*7.4)))
        nlines=max(1,math.ceil(len(name)/max(1,round(label_w/7.5))))
        label_h=nlines*14+4
        options=[]
        for dx in (0,-48,48,-94,94,-142,142):
            for margin in (8,16,34,60):
                options.append((x+w/2-label_w/2+dx,y-label_h-margin,'above'))
                options.append((x+w/2-label_w/2+dx,y+h+margin,'below'))
        for dy in (0,-30,30):
            options.append((x+w+11,y+h/2-label_h/2+dy,'right'))
            options.append((x-label_w-11,y+h/2-label_h/2+dy,'left'))
        best=None
        for lx,ly,side in options:
            lb=(lx,ly,label_w,label_h)
            overlaps=sum(1 for other,ob in boxes.items() if other!=id and
                         min(lx+label_w,ob[0]+ob[2])-max(lx,ob[0])>2 and
                         min(ly+label_h,ob[1]+ob[3])-max(ly,ob[1])>2)
            overlaps+=sum(1 for ox,oy,ow,oh in occupied if
                         min(lx+label_w,ox+ow)-max(lx,ox)>2 and
                         min(ly+label_h,oy+oh)-max(ly,oy)>2)
            cut=sum(1 for path in flowpaths.values() for a,b in zip(path,path[1:])
                    if bbox_intersect_seg(lb,a,b,clearance=1))
            # Penalize captions far away, outside diagram, or intruding on a lane.
            penalty=abs(lx+label_w/2-(x+w/2))*.45+abs(ly+label_h/2-(y+h/2))*.17
            if ly<75: penalty+=3000
            # Keep labels inside their actor lane whenever space permits.
            lane_id=info.get('lane')
            if lane_id:
                for lane_shape in plane.findall(Q('BPMNShape',BD)):
                    if lane_shape.get('bpmnElement')!=lane_id:continue
                    bounds=lane_shape.find(Q('Bounds',DC))
                    if bounds is not None:
                        lane_top=float(bounds.get('y'));lane_end=lane_top+float(bounds.get('height'))
                        if ly<lane_top+1 or ly+label_h>lane_end-1:penalty+=7000
                    break
            if ly>max(box[1]+box[3] for box in boxes.values())+35:penalty+=3000
            if kind=='startEvent' and side!='right':penalty+=20
            if kind=='endEvent' and side!='below':penalty+=15
            score=overlaps*15000+cut*3500+penalty
            if best is None or score<best[0]:best=(score,lb)
        lb=best[1];occupied.append(lb)
        old=shape.find(Q('BPMNLabel',BD))
        if old is None:old=ET.SubElement(shape,Q('BPMNLabel',BD))
        b=old.find(Q('Bounds',DC))
        if b is None:b=ET.SubElement(old,Q('Bounds',DC))
        for prop,value in zip(('x','y','width','height'),lb):b.set(prop,str(round(value,2)))
        result.append(id)
    return result


def arrange_flow_labels(root,plane,boxes,seq,paths):
    """Generate nonoverlapping BPMN-DI label rectangles for named branches.

    The source preview renderer's default labels sit on the first edge segment
    even if that collides with a document or another BPMN label. Labels here
    search around multiple edge segments with a hard spatial collision penalty.
    """
    import textwrap
    edges={e.get('bpmnElement'):e for e in plane.findall(Q('BPMNEdge',BD))}
    occupied=[];out={}
    for eid,u,v,name in sorted(seq,key=lambda q:(len(q[3] or ''),q[0]),reverse=True):
        if not name or eid not in paths:continue
        width=min(216,max(32,len(name)*7.1+13));lines=max(1,math.ceil((len(name)*7.1)/max(1,width-14)))
        height=16*lines+4
        proposals=[]
        for a,b in zip(paths[eid],paths[eid][1:]):
            dx=b[0]-a[0];dy=b[1]-a[1]
            if abs(dx)>abs(dy):
                centers=[(a[0]+b[0])/2]+[a[0]+dx*f for f in (.3,.7)]
                for center in centers:
                    for offset in (-12,-20,-34,-56,-76,-108,13,24,40,62,86,112):
                        proposals.append((center-width/2,a[1]+offset-height if offset<0 else a[1]+offset))
            else:
                for factor in (.3,.5,.7):
                    cy=a[1]+dy*factor
                    for off in (12,25,52,82,-width-12,-width-25,-width-52,-width-82):
                        proposals.append((a[0]+off,cy-height/2))
        best=None
        for xx,yy in proposals:
            rect=(xx,yy,width,height)
            hits=sum(1 for z in boxes.values() if min(xx+width,z[0]+z[2])-max(xx,z[0])>2 and min(yy+height,z[1]+z[3])-max(yy,z[1])>2)
            hits+=sum(1 for z in occupied if min(xx+width,z[0]+z[2])-max(xx,z[0])>2 and min(yy+height,z[1]+z[3])-max(yy,z[1])>2)
            cut=sum(1 for line in paths.values() for p,q in zip(line,line[1:]) if bbox_intersect_seg(rect,p,q,clearance=1.5))
            distance=abs(xx-(a[0]+b[0])/2)+abs(yy-(a[1]+b[1])/2)
            penalty=hits*4500+cut*1400+distance*.04+max(0,80-yy)*30
            if best is None or penalty<best[0]:best=(penalty,rect)
        if best is None:continue
        rect=tuple(round(v,2) for v in best[1]);occupied.append(rect);out[eid]=(name,rect)
        edge=edges[eid]
        lab=ET.SubElement(edge,Q('BPMNLabel',BD))
        b=ET.SubElement(lab,Q('Bounds',DC))
        for attr,val in zip(('x','y','width','height'),rect):b.set(attr,str(val))
    return out


def apply_di_labels_to_svg(svg_path,root,nodes,seq,flow_labels):
    """Render labels using the exact saved BPMN-DI bounds, not a guess.

    This does not modify semantic XML or routes; it fixes an SVG-specific label
    placement defect that previously made the preview appear much more tangled.
    """
    import textwrap
    SVG='http://www.w3.org/2000/svg'
    tree=ET.parse(str(svg_path));svg=tree.getroot()
    shape_names=set()
    labels=[]
    for shape in root.findall('.//'+Q('BPMNShape',BD)):
        nid=shape.get('bpmnElement');info=nodes.get(nid)
        if info is None or info.get('kind') not in ('startEvent','endEvent','exclusiveGateway','parallelGateway'):continue
        lab=shape.find(Q('BPMNLabel',BD))
        if lab is None:continue
        b=lab.find(Q('Bounds',DC))
        if b is None:continue
        name=info.get('name') or ''
        if not name:continue
        rect=tuple(float(b.get(k)) for k in ('x','y','width','height'))
        labels.append((name,rect))
        shape_names.update(textwrap.wrap(name,26)[:4]);shape_names.update(textwrap.wrap(name,25)[:4])
    branch_names={name for _,u,v,name in seq if name}
    for el in list(svg):
        if el.tag==f'{{{SVG}}}text' and (el.text or '').strip() in shape_names|branch_names:
            svg.remove(el)
    for name,(x,y,w,h) in labels:
        lines=textwrap.wrap(name,max(13,int(w/7)),break_long_words=False)
        for k,line in enumerate(lines[:max(1,int(h/14))]):
            txt=ET.SubElement(svg,f'{{{SVG}}}text',{'x':str(round(x+w/2,2)),
                'y':str(round(y+14+k*14,2)),'text-anchor':'middle',
                'font-family':'Arial,sans-serif','font-size':'12','fill':'#45546a'})
            txt.text=line
    for eid,(name,(x,y,w,h)) in flow_labels.items():
        lines=textwrap.wrap(name,max(9,int((w-8)/7.2)),break_long_words=False)
        rect=ET.SubElement(svg,f'{{{SVG}}}rect',{'x':str(round(x,2)),'y':str(round(y,2)),
            'width':str(round(w,2)),'height':str(round(h,2)),
            'fill':'#ffffff','fill-opacity':'0.92','stroke':'none'})
        for k,line in enumerate(lines[:max(1,int(h/14))]):
            txt=ET.SubElement(svg,f'{{{SVG}}}text',{'x':str(round(x+w/2,2)),
                'y':str(round(y+14+k*14,2)),'text-anchor':'middle',
                'font-family':'Arial,sans-serif','font-size':'12','fill':'#92613e'})
            txt.text=line
    tree.write(str(svg_path),encoding='utf-8',xml_declaration=True)


def save_labels(root,plane,boxes,nodes,paths):
    return shape_label_bounds(root,plane,boxes,nodes,paths)


def run(input,output,svg=None,png=None,report=None,scale=.90,clean_duplicates=False, approved_ids=None, task_gap=26, document_gap=15, candidate_scales=None, routing_order="short-first", max_width_growth=1.05, max_flow_length_growth=1.35, process_title=None, png_width=4400):
    tree,root,process,plane,nodes,seq,assocs,docs,lanes,lane_names,allboxes,source_paths=read_bpmn(input)
    process_start=copy.deepcopy(process)
    source_digest=semantic_digest(root)
    source_edges={i:(u,v,name) for i,u,v,name in seq}
    original_assocs={i:(u,v,d) for i,u,v,d in assocs}
    dropped,assocs=prune_reciprocal_associations(root,plane,assocs,docs,clean_duplicates,approved_ids)
    old={k:z for k,z in allboxes.items() if k in nodes or k in docs}
    before=geometry_audit(old,{k:v for k,v in source_paths.items() if k in {z[0] for z in seq+assocs}},seq,assocs,nodes,docs)
    choice=None
    scales=candidate_scales if candidate_scales is not None else [scale,max(scale,.78),max(scale,.84),1.0]
    scales=list(dict.fromkeys(round(float(r),5) for r in scales))
    for ratio in scales:
        boxes=compact_x(old,nodes,docs,ratio,gap_task=task_gap,gap_doc=document_gap)
        paths,details=pack_routes(old,boxes,source_paths,seq,assocs,ratio,ordering=routing_order)
        if paths is None:continue
        changes=refine_conflicts(boxes,paths,seq,assocs,nodes,docs)
        details['joint_refinements']=len(changes)
        metrics=geometry_audit(boxes,paths,seq,assocs,nodes,docs)
        if metrics['shape_overlaps'] or metrics['line_through_shapes'] or metrics['crossings'].get('overlapping_segments',0):continue
        # Regression guard: never introduce more main/document intersections than
        # the input. The next optimization must be strictly better or equal.
        if any(metrics['crossings'].get(kind,0)>before['crossings'].get(kind,0)
               for kind in ('flow_flow','flow_association','association_association')):
            continue
        width=max(v[0]+v[2] for v in boxes.values())-min(v[0] for v in boxes.values())
        original_width=max(z[0]+z[2] for z in old.values())-min(z[0] for z in old.values())
        if width > original_width*max_width_growth:continue
        if before.get('avg_flow_length',0)>0 and metrics.get('avg_flow_length',0)>before['avg_flow_length']*max_flow_length_growth:continue
        # Hard priorities: document-flow collisions and crossing count.
        # Within equally clean routings trade ONE extra bend against a visibly
        # narrower diagram; previous lexicographic selection always favoured
        # the uncompressed (scale=1) geometry because of one extra bend.
        width=max(v[0]+v[2] for v in boxes.values())-min(v[0] for v in boxes.values())
        compact_score=metrics['total_bends']*14 + width*.13 + metrics['avg_flow_length']*.14
        obj=(metrics['crossings'].get('flow_association',0),metrics['crossings'].get('association_association',0),
             metrics['crossings'].get('flow_flow',0),round(compact_score,2))
        if choice is None or obj < choice[0]:choice=(obj,boxes,paths,metrics,details,ratio)
    if choice is None:
        if before['shape_overlaps'] or before['line_through_shapes']:
            raise RuntimeError('No feasible route preserving safety constraints')
        candidate_paths={i:source_paths[i] for i in {z[0] for z in seq+assocs}}
        choice=((before['crossings'].get('flow_association',0),before['crossings'].get('association_association',0),
                 before['crossings'].get('flow_flow',0),1e9),old,candidate_paths,before,
                 {'fallback':'input geometry retained to avoid quality regressions'},1.)
    objective,boxes,paths,after,details,ratio=choice
    # In small-output mode no shapes are resized. Only BPMN-DI and explicitly
    # whitelisted redundant business associations change.
    set_di(root,plane,boxes,paths)
    lane_compact_horizontal(root,plane,lane_names,boxes)
    labelled=save_labels(root,plane,boxes,nodes,paths)
    flow_labels=arrange_flow_labels(root,plane,boxes,seq,paths)
    remaining_assocs={i:(u,v,d) for i,u,v,d in assocs}
    if {i:(u,v,name) for i,u,v,name in seq}!=source_edges or remaining_assocs!={k:v for k,v in original_assocs.items() if k not in dropped}:
        raise RuntimeError('Unexpected business flow edit')
    if any(old[id][2:]!=boxes[id][2:] for id in old):raise RuntimeError('Object dimensions changed')
    # Exact non-DI XML equality except association ids on the explicit whitelist.
    expected=copy.deepcopy(process_start)
    for elm in list(expected.iter()):
        if elm.get('id') in dropped:elm.getparent().remove(elm)
    actual=copy.deepcopy(process)
    ET.cleanup_namespaces(expected)
    ET.cleanup_namespaces(actual)
    if ET.tostring(expected,method='c14n')!=ET.tostring(actual,method='c14n'):
        raise RuntimeError('Unapproved process-level XML change')
    # The rest of the XML (outside the process) must also be unchanged apart
    # from BPMN-DI. Compare canonical normalized entire documents.
    origtree=ET.parse(str(input));origroot=copy.deepcopy(origtree.getroot())
    newroot=copy.deepcopy(root)
    for copyroot in (origroot,newroot):
        for child in list(copyroot):
            if child.tag.startswith('{'+BD+'}'):copyroot.remove(child)
        ET.cleanup_namespaces(copyroot)
    for el in list(origroot.iter()):
        if el.get('id') in dropped:el.getparent().remove(el)
    ET.cleanup_namespaces(origroot)
    if ET.tostring(origroot,method='c14n')!=ET.tostring(newroot,method='c14n'):
        raise RuntimeError('Non-DI XML change outside explicit association whitelist')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    tree.write(str(output),encoding='utf-8',xml_declaration=True)
    reread=read_bpmn(output)
    problems=validate_di(reread[1],reread[4],reread[7],reread[5],reread[6],reread[10],reread[11])
    if problems:raise RuntimeError('Invalid BPMN-DI '+str(problems))
    if svg:
        svg_render(Path(svg),root,boxes,nodes,docs,seq,assocs,paths,lane_names,lane_boxes(root,plane,lane_names),{'title': process_title or process.get('name') or Path(input).stem})
        apply_di_labels_to_svg(Path(svg),root,nodes,seq,flow_labels)
        if png:
            import cairosvg
            cairosvg.svg2png(url=str(svg),write_to=str(png),output_width=png_width)
    out={'input':str(input),'output':str(output),'scale':ratio,
         'removed_redundant_associations':dropped,'changed_business_routes':0,
         'unchanged_sequence_flows':len(seq),'unchanged_business_nodes':len(nodes),
         'remaining_document_associations':len(assocs),'shape_dimensions_preserved':True,
         'source_semantic_digest':source_digest,'new_semantic_digest':semantic_digest(root),
         'process_semantic_diff_except_whitelist':0,'geometry_before':before,'geometry_after':after,
         'width_before':round(max(z[0]+z[2] for z in old.values())-min(z[0] for z in old.values()),2),
         'width_after':round(max(z[0]+z[2] for z in boxes.values())-min(z[0] for z in boxes.values()),2),
         'router_stats':details,'labels':labelled,'process_title':process_title or process.get('name') or Path(input).stem}
    if report:
        Path(report).parent.mkdir(parents=True,exist_ok=True)
        Path(report).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    return out
