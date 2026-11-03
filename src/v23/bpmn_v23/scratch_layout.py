"""Coordinate-free reconstruction: source DI is erased before any planning.

Only business XML, role membership, complete names and shape kinds survive.
Reference coordinates and input waypoints never enter either layout engine.
"""
from pathlib import Path
from collections import deque
import json,math,re,subprocess,tempfile,time
from bpmn_refkit.model import read_bpmn,TAG_TASK,TAG_GATE,TAG_EVENT
from bpmn_universal.contract import NS,semantic_equality
from .di_geometry import update_geometry
from .typography import task_layout
from .freeze import equal as di_equal
from .human_search import HumanStyleBackend
from .attachment_axes import attachment_axes
from .readability import graph_returns
from .quality import score
from .patterns import analyze
from .elk_layout import handoff_groups


def semantic_document_owners(nodes,docs,assocs,boxes):
    owners={}
    for d in docs:
        links={v if u==d else u for _,u,v,_ in assocs if d in (u,v)}&nodes.keys()
        writers={u for _,u,v,_ in assocs if v==d and u in nodes}
        if links:owners[d]=min(writers or links)
    return owners


def independent_scenarios(nodes,seq,docs,assocs):
    neighbours={n:set() for n in nodes}
    for _,u,v,_ in seq:neighbours[u].add(v);neighbours[v].add(u)
    components=[];seen=set()
    for start in sorted(nodes):
        if start in seen:continue
        todo=[start];component=set()
        while todo:
            n=todo.pop()
            if n in component:continue
            component.add(n);todo.extend(neighbours[n]-component)
        seen|=component;components.append(component)
    owner={n:i for i,c in enumerate(components) for n in c};deps=set()
    for d in docs:
        writers={u for _,u,v,_ in assocs if v==d and u in nodes};readers={v for _,u,v,_ in assocs if u==d and v in nodes}
        deps|={(owner[w],owner[r]) for w in writers for r in readers if owner[w]!=owner[r]}
    def hint(i):
        component=components[i]
        return (len(component),sum(u in component and v in component for _,u,v,*_ in seq),min(component))
    remaining=set(range(len(components)));order=[]
    while remaining:
        ready={c for c in remaining if not any(v==c and u in remaining for u,v in deps)}
        chosen=min(ready or remaining,key=hint);order.append(chosen);remaining.remove(chosen)
    return [components[i] for i in order],sorted(deps)


def canonical_task(name,kind):
    for w in (180,200,220,240):
        b=(0,0,w,76);fit=task_layout(name,b,kind)
        if fit['fits'] and fit['font_size']>=11:return w,76
    fit=task_layout(name,(0,0,240,76),kind)
    return 240,max(76,math.ceil(fit['required_height']/4)*4)


def semantic_role_order(nodes,seq,member,lanes):
    outgoing={n:[] for n in nodes};indegree={n:0 for n in nodes}
    for _,u,v,_ in seq:outgoing[u].append(v);indegree[v]+=1
    roots=sorted(n for n,o in nodes.items() if o['kind']=='startEvent' or indegree[n]==0);distance={n:0 for n in roots};queue=deque(roots)
    while queue:
        u=queue.popleft()
        for v in outgoing[u]:
            if v not in distance:distance[v]=distance[u]+1;queue.append(v)
    return sorted(lanes,key=lambda lane:(min((distance.get(n,10**9) for n in nodes if member.get(n)==lane),default=10**9),lane))


def erase_geometry(source,target):
    tree,root,_,plane,nodes,seq,assocs,docs,member,lanes,boxes,paths=read_bpmn(source)
    role_order=semantic_role_order(nodes,seq,member,lanes)
    neutral={}
    for n in sorted(boxes):
        if n in nodes:
            kind=nodes[n]['kind']
            w,h=canonical_task(nodes[n].get('name',''),kind) if kind in TAG_TASK else (50,50) if kind in TAG_GATE else (36,36)
            neutral[n]=(200-w/2,200-h/2,w,h)
        elif n in docs:
            w,h=(50,48) if docs[n]['kind']=='dataStoreReference' else (36,50)
            neutral[n]=(200-w/2,200-h/2,w,h)
        elif n in lanes:neutral[n]=(30,65+role_order.index(n)*200,1000,200)
        else:neutral[n]=(0,65,1030,max(200,len(lanes)*200))
    dummy={i:[(200,200),(200,200)] for i in paths}
    update_geometry(root,plane,neutral,dummy)
    for label in root.xpath('.//bd:BPMNLabel',namespaces=NS):label.getparent().remove(label)
    tree.write(str(target),encoding='utf-8',xml_declaration=True)
    if not semantic_equality(source,target) or not di_equal(source,target):raise ValueError('Canonicalization freeze violation')
    return {'source_positions_used':False,'source_dimensions_used':False,'source_waypoints_used':False,'source_label_bounds_used':False,'external_incumbent_used':False,
            'source_lane_order_used':False,'role_order_method':'graph distance from starts; opaque ID tie break; business XML lane order unchanged',
            'inputs':'business graph, fixed role membership, full names, shape kinds; neutral canonical DI and measured text sizes'}


