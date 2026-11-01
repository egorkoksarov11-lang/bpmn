"""Small natural-loop candidates with explicit external interfaces, geometry only."""
def discover(macros,edges,roots,max_nodes=6):
    out={n:set() for n in macros};inc={n:set() for n in macros}
    for eid,u,v in edges:
        if u!=v:out[u].add(v);inc[v].add(u)
    roots=set(roots)|{n for n in macros if not inc[n]};active=set();todo=list(roots)
    while todo:
        n=todo.pop()
        if n not in active:active.add(n);todo.extend(out[n]-active)
    dom={n:({n} if n in roots else set(active)) for n in active};changed=True
    while changed:
        changed=False
        for n in sorted(active-roots):
            ps=inc[n]&active;value={n}|(set.intersection(*(dom[p] for p in ps)) if ps else set())
            if value!=dom[n]:dom[n]=value;changed=True
    found={}
    for eid,tail,header in edges:
        if header==tail or header not in dom.get(tail,set()):continue
        body={header,tail};todo=[tail]
        while todo:
            n=todo.pop()
            for p in inc[n]:
                if p not in body:body.add(p);todo.append(p)
        if not 2<=len(body)<=max_nodes:continue
        key=tuple(sorted(body))
        if key not in found:
            found[key]={'nodes':list(key),'header':header,'returns':[],'boundary_ports':[{'edge':i,'source':u,'target':v,'direction':'in' if v in body else 'out'} for i,u,v in edges if (u in body)!=(v in body)]}
        found[key]['returns'].append(eid)
    return [found[k] for k in sorted(found)]
