"""Read saved BPMN artifacts; independently compare equal-input cold runs."""
import argparse,csv,hashlib,json,math,sys
from pathlib import Path
from statistics import median
from lxml import etree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_universal.contract import parse,NS,B,BD,DC,DI,Q,semantic_equality
from bpmn_refkit.model import TAG_TASK,TAG_GATE,TAG_EVENT
from bpmn_v23.freeze import equal


def metrics(path):
    root=parse(path);nodes={e.get('id'):e for e in root.iter() if ET.QName(e).localname in TAG_TASK|TAG_GATE|TAG_EVENT}
    docs={e.get('id') for e in root.iter() if ET.QName(e).localname in ('dataObjectReference','dataStoreReference')}
    edges={e.get('id'):e for e in root.iter() if ET.QName(e).localname in ('sequenceFlow','association','dataInputAssociation','dataOutputAssociation','messageFlow')}
    flows={i for i,e in edges.items() if e.tag==Q(B,'sequenceFlow')};information={i for i,e in edges.items() if e.tag in (Q(B,'association'),Q(B,'dataInputAssociation'),Q(B,'dataOutputAssociation'))}
    boxes={s.get('bpmnElement'):tuple(float(s.find(Q(DC,'Bounds')).get(k)) for k in ('x','y','width','height')) for s in root.xpath('.//bd:BPMNShape',namespaces=NS)}
    paths={s.get('bpmnElement'):[(float(p.get('x')),float(p.get('y'))) for p in s.findall(Q(DI,'waypoint'))] for s in root.xpath('.//bd:BPMNEdge',namespaces=NS)}
    rectangles=[b for n,b in boxes.items() if n in nodes or n in docs]
    for b in root.xpath('.//bd:BPMNLabel/dc:Bounds',namespaces=NS):
        owner=b.getparent().getparent().get('bpmnElement')
        if owner in nodes and ET.QName(nodes[owner]).localname in TAG_TASK:continue
        if owner in nodes or owner in docs or owner in edges:rectangles.append(tuple(float(b.get(k)) for k in ('x','y','width','height')))
    points=[p for i,ps in paths.items() if i in edges for p in ps]
    x0=min([b[0] for b in rectangles]+[p[0] for p in points]);x1=max([b[0]+b[2] for b in rectangles]+[p[0] for p in points])
    y0=min([b[1] for b in rectangles]+[p[1] for p in points]);y1=max([b[1]+b[3] for b in rectangles]+[p[1] for p in points])
    def bends(ps):
        vv=[(b[0]-a[0],b[1]-a[1]) for a,b in zip(ps,ps[1:]) if math.dist(a,b)>.01]
        return sum(abs(a[0]*b[1]-a[1]*b[0])>1e-6*math.hypot(*a)*math.hypot(*b) or a[0]*b[0]+a[1]*b[1]<0 for a,b in zip(vv,vv[1:]))
    def length(ids):return round(sum(math.dist(a,b) for i in ids for a,b in zip(paths[i],paths[i][1:])),2)
    outgoing={n:[] for n in nodes};incoming={n:[] for n in nodes}
    for i in flows:
        e=edges[i];outgoing[e.get('sourceRef')].append(i);incoming[e.get('targetRef')].append(i)
    serial=[i for i in flows if len(outgoing[edges[i].get('sourceRef')])==len(incoming[edges[i].get('targetRef')])==1
            and ET.QName(nodes[edges[i].get('sourceRef')]).localname in TAG_TASK
            and ET.QName(nodes[edges[i].get('targetRef')]).localname in TAG_TASK]
    lengths=sorted(length([i]) for i in flows)
    serial_straight=sum(bends(paths[i])==0 for i in serial)
    return {'nodes':len(nodes),'documents':len(docs),'flows':len(flows),'information_links':len(information),'width':round(x1-x0,2),'height':round(y1-y0,2),
            'area':round((x1-x0)*(y1-y0),2),'flow_length':length(flows),'information_length':length(information),'bends':sum(bends(paths[i]) for i in flows),
            'straight_flows':sum(bends(paths[i])==0 for i in flows),'serial_links':len(serial),'serial_straight':serial_straight,
            'serial_straight_percent':round(100*serial_straight/max(1,len(serial)),2),
            'flow_length_p95':lengths[max(0,math.ceil(len(lengths)*.95)-1)],'flow_length_max':max(lengths),
            'task_width_median':median([b[2] for n,b in boxes.items() if n in nodes and ET.QName(nodes[n]).localname in TAG_TASK])}