class GraphChannelsBackend(HumanStyleBackend):
    name='v23-semantic-layers-and-local-information'
    preserve_labels=True
    straight_documents=True
    simplify_routes=True
    return_corridors=True
    def __init__(self,role_order=None,search_seconds=None,**kwargs):
        super().__init__(orient_decisions=False,**kwargs);self.max_search_seconds=max(45,self.candidate_seconds*8) if search_seconds is None else search_seconds;self.role_order=role_order
        if not math.isfinite(self.max_search_seconds) or self.max_search_seconds<=0:raise ValueError('search_seconds must be positive')
    def candidate_rank(self,path,boxes,paths,uv,nodes,docs,seq):
        from .layout_objective import objective
        model=read_bpmn(path)
        labels=[tuple(float(b.get(k)) for k in ('x','y','width','height')) for b in model[1].xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS)]
        value,detail=objective(boxes,paths,nodes,seq,model[8],docs,model[6],labels)
        return round(value/max(1,len(seq)),6),score(paths,uv),round(detail['packing'],6)
    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        returns=graph_returns(nodes,seq)
        motifs=analyze(nodes,[e for e in seq if e[0] not in returns],member,original);macro_owner=motifs['owner']
        primary={(u,v) for c in motifs['components'] for u,v in zip(c['backbone'],c['backbone'][1:])}
        grouping=handoff_groups(nodes,[(i,u,v) for i,u,v,_ in seq if i not in returns],member)
        groups=sorted(set(grouping.values()));sizes={g:(max(original[n][2] for n in nodes if grouping[n]==g),max(original[n][3] for n in nodes if grouping[n]==g)) for g in groups}
        for layering in ('NETWORK_SIMPLEX','LONGEST_PATH'):
            children=[{'id':g,'width':sizes[g][0],'height':sizes[g][1]} for g in groups]
            graph={'id':'root','layoutOptions':{'elk.algorithm':'layered','elk.direction':'RIGHT','elk.edgeRouting':'ORTHOGONAL','elk.layered.layering.strategy':layering,
                'elk.layered.nodePlacement.strategy':'BRANDES_KOEPF','elk.layered.nodePlacement.bk.fixedAlignment':'BALANCED','elk.layered.spacing.nodeNodeBetweenLayers':'28',
                'elk.spacing.nodeNode':'40','elk.randomSeed':'23','elk.separateConnectedComponents':'true'},'children':children,
                'edges':[{'id':i,'sources':[grouping[u]],'targets':[grouping[v]],'layoutOptions':{'elk.layered.priority.straightness':'20' if macro_owner[u]==macro_owner[v] or (macro_owner[u],macro_owner[v]) in primary else '1','elk.layered.priority.shortness':'10' if (macro_owner[u],macro_owner[v]) in primary else '1'}} for i,u,v,_ in seq if i not in returns and grouping[u]!=grouping[v]]}
            proc=subprocess.run(['node',str(Path(__file__).parent/'assets/elk_runner.cjs')],input=json.dumps(graph),capture_output=True,text=True,timeout=30)
            if proc.returncode:raise RuntimeError('ELK semantic graph failed: '+proc.stderr[:300])
            raw=json.loads(proc.stdout);generated=dict(original)
            for group in raw['children']:
                for n in nodes:
                    if grouping[n]!=group['id']:continue
                    w,h=original[n][2:];generated[n]=(group['x']+100+(group['width']-w)/2,group['y']+100+(group['height']-h)/2,w,h)
            # Independent scenarios start at the same left reading margin.
            # ELK component-packing offsets are not meaningful process phases.
            components,dependencies=independent_scenarios(nodes,seq,docs,assocs)
            for gap in (24,40):
                basis=dict(generated);spines=[]
                if gap==24:
                    from .semantic_spines import align_spines
                    basis,spines=align_spines(basis,motifs,nodes,seq,member,grouping,gap)
                cursor=100
                for component in components:
                    left=min(basis[n][0] for n in component);top=min(basis[n][1] for n in component);bottom=max(basis[n][1]+basis[n][3] for n in component)
                    for n in component:
                        x,y,w,h=basis[n];basis[n]=(x-left+100,y-top+cursor,w,h)
                    cursor+=bottom-top+80
                # Information owners come from semantic directions, never from
                # the former coordinates of a document in the input diagram.
                for d,owner in semantic_document_owners(nodes,docs,assocs,basis).items():
                    x,y,w,h=basis[owner];dw,dh=original[d][2:];basis[d]=(x+w/2-dw/2,y+h+24,dw,dh)
                try:boxes,report=attachment_axes(nodes,docs,seq,assocs,member,lanes,basis,gap_size=gap,compact_bays=gap==24,overlap_corridors=getattr(self,'overlap_corridors',False))
                except ValueError:continue
                if gap==24:
                    from .skyline_layout import compact_rows
                    boxes,report=compact_rows(boxes,report,nodes,docs,member,lanes,seq)
                if self.role_order is not None:
                    from .lane_ordering import reorder_lanes
                    boxes,report=reorder_lanes(boxes,report,nodes,docs,seq,member,lanes,self.role_order)
                report.update(external_engine='elkjs@0.12.1-semantic-graph-only',layering=layering,source_geometry_used=False,feedback_edges=sorted(returns),scenario_dependency_hints=dependencies,scenario_order=[sorted(c) for c in components],handoff_groups=grouping,semantic_spines=spines)
                yield f'semantic-{layering.lower()}-gap-{gap}',boxes,report
        # This fallback also receives only the erased canonical model.
        for name,boxes,report in super().placements(nodes,docs,seq,assocs,member,lanes,original):
            if self.role_order is not None:
                from .lane_ordering import reorder_lanes
                boxes,report=reorder_lanes(boxes,report,nodes,docs,seq,member,lanes,self.role_order)
            yield name,boxes,report


