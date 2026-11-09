"""Registry-derived constructs, synthetic examples; no private source archives."""
import copy
import json
from pathlib import Path
import pytest
from lxml import etree as ET
from bpmn_universal.contract import B,BD,DC,DI,Q,NS,parse,semantic_equality
from bpmn_v23.input_formats import load_model,to_bpmn,validate
from bpmn_v23.collaboration import validate_collaboration,boxes_paths,write,collaboration_geometry
from bpmn_v23.pipeline import run,validate_xml
from bpmn_v23.scratch_layout import ScratchBackend
from bpmn_v23.freeze import equal as di_equal

ROOT=Path(__file__).resolve().parents[1]


def example():return load_model(ROOT/'desktop/example-collaboration.json')


def test_json_yaml_equivalent_and_alias_identity(tmp_path):
    model=example();assert model==load_model(ROOT/'desktop/example-collaboration.yaml')
    source=tmp_path/'source.bpmn';report=to_bpmn(model,source);root=parse(source)
    assert report['counts']['processes']==2 and report['counts']['message_flows']==2
    assert root.xpath('.//b:dataObjectReference/@dataObjectRef',namespaces=NS)==['DO_Package','DO_Package']
    assert root.xpath('.//b:dataObject/@id',namespaces=NS)==['DO_Package']
    assert root.xpath('.//b:messageEventDefinition/@id',namespaces=NS)==['wait_message','start_message']
    assert root.xpath('.//b:messageFlow/@messageRef',namespaces=NS)==['msg_package','msg_confirmation']
    assert root.xpath('.//b:participant/@processRef',namespaces=NS)==['OrganizationProcess','CustomerProcess']


@pytest.mark.parametrize('edit,reason',[
    (lambda m:m['processes'][1].update(id='OrganizationProcess'),'повторяется'),
    (lambda m:m['processes'][0]['flows'][0].update(target='review'),'source и target'),
    (lambda m:m['collaboration']['participants'][1].update(process_ref='OrganizationProcess'),'представлен'),
    (lambda m:m['collaboration']['message_flows'][0].update(target='wait'),'разным участникам'),
    (lambda m:m['collaboration']['message_flows'][0].update(target='DOR_Outgoing'),'разным участникам'),
    (lambda m:m['collaboration']['message_flows'][0].update(message_ref='missing'),'сообщение не найдено'),
    (lambda m:m['processes'][0]['nodes'][2]['event_definition'].update(message_ref='missing'),'сообщение не найдено'),
    (lambda m:m['processes'][0]['documents'][1].update(object_ref='missing'),'отсутствует определение'),
    (lambda m:m['collaboration']['message_flows'][0].update(source='wait'),'направление'),
    (lambda m:m['collaboration']['participants'][0].update(lane='org_role'),'process_ref'),
])
def test_reject_semantic_shortcuts(edit,reason):
    model=example();edit(model)
    with pytest.raises(ValueError,match=reason):validate(model)


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    directory=tmp_path_factory.mktemp('collaboration-e2e');source=directory/'source.bpmn';model=example()
    to_bpmn(model,source)
    result=run(source,directory/'result',ScratchBackend(candidate_seconds=5,search_seconds=15))
    return source,directory/'result',result


def test_full_layout_keeps_every_business_and_di_id(built):
    source,folder,result=built;target=folder/'process_08_v23.bpmn'
    assert semantic_equality(source,target) and di_equal(source,target)
    assert result['processes']==2 and result['routing_safety']
    root=parse(target)
    assert root.xpath('.//b:intermediateCatchEvent/@id',namespaces=NS)==['wait']
    assert root.xpath('.//b:messageFlow/@id',namespaces=NS)==['M1','M2']
    assert len(root.xpath('.//b:sequenceFlow',namespaces=NS))==6
    assert validate_xml(target)['reference_integrity']
    svg=ET.parse(str(folder/'process_08_v23.svg'));ids=set(svg.xpath('//@data-bpmn-id'))
    assert {'OrgPool','CustomerPool','M1','M2','wait','DOR_Outgoing','DOR_Accepted'}<=ids
    g=json.loads((folder/'geometry_report.json').read_text())['after']
    assert g['routing_safety_passed'] and g['edge_clearance_passed']
    assert not(g['label_collision_pairs'] or g['label_line_cuts'] or g['outside_pools'])


def test_audit_rejects_corrupt_message_endpoint(built,tmp_path):
    _,folder,_=built;root=parse(folder/'process_08_v23.bpmn')
    pt=root.xpath('.//bd:BPMNEdge[@bpmnElement="M1"]/di:waypoint',namespaces=NS)[0]
    pt.set('x',str(float(pt.get('x'))+30));target=tmp_path/'bad.bpmn';write(root,target)
    assert not collaboration_geometry(target)['routing_safety_passed']


