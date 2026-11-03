"""Explicit presentation simplification; the complete source remains unchanged.

A caller must opt in. Every omitted reference/association is journalled, and
workflow XML and logical data definitions are independently frozen.
"""
from pathlib import Path
from collections import defaultdict,deque
import copy,hashlib,json
from lxml import etree as ET
from bpmn_universal.contract import parse,NS,B,BD,Q
from bpmn_refkit.model import read_bpmn,TAG_TASK


def first_appearance_plan(source,omissions=None):
    omissions=omissions or {};m=read_bpmn(source);root=m[1];nodes,seq,assocs,docs=m[4:8]
    for d,explanation in omissions.items():
        if d not in docs or not isinstance(explanation,str) or not explanation.strip():raise ValueError('Every explicit omitted document needs an existing ID and a reason')
    neighbours=defaultdict(list);indegree=defaultdict(int)
    for _,u,v,_ in seq:neighbours[u].append(v);indegree[v]+=1
    roots=sorted(n for n,o in nodes.items() if o['kind']=='startEvent' or not indegree[n]);distance={n:0 for n in roots};queue=deque(roots)
    while queue:
        u=queue.popleft()
        for v in sorted(neighbours[u]):
            if v not in distance:distance[v]=distance[u]+1;queue.append(v)
    from .readability import graph_returns
    returns=graph_returns(nodes,seq);forward=defaultdict(list)
    for i,u,v,_ in seq:
        if i not in returns:forward[u].append(v)
    # Dominator returns do not cover every repair loop. Remove DFS back links
    # for this occurrence analysis only; all workflow transitions stay intact.
    acyclic=defaultdict(list);colour={}
    for start in roots+sorted(nodes):
        if colour.get(start):continue
        colour[start]=1;stack=[(start,iter(sorted(forward[start])))]
        while stack:
            u,targets=stack[-1]
            try:v=next(targets)
            except StopIteration:colour[u]=2;stack.pop();continue
            if colour.get(v)==1:continue
            acyclic[u].append(v)
            if not colour.get(v):colour[v]=1;stack.append((v,iter(sorted(forward[v]))))
    forward=acyclic
    reachable={}
    for n in nodes:
        seen=set();todo=list(forward[n])
        while todo:
            other=todo.pop()
            if other in seen:continue
            seen.add(other);todo.extend(forward[other])
        reachable[n]=seen
    elements={e.get('id'):e for e in root.iter() if e.get('id')};groups=defaultdict(list)
    for d,o in docs.items():
        if d in omissions:continue
        e=elements[d];state=e.find(Q(B,'dataState'));state_key=ET.tostring(state,method='c14n') if state is not None else b''
        identity=e.get('dataObjectRef') or e.get('dataStoreRef') or d
        groups[(o['kind'],identity,state_key)].append(d)
    related={i for i,u,v,_ in assocs if u in docs and v in nodes or v in docs and u in nodes}
    protected={d for i,u,v,_ in assocs if i not in related for d in (u,v) if d in docs}
    if protected & omissions.keys():raise ValueError('Cannot omit a reference used by a non-operation association')
    kept=[];chosen_refs=set(protected);decisions=[]
    for refs in groups.values():
        candidates=[]
        for i,u,v,kind in assocs:
            d=u if u in refs else v if v in refs else None
            if d is None:continue
            n=v if u==d else u
            if n not in nodes:continue
            # Gateways merely test data; a nearby real operation owns the glyph.
            rank=(nodes[n]['kind'] not in TAG_TASK,distance.get(n,10**9),u!=n,n,i)
            candidates.append((rank,i,d,n))
        if not candidates:
            # Unconnected references still denote distinct information; retain one.
            d=min(refs);chosen_refs.add(d);decisions.append({'reference':d,'kept_association':None,'reason':'first logical reference; no operation links'});continue
        store=docs[refs[0]]['kind']=='dataStoreReference'
        writers={n for _,i,d,n in candidates for eid,u,v,kind in assocs if eid==i and (v==d and kind=='One' or kind=='Both')}
        frontier={w for w in writers if not any(w in reachable[other] and other not in reachable[w] for other in writers-{w})}
        reason='first substantive use of existing information'
        selected=candidates
        if not store and frontier:
            # Several contributors may assemble one package, or alternative
            # branches may produce the same result. Prefer their first common
            # receiving operation over wiring the document to every contributor.
            common=[c for c in candidates if nodes[c[3]]['kind'] in TAG_TASK and all(c[3]==w or c[3] in reachable[w] for w in frontier)] if len(frontier)>1 else []
            if common:selected=common;reason='first common operation after initial contributors or alternative producers'
            else:selected=[c for c in candidates if c[3] in frontier];reason='first producing operation; later reuse is implicit'
        _,edge,d,node=min(selected);kept.append(edge);chosen_refs.add(d)
        decisions.append({'reference':d,'kept_association':edge,'first_operation':node,'reason':reason,'initial_producers':sorted(frontier)})
    remove_refs=sorted(set(docs)-chosen_refs);remove_edges=sorted(related-set(kept))
    # Preserve non-document associations; the policy is not workflow deletion.
    removed=remove_refs+remove_edges;removed_di=[e.get('id') for e in root.xpath('.//bd:BPMNShape|.//bd:BPMNEdge',namespaces=NS) if e.get('bpmnElement') in removed]
    return {'policy':'first-appearance; one visible connection per logical document/state','authorized_scope':'presentation-only document references and their associations; workflow and logical data definitions unchanged',
            'source_sha256':hashlib.sha256(Path(source).read_bytes()).hexdigest(),'removed_reference_ids':remove_refs,'removed_association_ids':remove_edges,'removed_di_ids':removed_di,
            'decisions':decisions,'protected_reference_ids':sorted(protected),'reviewed_omissions':omissions,'removed_business_xml':{i:ET.tostring(elements[i],encoding='unicode') for i in removed},
            'before':{'information_objects':len(docs),'information_links':len(assocs)},'after':{'information_objects':len(chosen_refs),'information_links':len(assocs)-len(remove_edges)}}


