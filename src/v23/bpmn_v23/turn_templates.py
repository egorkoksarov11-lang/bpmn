"""Readable serial turns occur at activities, not on a reset-to-left wire."""
from .quality import path_length


def turn_proposals(region,state,gap=28):
    nodes,seq,assocs,docs,member,lanes,boxes,paths=state[4:]
    ids=region['nodes'];edges={(u,v) for i,u,v,*_ in seq}
    if not 3<=len(ids)<=6 or len({member[n] for n in ids})!=1:return
    if not all((u,v) in edges for u,v in zip(ids,ids[1:])):return
    anchor=ids[0];a=boxes[anchor];origin=(a[0]+a[2]/2,a[1]+a[3]/2);variants=[]
    for cut in range(1,len(ids)-1):
        for name,first,last in [('right-down',(1,0),(0,1)),('down-right',(0,1),(1,0)),('right-up',(1,0),(0,-1)),('up-right',(0,-1),(1,0))]:
            proposal={anchor:a};cx,cy=origin
            for j,(u,v) in enumerate(zip(ids,ids[1:]),1):
                dx,dy=first if j<=cut else last;old=boxes[u];new=boxes[v]
                cx+=dx*(old[2]/2+gap+new[2]/2);cy+=dy*(old[3]/2+gap+new[3]/2)
                proposal[v]=(cx-new[2]/2,cy-new[3]/2,*new[2:])
            # Boundary links matter before routing. A local fold that moves its
            # exit away from the following interaction is usually a bad choice.
            travel=0
            for i,u,v,*_ in seq:
                if (u in proposal)==(v in proposal):continue
                aa=proposal.get(u,boxes[u]);bb=proposal.get(v,boxes[v])
                travel+=abs(aa[0]+aa[2]/2-bb[0]-bb[2]/2)+abs(aa[1]+aa[3]/2-bb[1]-bb[3]/2)
            width=max(b[0]+b[2] for b in proposal.values())-min(b[0] for b in proposal.values())
            height=max(b[1]+b[3] for b in proposal.values())-min(b[1] for b in proposal.values())
            variants.append((travel+.1*(width+height),f'turn-{name}-{cut}',proposal))
    for _,name,proposal in sorted(variants,key=lambda x:(x[0],x[1])):yield name,proposal
