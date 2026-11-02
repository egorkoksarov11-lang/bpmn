"""Pack row envelopes by occupied columns, sharing empty information bays.

Everything here is generated from the semantic graph. No reference coordinates
or source-DI rows are consulted. Routing runs after this placement stage.
"""
from collections import defaultdict


def compact_rows(boxes,report,nodes,docs,member,lanes,seq):
    out=dict(boxes);captions=dict(report.get('reserved_captions',{}));owners=report['document_owners']
    rows={n:tuple(r) for n,r in report['axis_rows'].items()};groups=defaultdict(list);glyphs=defaultdict(list);labels=defaultdict(list)
    for n in nodes:
        row=rows[n];groups[row].append(out[n]);glyphs[row].append(n)
    for d,owner in owners.items():
        row=rows[owner];groups[row].append(out[d]);glyphs[row].append(d)
    for n,b in captions.items():
        owner=owners[n] if n in docs else n;row=rows[owner];groups[row].append(b);labels[row].append(n)
    # Protect the horizontal continuation corridor as well as visible objects.
    for _,u,v,_ in seq:
        if rows[u]!=rows[v]:continue
        a,b=out[u],out[v];cy=a[1]+a[3]/2
        if abs(cy-b[1]-b[3]/2)>.1:continue
        left,right=(a,b) if a[0]<b[0] else (b,a)
        if left[0]+left[2]<right[0]:groups[rows[u]].append((left[0]+left[2],cy-8,right[0]-left[0]-left[2],16))
    cursor=min(out[l][1] for l in lanes);old_height=sum(out[l][3] for l in lanes);moves=[];new_axes=[]
    for lane in sorted(lanes,key=lambda l:out[l][1]):
        top=cursor;placed=[];previous=None;lane_rows=sorted((r for r in groups if r[0]==lane),key=lambda r:min(out[n][1]+out[n][3]/2 for n in nodes if rows[n]==r))
        for row in lane_rows:
            current_nodes=[n for n in nodes if rows[n]==row];old_centre=sum(out[n][1]+out[n][3]/2 for n in current_nodes)/len(current_nodes)
            height=max(out[n][3] for n in current_nodes);bounds=[top+20-min(b[1]-old_centre for b in groups[row])]
            if previous is not None:bounds.append(previous[0]+(previous[1]+height)/2+24)
            for b in groups[row]:
                for other in placed:
                    if min(b[0]+b[2]+8,other[0]+other[2])-max(b[0]-8,other[0])>0:
                        bounds.append(other[1]+other[3]+8-(b[1]-old_centre))
            centre=max(bounds);dy=centre-old_centre
            for n in glyphs[row]:
                x,y,w,h=out[n];out[n]=(x,y+dy,w,h)
            for n in labels[row]:
                x,y,w,h=captions[n];captions[n]=(x,y+dy,w,h)
            placed.extend((x,y+dy,w,h) for x,y,w,h in groups[row]);previous=(centre,height)
            moves.append({'row':list(row),'dy':round(dy,2)});new_axes.append([old_centre,centre])
        bottom=max((b[1]+b[3] for b in placed),default=top+100);cursor=max(top+120,bottom+20)
        x,_,w,_=out[lane];out[lane]=(x,top,w,cursor-top)
    first=min(out[l][1] for l in lanes)
    for n,b in out.items():
        if n not in nodes and n not in docs and n not in lanes:out[n]=(b[0],first,b[2],cursor-first)
    new_report={**report,'reserved_captions':captions,'row_skyline':{'moves':moves,'old_lane_height':old_height,'new_lane_height':cursor-first,'method':'occupied-column envelopes; measured captions; 8px object and corridor separation; fixed role membership'}}
    new_report['mapped_axes']={**report['mapped_axes'],'y':new_axes}
    return out,new_report