@pytest.mark.parametrize('kind',['exclusiveGateway','intermediateCatchEvent'])
@pytest.mark.parametrize('inside',[False,True])
def test_collaboration_uses_true_contours_for_label_collisions(built,tmp_path,kind,inside):
    _,folder,_=built;root=parse(folder/'process_08_v23.bpmn')
    node=root.xpath('.//b:userTask[@id="review"]',namespaces=NS)[0]
    node.tag=Q(B,kind)  # An internal node, never a message endpoint.
    boxes,_=boxes_paths(root);x,y,w,h=boxes['review']
    label=root.xpath('.//bd:BPMNEdge[@bpmnElement="M2"]/bd:BPMNLabel/dc:Bounds',namespaces=NS)[0]
    rect=(x+w/2-2,y+h/2-2,4,4) if inside else (x,y,4,4)
    for key,value in zip(('x','y','width','height'),rect):label.set(key,str(value))
    target=tmp_path/'label.bpmn';write(root,target)
    validate_xml(target)
    report=collaboration_geometry(target)
    assert (['M2','review'] in report['label_collision_pairs']) is inside
    if inside:
        from bpmn_v23.collaboration import rejection_reasons
        assert any('M2' in reason and 'review' in reason for reason in rejection_reasons(report))


def test_raw_bpmn_without_customer_lanes_and_bare_catch(tmp_path):
    source=tmp_path/'source.bpmn';to_bpmn(example(),source);root=parse(source)
    customer=root.xpath('./b:process[@id="CustomerProcess"]',namespaces=NS)[0]
    for lane in customer.findall(Q(B,'laneSet')):customer.remove(lane)
    shape=root.xpath('.//bd:BPMNShape[@bpmnElement="customer_role"]',namespaces=NS)[0];shape.getparent().remove(shape)
    event=root.xpath('.//b:intermediateCatchEvent[@id="wait"]',namespaces=NS)[0]
    for definition in event.findall(Q(B,'messageEventDefinition')):event.remove(definition)
    write(root,source);before=source.read_bytes()
    assert validate_collaboration(source)['preflight']['warnings']
    run(source,tmp_path/'result',ScratchBackend(candidate_seconds=5,search_seconds=15))
    target=tmp_path/'result/process_08_v23.bpmn'
    assert source.read_bytes()==before and semantic_equality(source,target) and di_equal(source,target)
    final=parse(target)
    assert not final.xpath('.//b:lane[starts-with(@id,"__layout_internal")]',namespaces=NS)
    assert not final.xpath('.//b:intermediateCatchEvent/b:messageEventDefinition',namespaces=NS)


def test_message_to_pool_endpoint(tmp_path):
    model=example();model['collaboration']['message_flows'][0]['target']='CustomerPool'
    source=tmp_path/'source.bpmn';to_bpmn(model,source)
    run(source,tmp_path/'result',ScratchBackend(candidate_seconds=5,search_seconds=15))
    assert semantic_equality(source,tmp_path/'result/process_08_v23.bpmn')


def test_three_and_four_message_channels(tmp_path):
    model=example()
    model['processes'][0]['nodes'][1]['type']='userTask'
    model['collaboration']['message_flows'].extend([
        {'id':'M3','source':'send','target':'review','name':'Уточнение'},
        {'id':'M4','source':'review','target':'send','name':'Вопрос заказчика'}])
    source=tmp_path/'source.bpmn';to_bpmn(model,source)
    run(source,tmp_path/'result',ScratchBackend(candidate_seconds=5,search_seconds=15))
    g=collaboration_geometry(tmp_path/'result/process_08_v23.bpmn')
    assert g['message_flows']==4 and g['routing_safety_passed'] and not g['collinear_overlap_pairs']


def test_seven_message_channels(tmp_path):
    model=example();model['processes'][0]['nodes'][1]['type']='userTask'
    model['collaboration']['message_flows'].extend(
        {'id':f'M{i}','source':'send' if i%2 else 'review','target':'review' if i%2 else 'send','name':f'Сообщение {i}'}
        for i in range(3,8))
    source=tmp_path/'source.bpmn';to_bpmn(model,source)
    run(source,tmp_path/'result',ScratchBackend(candidate_seconds=5,search_seconds=15))
    g=collaboration_geometry(tmp_path/'result/process_08_v23.bpmn')
    assert g['message_flows']==7 and g['routing_safety_passed'] and g['edge_clearance_passed']


def test_single_process_message_catch_and_document_aliases(tmp_path):
    model=example();proc=model['processes'][0]
    single=dict(schema_version=1,process={k:proc[k] for k in ('id','name')},messages=model['messages'],**{k:v for k,v in proc.items() if k not in ('id','name')})
    source=tmp_path/'source.bpmn';to_bpmn(single,source)
    run(source,tmp_path/'result',ScratchBackend(candidate_seconds=5,search_seconds=15))
    target=tmp_path/'result/process_08_v23.bpmn'
    assert semantic_equality(source,target)
    assert parse(target).xpath('.//b:dataObjectReference/@dataObjectRef',namespaces=NS)==['DO_Package','DO_Package']
