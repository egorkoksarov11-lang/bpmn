"""Explicit productive spines and short side branches, from business graph only."""
from collections import defaultdict,deque
from statistics import median


def align_spines(boxes,motifs,nodes,seq,member,grouping,gap=24):
    out=dict(boxes);old_centres={n:(b[0]+b[2]/2,b[1]+b[3]/2) for n,b in boxes.items() if n in nodes}
    owner=motifs['owner'];incoming=defaultdict(list);outgoing=defaultdict(list)
    for _,u,v,_ in seq:incoming[v].append(u);outgoing[u].append(v)
    groups=defaultdict(list)
    for n,g in grouping.items():groups[g].append(n)
    reports=[]
    for component in motifs['components']:
        path=[]
        for macro in component['backbone']:
            path.append(macro)
            if macro in motifs['pairs']:path.append(motifs['pairs'][macro])
        main=set(path);allowed={n for n in nodes if owner[n] in component['nodes']}
        if not path:continue
        row_y={l:median(old_centres[n][1] for n in path if member[n]==l) for l in {member[n] for n in path}}
        phase={};previous=None
        for n in path:
            group=grouping[n]
            frame=max(boxes[v][2] if nodes[v]['kind']!='startEvent' or not nodes[v].get('name') else 140 for v in groups[group])
            if group not in phase:
                phase[group]=0 if previous is None else phase[previous[0]]+previous[1]/2+frame/2+gap
            previous=(group,frame)
        for n in allowed:
            if grouping[n] in phase:
                x,y,w,h=out[n];out[n]=(phase[grouping[n]]-w/2,y,w,h)
        for n in path:
            x,y,w,h=out[n];out[n]=(x,row_y[member[n]]-h/2,w,h)
        placed=[(member[n],out[n]) for n in path]
        for n in sorted(allowed-main,key=lambda n:(old_centres[n][0],old_centres[n][1],n)):
            # Find a graph ancestor on the main spine; no names or DI positions
            # determine which business edge is the continuation.
            queue=deque(incoming[n]);seen=set();anchor=None
            while queue:
                u=queue.popleft()
                if u in seen:continue
                seen.add(u)
                if u in main:anchor=u;break
                queue.extend(incoming[u])
            x,y,w,h=out[n]
            if anchor is not None and grouping[n] not in phase:
                new_cx=out[anchor][0]+out[anchor][2]/2+(old_centres[n][0]-old_centres[anchor][0])
                if anchor in incoming[n] and len(outgoing[anchor])>1 and member[n]==member[anchor] and len(groups[grouping[n]])==1:
                    new_cx=out[anchor][0]+out[anchor][2]/2
                x=new_cx-w/2
            if member[n] in row_y:
                cy=row_y[member[n]];main_height=max(out[v][3] for v in path if member[v]==member[n]);distance=(main_height+h)/2+48
                y=cy+distance-h/2
            else:distance=h+48
            while any(lane==member[n] and min(x+w+8,b[0]+b[2])-max(x-8,b[0])>0 and min(y+h+8,b[1]+b[3])-max(y-8,b[1])>0 for lane,b in placed):y+=distance
            out[n]=(x,y,w,h);placed.append((member[n],out[n]))
        reports.append({'main_path':path,'side_nodes':sorted(allowed-main),'method':'longest productive semantic path; fixed roles; common row and separated columns; short fork branches'})
    return out,reports
