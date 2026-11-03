"""Extract anonymized two-wire edits from saved human BPMN states.

This is retrospective evidence, never a source of construction coordinates. Saved
states do not reveal the user's cursor movement or ordering of unsaved commands.
"""
from pathlib import Path
import argparse,json,math,sys
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_refkit.model import read_bpmn
from bpmn_universal.contract import semantic_equality
from bpmn_v23.window_metrics import windows,metrics
from bpmn_v23.local_editing import physical_bends


def relative_edit(before,after,window,tolerance=2):
    """Whole-diagram translations are not changes to local arrangement."""
    a,b,c=window['nodes']
    def centre(box):return (box[0]+box[2]/2,box[1]+box[3]/2)
    aa,ab=centre(before[a]),centre(after[a]);changed=[]
    for n in (b,c):
        old,new=centre(before[n]),centre(after[n]);delta=((new[0]-ab[0])-(old[0]-aa[0]),(new[1]-ab[1])-(old[1]-aa[1]))
        if math.hypot(*delta)>tolerance:changed.append(n)
    return changed


def pair_signature(paths,edges,anchor):
    return tuple(tuple((round(x-anchor[0],2),round(y-anchor[1],2)) for x,y in paths[i]) for i in edges)


def analyze(root):
    rows=[]
    for index,folder in enumerate(sorted(p for p in Path(root).iterdir() if (p/'snapshots').is_dir()),1):
        files=sorted((folder/'snapshots').glob('*.bpmn'));states=[read_bpmn(p) for p in files];counts=Counter();semantic_transitions=0
        for pa,pb,old,new in zip(files,files[1:],states,states[1:]):
            semantic_transitions+=not semantic_equality(pa,pb)
            newer={w['nodes']:w for w in windows(new[4],new[5])}
            for w in windows(old[4],old[5]):
                if w['nodes'] not in newer or w['edges']!=newer[w['nodes']]['edges']:continue
                # Same control wiring, kinds and role membership in both states.
                if any(old[4][n]['kind']!=new[4][n]['kind'] or old[8].get(n)!=new[8].get(n) for n in w['nodes']):continue
                counts['stable_window_observations']+=1
                moved=relative_edit(old[-2],new[-2],w);a=w['nodes'][0]
                oldpair=pair_signature(old[-1],w['edges'],old[-2][a][:2]);newpair=pair_signature(new[-1],w['edges'],new[-2][a][:2])
                changed=[u!=v for u,v in zip(oldpair,newpair)]
                if not moved and not any(changed):continue
                counts['edited_windows']+=1;counts['joint_relative_node_edits']+=len(moved)==2;counts['single_relative_node_edits']+=len(moved)==1
                counts['both_wires_edited']+=all(changed);counts['wire_only_edits']+=not moved and any(changed)
                bends_old=sum(physical_bends(old[-1][i]) for i in w['edges']);bends_new=sum(physical_bends(new[-1][i]) for i in w['edges'])
                counts['fewer_bends']+=bends_new<bends_old;counts['more_bends']+=bends_new>bends_old
                counts['became_simple_pair']+=any(physical_bends(old[-1][i])>1 for i in w['edges']) and all(physical_bends(new[-1][i])<=1 for i in w['edges'])
        last=states[-1];rows.append({'session':'S'+str(index),'saved_states':len(files),'saved_transitions':len(files)-1,'transitions_with_business_xml_changes':semantic_transitions,'window_observations':dict(counts),'final_diagnostics':metrics(last[-2],last[-1],last[4],last[5],last[8],last[7],last[6])})
    return {'protocol':{'source':'consecutive saved BPMN states','no_cursor_recording':True,'reference_coordinates_used_by_generator':False,'counts_are_overlapping_windows_not_independent_user_actions':True,'whole_diagram_translations_removed':True,'development_corpus_not_held_out':True},'sessions':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--observations',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=analyze(a.observations);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False))