class ScratchBackend:
    name='v23-from-scratch'
    preserve_labels=True
    source_geometry_used=False
    def __init__(self,candidate_seconds=30,control=False,role_order=None,search_seconds=None,graph_backend=None,staged_windows=True):
        if control and role_order is not None:raise ValueError('Role optimization requires the graph scratch backend')
        self.candidate_seconds=candidate_seconds;self.control=control;self.role_order=role_order;self.search_seconds=search_seconds;self.graph_backend=graph_backend;self.staged_windows=staged_windows

    def layout(self,source,output,svg):
        started=time.monotonic()
        with tempfile.TemporaryDirectory(prefix='semantic-only-',dir=Path(output).parent) as folder:
            neutral=Path(folder)/'neutral.bpmn';erasure=erase_geometry(source,neutral)
            if self.control:
                backend=HumanStyleBackend(candidate_seconds=self.candidate_seconds,orient_decisions=False)
            else:
                from .episode_layout import EpisodeGraphBackend
                backend=(self.graph_backend or EpisodeGraphBackend)(candidate_seconds=self.candidate_seconds,role_order=self.role_order,search_seconds=self.search_seconds)
            result=backend.layout(neutral,output,svg)
            if not self.control and getattr(backend,'local_episode_editing',False):
                from .cold_guard import protect_cold_result
                guard,adopted=protect_cold_result(neutral,output,svg,candidate_seconds=self.candidate_seconds,search_seconds=self.search_seconds or 200,role_order=self.role_order)
                if adopted is not None:
                    result['primary_candidate_before_guard']=result['selected_candidate']
                    result['selected_candidate']='internal-cold-guard/'+adopted['selected_candidate']
                result['internal_cold_guard']=guard
            if not self.control:
                from .attachment_refinement import compact_attachments
                final=read_bpmn(output);anchors=semantic_document_owners(final[4],final[7],final[6],final[-2])
                result['local_attachment_moves']=compact_attachments(output,svg,neutral,seconds=min(12,self.candidate_seconds*2),fixed_owners=anchors)
                if getattr(backend,'local_episode_editing',False):
                    from .local_editing import edit_groups
                    result['local_episode_edits']=edit_groups(output,svg,neutral,seconds=min(24,self.candidate_seconds*2))
                    from .port_refinement import refine_ports
                    result['port_refinement']=refine_ports(output,svg,neutral,seconds=min(24,self.candidate_seconds*2))
                    if self.staged_windows:
                        from .graph_refinement import refine_graph
                        refinement=refine_graph(output,svg,neutral,seconds=min(100,self.candidate_seconds*3))
                        result['graph_refinement']=refinement
                        if refinement['rounds']:
                            result['staged_window_refinement']=refinement['rounds'][0]['groups']
                            result['current_role_refinement']=refinement['rounds'][-1]['roles']
                    from .whitespace import compact_whitespace
                    result['whitespace_compaction']=compact_whitespace(output,svg,neutral)
            if not semantic_equality(source,output) or not di_equal(source,output):raise ValueError('Scratch output freeze violation')
        result['geometry_erasure']=erasure;result['from_scratch']=True;result['seconds']=round(time.monotonic()-started,3)
        result['reference_target_met']=False
        result['structural_signals']={'sequence_links':True,'data_links':True,'role_membership':True,'bpmn_kinds':True,'names':False,'step_numbers':False,'text_usage':'measured typography only; no lexical meaning or ordering'}
        return result