def allowed_projection_equal(source,target,plan):
    root=parse(source);removed=set(plan['removed_reference_ids']+plan['removed_association_ids'])
    for e in list(root.iter()):
        if e.get('id') in removed:e.getparent().remove(e)
    # Use the same canonical comparator as the standard pipeline.
    other=parse(target)
    def canonical(r):
        r=copy.deepcopy(r)
        for diagram in r.xpath('.//bd:BPMNDiagram',namespaces=NS):diagram.getparent().remove(diagram)
        for e in r.iter():
            if e.text and not e.text.strip():e.text=None
            if e.tail and not e.tail.strip():e.tail=None
        ET.cleanup_namespaces(r);return ET.tostring(r,method='c14n')
    return canonical(root)==canonical(other)


def apply_first_appearance(source,target,journal,omissions=None):
    if Path(source).resolve()==Path(target).resolve():raise ValueError('Presentation projection must be separate from source')
    from .pipeline import validate_xml
    validate_xml(source)
    plan=first_appearance_plan(source,omissions)
    Path(journal).parent.mkdir(parents=True,exist_ok=True)
    Path(journal).write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    root=parse(source);removed=set(plan['removed_reference_ids']+plan['removed_association_ids'])
    for e in list(root.iter()):
        if e.get('id') in removed or e.tag in {Q(BD,'BPMNShape'),Q(BD,'BPMNEdge')} and e.get('bpmnElement') in removed:e.getparent().remove(e)
    Path(target).parent.mkdir(parents=True,exist_ok=True);ET.ElementTree(root).write(str(target),encoding='utf-8',xml_declaration=True)
    if not allowed_projection_equal(source,target,plan):raise ValueError('Unexpected changes outside document whitelist')
    from .pipeline import validate_xml
    validate_xml(target)
    plan['workflow_and_data_definitions_equal']=True
    Path(journal).write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    return plan
