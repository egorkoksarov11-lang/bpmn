"""Graph topology identifies local phases; step names and numbers are never read."""
from collections import defaultdict,deque
from .patterns import analyze
from .readability import graph_returns
from .scratch_layout import semantic_document_owners
from .attachment_axes import attachment_axes
from .skyline_layout import compact_rows


def semantic_stages(nodes,seq,member,original):
    from .graph_topology import region_stages
    motifs=analyze(nodes,seq,member,original,pair_merges=False)
    return motifs,region_stages(nodes,seq,member,motifs)


def stage_proposal(nodes,docs,seq,assocs,member,lanes,original):
    motifs,stages=semantic_stages(nodes,seq,member,original)
    stage_index={v:i for i,v in enumerate(sorted(set(stages.values())))}
    main=[n for c in motifs['components'] for n in c['backbone']];main_index={n:i for i,n in enumerate(main)}
    counts=defaultdict(int);slots={}
    for n in sorted(motifs['macros'],key=lambda n:(stage_index[stages[n]],main_index.get(n,10**6),n)):
        col=stage_index[stages[n]];key=member[n],col;row=counts[key];counts[key]+=1;slots[n]=(col,row)
    widths=defaultdict(float);heights=defaultdict(float)
    for n,(col,row) in slots.items():
        w,h=original[n][2:];g=motifs['pairs'].get(n);widths[col]=max(widths[col],w+(original[g][2]+28 if g else 0));heights[member[n],row]=max(heights[member[n],row],h)
    xs={};cursor=120
    for col in sorted(widths):xs[col]=cursor;cursor+=widths[col]+40
    ys={};cursor=100
    for l in lanes:
        for r in sorted({row for n,(col,row) in slots.items() if member[n]==l}):ys[l,r]=cursor;cursor+=heights[l,r]+180
        cursor+=80
    basis=dict(original)
    for n,(col,row) in slots.items():
        x,y=xs[col],ys[member[n],row];w,h=original[n][2:];basis[n]=(x,y,w,h)
        if n in motifs['pairs']:
            g=motifs['pairs'][n];gw,gh=original[g][2:];basis[g]=(x+w+28,y+h/2-gh/2,gw,gh)
    for d,n in semantic_document_owners(nodes,docs,assocs,basis).items():
        x,y,w,h=basis[n];dw,dh=original[d][2:];basis[d]=(x,y+h+24,dw,dh)
    for i,l in enumerate(lanes):basis[l]=(30,65+i*1000,2000,1000)
    boxes,report=attachment_axes(nodes,docs,seq,assocs,member,lanes,basis,gap_size=32,compact_bays=True,overlap_corridors=True)
    boxes,report=compact_rows(boxes,report,nodes,docs,member,lanes,seq)
    report.update(external_engine='graph-region-episodes',source_geometry_used=False,stage_labels=stages,stage_count=len(stage_index))
    return boxes,report