def inspect(case,folder):
    path=folder/'process_08_v23.bpmn'
    if not path.exists():return {'status':'failed','log':str(folder/'console.log')}
    m=metrics(path);run=json.loads((folder/'run_report.json').read_text());geo=json.loads((folder/'geometry_report.json').read_text())['after'];semantic=json.loads((folder/'semantic_diff.json').read_text())
    assert semantic_equality(case['input'],path) and equal(case['input'],path)
    assert semantic['equal'] and geo['routing_safety_passed'] and geo['edge_clearance_passed']
    assert not geo['label_collision_pairs'] and not geo['label_line_cuts']
    gs=geo.get('processes',[geo]);reports=run['backend_report'].get('processes',[run])
    stable=[r['backend_report'].get('stable_blocks',{}) for r in reports]
    final=[r['backend_report'].get('stable_finalization',{}) for r in reports]
    narrative=[r['backend_report'].get('narrative_refinement',{}) for r in reports]
    portfolios=[r['backend_report'].get('portfolio_refinement',{}) for r in reports]
    work=[r['backend_report'].get('work_budget',{}) for r in reports]
    from bpmn_refkit.model import read_bpmn
    state=read_bpmn(path)
    if len(state[4])==m['nodes']:
        from bpmn_v23.narrative_planner import reading_measure
        reading=reading_measure(state)
        m.update(reading_score=reading['score'],serial_hairpins=reading['hairpins'],parallel_pressure=reading['crowding'],broken_serial=reading['broken_serial'])
        for key in ('forward_max_task_units','forward_p90_task_units','long_forward_count','forward_jump_loss','horizontal_span_loss','information_mean_task_units','information_max_task_units'):
            if key in reading:m[key]=reading[key]
    m.update(status='verified',version=run['version'],semantic_equal=True,di_structure_equal=True,contacts=geo['ambiguous_contacts'],
             crossings={key:sum(g.get('crossings',{}).get(key,0) for g in gs) for key in ('flow_flow','flow_assoc','assoc_assoc')},
             minimum_font=min(g['minimum_measured_font_size'] for g in gs),overflows=sum(len(g['task_text_overflows']) for g in gs),
             stable_blocks=sum(r.get('accepted_blocks',0) for r in stable),outside_nodes_moved=sum(b['outside_nodes_moved'] for r in stable for b in r.get('blocks',[])),
             narrative_edits=sum(r.get('accepted',0) for r in narrative),
             narrative_edit_kinds=[e['kind'] for r in narrative for e in r.get('edits',[])],
             narrative_diagnostics=[{k:r[k] for k in ('before','after','rejections','seconds') if k in r} for r in narrative if r],
             portfolio_finalists=sum(len(r.get('finalists',[])) for r in portfolios),
             portfolio_diagnostics=[r for r in portfolios if r],routing_work=[r for r in work if r],
             finalization_idempotent=all(r.get('idempotent',False) for r in final) if all(final) else None)
    return m


def compare(manifest,baseline,new,output,protocol_note=None):
    cases=json.loads(Path(manifest).read_text());rows=[]
    for case in cases:
        assert hashlib.sha256(Path(case['input']).read_bytes()).hexdigest()==case['sha256']
        a=inspect(case,Path(baseline)/case['case']);b=inspect(case,Path(new)/case['case'])
        row={'case':case['case'],'input_sha256':case['sha256'],'baseline':a,'new':b}
        if case.get('reference'):
            row['human_reference_descriptive_only']=metrics(Path(case['reference']))
        if a['status']==b['status']=='verified':
            row['change_percent']={k:round(100*(b[k]/a[k]-1),2) if a[k] else None for k in ('area','width','height','flow_length','information_length','bends','contacts')}
        rows.append(row)
    report={'method':'same normalized input; cold layout; common independent XML geometry measurements',
            'note':protocol_note or 'Consult run reports for search/finishing budgets and execution conditions; wall times are diagnostic, not a speedup claim.','cases':rows}
    paired=[r for r in rows if r['baseline']['status']==r['new']['status']=='verified']
    report['aggregate']={}
    for key in ('area','flow_length','information_length','bends','contacts'):
        a=sum(r['baseline'][key] for r in paired);b=sum(r['new'][key] for r in paired)
        report['aggregate'][key]={'baseline':a,'new':b,'change_percent':round(100*(b/a-1),2) if a else None}
    output=Path(output);output.mkdir(parents=True,exist_ok=True);(output/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with (output/'comparison.csv').open('w',newline='',encoding='utf-8-sig') as file:
        writer=csv.writer(file);writer.writerow(['case','version','status','area','flow_length','bends','contacts','minimum_font','stable_blocks','finalization_idempotent'])
        for r in rows:
            for version in ('baseline','new'):
                m=r[version];writer.writerow([r['case'],version,*[m.get(k) for k in ('status','area','flow_length','bends','contacts','minimum_font','stable_blocks','finalization_idempotent')]])
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True);parser.add_argument('--baseline',required=True);parser.add_argument('--new',required=True);parser.add_argument('--output',required=True);parser.add_argument('--protocol-note');a=parser.parse_args()
    report=compare(a.manifest,a.baseline,a.new,a.output,a.protocol_note)
    print(json.dumps(report,ensure_ascii=False,indent=2))
