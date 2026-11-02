"""ELK layers/crossing order projected into immutable BPMN lane membership."""
from pathlib import Path
from statistics import median
from collections import defaultdict
import subprocess,json
from .human_search import HumanStyleBackend
from .human_layout import _proposals
from .patterns import analyze
from .readability import graph_returns
from .decision_layout import reflow


def pack_layers(items,membership,predecessors,wrap=None):
    """Assign non-overlapping lane cells, preserving ELK layer order.

    Alternate folded bands reverse horizontal reading to avoid a page-wide
    jump at the wrap boundary. Band changes remain inside the same role.
    """
    layers=sorted({r['layer'] for r in items});index={l:i for i,l in enumerate(layers)};rows={};slots={};bands={};used=set();width=wrap or len(layers)
    # Reserve enough rows per band for the busiest layer of each lane.
    capacities=defaultdict(lambda:1);counts=defaultdict(int)
    for it in items:counts[membership[it['id']],it['layer']]+=1
    for (lane,layer),count in counts.items():capacities[lane]=max(capacities[lane],count)
    for it in sorted(items,key=lambda r:(r['layer'],r.get('phase',r['layer']),r['y'],r['id'])):
        n=it['id'];lane=membership[n];phase=index[it['layer']];band=phase//width;col=phase%width
        if band%2:col=width-1-col
        preferred=median([rows[p] for p in predecessors.get(n,[]) if p in rows and membership[p]==lane]) if any(p in rows and membership[p]==lane for p in predecessors.get(n,[])) else 0
        options=[r for r in range(capacities[lane]) if (lane,band,col,r) not in used];row=min(options,key=lambda r:(abs(r-preferred),r))
        used.add((lane,band,col,row));rows[n]=row;slots[n]=(col,band*(capacities[lane]+1)+row);bands[n]=band
    return slots,bands


class ElkBackend(HumanStyleBackend):
    name='v23-elk-lane-projection'
    def __init__(self,elk_module=None,align_handoffs=True,**kwargs):
        super().__init__(orient_decisions=False,**kwargs);self.elk_module=elk_module;self.align_handoffs=align_handoffs
    def placements(self,nodes,docs,seq,assocs,member,lanes,original):
        motifs=analyze(nodes,seq,member,original);owner=motifs['owner'];returns=graph_returns(nodes,seq)
        edges=[(i,owner[u],owner[v]) for i,u,v,_ in seq if owner[u]!=owner[v] and i not in returns];pred=defaultdict(list)
        for _,u,v in edges:pred[v].append(u)
        grouping=handoff_groups(motifs['macros'],edges,member) if self.align_handoffs else {n:n for n in motifs['macros']}
        group_ids=sorted(set(grouping.values()))
        graph={'id':'root','layoutOptions':{'elk.algorithm':'layered','elk.direction':'RIGHT','elk.edgeRouting':'ORTHOGONAL','elk.layered.layering.strategy':'NETWORK_SIMPLEX','elk.layered.generatePositionAndLayerIds':'true','elk.layered.spacing.nodeNodeBetweenLayers':'40','elk.spacing.nodeNode':'35','elk.randomSeed':'23'},'children':[{'id':n,'width':300 if n in motifs['pairs'] else 220,'height':100} for n in group_ids],'edges':[{'id':i,'sources':[grouping[u]],'targets':[grouping[v]]} for i,u,v in edges if grouping[u]!=grouping[v]]}
        cmd=['node',str(Path(__file__).parent/'assets/elk_runner.cjs')]
        if self.elk_module:cmd.append(str(Path(self.elk_module).resolve()))
        result=subprocess.run(cmd,input=json.dumps(graph),text=True,capture_output=True,timeout=45)
        if result.returncode:raise RuntimeError('ELK failed: '+result.stderr[:400])
        raw=json.loads(result.stdout);items=[];right=None;layer=-1
        # elkjs does not serialize internal layerId properties in this build.
        # Disjoint layer intervals recover the ordered layers from geometry.
        for n in sorted(raw['children'],key=lambda n:(n['x'],n['id'])):
            if right is None or n['x']>=right-.01:layer+=1;right=n['x']+n['width']
            else:right=max(right,n['x']+n['width'])
            items.append({'id':n['id'],'layer':layer,'y':n['y']})
        expanded=[]
        for item in items:
            expanded.extend({**item,'id':n} for n,g in grouping.items() if g==item['id'])
        items=expanded
        for group_size in (3,4):
            grouped=[{**it,'phase':it['layer'],'layer':it['layer']//group_size} for it in items]
            wrap=None
            plan,bands=pack_layers(grouped,member,pred,wrap)
            for n,o in nodes.items():
                if o['kind']=='startEvent':
                    nexts=[owner[v] for _,u,v,_ in seq if u==n and member[v]==member[n]]
                    if len(nexts)==1:plan[owner[n]]=plan[nexts[0]]
            left=min(c for c,r in plan.values());plan={n:(c-left,r) for n,(c,r) in plan.items()}
            for _,boxes,report in _proposals(nodes,docs,seq,assocs,member,lanes,original,secondary_rows=1,chain_depths=(2,),role_variants=0,slot_plan=plan,compact_doc_bays=True):
                orientations={a:'left' if bands[a]%2 else 'right' for a in report['pairs']}
                boxes=reflow(boxes,report,orientations,nodes,docs,member)
                report={**report,'external_engine':'elkjs@0.12.1','feedback_edges':sorted(returns),'fold_width':wrap,'decision_orientations':orientations,'layer_count':len({r['layer'] for r in items}),'layers_per_column':group_size,'handoff_groups':grouping}
                yield f'elk-layer-groups-{group_size}',boxes,report


def handoff_groups(macros,edges,membership):
    """Geometry-only contractions: at most one macro from each fixed lane."""
    parent={n:n for n in macros};roles={n:{membership[n]} for n in macros};degree_in=defaultdict(int);degree_out=defaultdict(int)
    def root(n):
        while parent[n]!=n:n=parent[n]
        return n
    for _,u,v in edges:degree_out[u]+=1;degree_in[v]+=1
    ordered=sorted(edges,key=lambda e:(not(degree_out[e[1]]==1 and degree_in[e[2]]==1),degree_out[e[1]]+degree_in[e[2]],e[0]))
    for _,u,v in ordered:
        a,b=root(u),root(v)
        if a==b or roles[a]&roles[b]:continue
        if degree_out[u]!=1 and degree_in[v]!=1:continue
        lo,hi=sorted([a,b]);parent[hi]=lo;roles[lo]|=roles[hi]
    return {n:root(n) for n in macros}
