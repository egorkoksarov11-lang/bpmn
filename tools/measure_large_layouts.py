"""Read-only diagnostics for one-process BPMN layouts, including large references."""
from pathlib import Path
import sys,math
CODE=Path(__file__).resolve().parents[1];sys.path[:0]=[str(CODE/'src/v23'),str(CODE/'src/v22'),str(CODE/'tools')]
from compare_layout_versions import metrics
from bpmn_refkit.model import read_bpmn,TAG_TASK
from bpmn_v23.quality import contacts,segment_overlap
from bpmn_v23.narrative_planner import reading_measure

def extra(path):
 state=read_bpmn(path);_,_,_,_,nodes,seq,assocs,docs,member,lanes,boxes,paths=state;uv={i:(u,v) for i,u,v,*_ in seq+assocs};usable={i:paths[i] for i in uv};m=metrics(path);reading=reading_measure(state)
 m.update({k:reading[k] for k in ['score','hairpins','crowding','long_forward_count','forward_max_task_units','forward_p90_task_units','information_mean_task_units','information_max_task_units'] if k in reading})
 items=list(usable.items());shared_length=0;shared_pairs=0
 for i,(eid,p) in enumerate(items):
  for other,q in items[i+1:]:
   length=sum(segment_overlap(a,b,c,d) for a,b in zip(p,p[1:]) for c,d in zip(q,q[1:]))
   if length>.01:shared_length+=length;shared_pairs+=1
 role_order={l:i for i,l in enumerate(sorted(lanes,key=lambda l:(boxes[l][1],l)))};transitions=[abs(role_order[member[u]]-role_order[member[v]]) for _,u,v,*_ in seq if member.get(u) in role_order and member.get(v) in role_order and member[u]!=member[v]]
 m.update(contacts_common=len(contacts(usable,uv)),shared_collinear_pairs=shared_pairs,shared_collinear_length=round(shared_length,2),role_transition_count=len(transitions),role_transition_mean_lane_hops=round(sum(transitions)/max(1,len(transitions)),3),role_transition_max_lane_hops=max(transitions,default=0))
 return m

if __name__=='__main__':
 import argparse,json
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--input',type=Path,required=True)
 args=parser.parse_args()
 print(json.dumps(extra(args.input),ensure_ascii=False,indent=2))
