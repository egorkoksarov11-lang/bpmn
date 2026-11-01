from pathlib import Path
import shutil
import pytest
from lxml import etree as ET
from bpmn_v23.pipeline import run, geometry
from bpmn_v23.labels import place_labels
from bpmn_universal.contract import semantic_equality

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'inputs/process/08 Организация операции через поставщика_v2.bpmn'
CANDIDATE=ROOT/'tests/fixtures/v2_candidate/process_08_v23.bpmn'
SVG=ROOT/'tests/fixtures/v2_candidate/process_08_v23.svg'

class ReplayBackend:
    name='test-replay'
    def __init__(self,mutation=None):self.mutation=mutation
    def layout(self,source,output,svg):
        shutil.copy2(CANDIDATE,output);shutil.copy2(SVG,svg)
        if self.mutation:
            t=ET.parse(str(output));self.mutation(t);t.write(str(output),encoding='utf-8')
        return {}


def test_rejects_semantic_mutation_before_publication(tmp_path):
    def mutate(t):t.xpath('//*[@id="F1"]')[0].set('targetRef','E')
    out=tmp_path/'out';out.mkdir();sentinel=out/'process_08_v23.bpmn';sentinel.write_text('previous')
    with pytest.raises(ValueError,match='Semantic freeze'):run(SOURCE,out,ReplayBackend(mutate))
    assert sentinel.read_text()=='previous'


def test_rejects_dangling_reference(tmp_path):
    def mutate(t):t.xpath('//*[@id="F1"]')[0].set('targetRef','deleted')
    with pytest.raises(ValueError,match='dangling'):run(SOURCE,tmp_path/'out',ReplayBackend(mutate))


def test_routing_and_labels_preserve_frozen_model(tmp_path):
    target=tmp_path/'result.bpmn';svg=tmp_path/'result.svg'
    shutil.copy2(CANDIDATE,target);shutil.copy2(SVG,svg)
    # Legacy fixtures used box ports; migrate only DI to real shape contours.
    from bpmn_refkit.model import read_bpmn,set_di
    from bpmn_v23.contours import attach
    tree,root,_,plane,nodes,seq,assocs,_,_,_,boxes,paths=read_bpmn(target)
    set_di(root,plane,{},attach(paths,{i:(u,v) for i,u,v,_ in seq+assocs},boxes,nodes))
    tree.write(str(target),encoding='utf-8',xml_declaration=True)
    place_labels(target,svg)
    assert semantic_equality(SOURCE,target)
    g=geometry(target)
    assert g['routing_safety_passed']
    assert not g['label_collision_pairs']
    assert not g['a4_ratio_passed'] # Do not claim A4 success for a wide diagram.


def test_never_overwrites_source_directory():
    with pytest.raises(ValueError,match='separate'):run(SOURCE,SOURCE.parent)


def test_frozen_v4_preserves_documents_and_routes():
    source=ROOT/'inputs/benchmark/process_08_v4_frozen.bpmn'
    output=ROOT/'output/process_08_v23.bpmn'
    assert semantic_equality(source,output)
    root=ET.parse(str(output))
    ns={'b':'http://www.omg.org/spec/BPMN/20100524/MODEL'}
    assert len(root.xpath('.//b:association',namespaces=ns))==18
    assert len(root.xpath('.//b:sequenceFlow',namespaces=ns))==95
    assert len(root.xpath('.//b:dataObjectReference | .//b:dataStoreReference',namespaces=ns))==17
    g=geometry(output)
    assert g['routing_safety_passed'] and not g['label_collision_pairs']


def test_v22_fallback_geometry_is_rejected(tmp_path):
    source=ROOT/'inputs/benchmark/process_08_v4_frozen.bpmn'
    class InputGeometryBackend:
        name='test-input-fallback'
        def layout(self,source,output,svg):shutil.copy2(source,output);return {}
    with pytest.raises(ValueError,match='routing_safety_rejected'):
        run(source,tmp_path/'out',InputGeometryBackend())
    assert not (tmp_path/'out/process_08_v23.bpmn').exists()


def test_distinct_channel_backend_separates_parallel_edges(tmp_path):
    source=tmp_path/'source.bpmn'
    source.write_text('''<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="defs" targetNamespace="test">
    <process id="p"><task id="a" name="A"/><task id="b" name="B"/>
    <sequenceFlow id="f1" sourceRef="a" targetRef="b"/><sequenceFlow id="f2" sourceRef="a" targetRef="b"/><sequenceFlow id="f3" sourceRef="a" targetRef="b"/></process>
    <bpmndi:BPMNDiagram id="diagram"><bpmndi:BPMNPlane id="plane" bpmnElement="p">
    <bpmndi:BPMNShape id="sa" bpmnElement="a"><dc:Bounds x="200" y="200" width="170" height="70"/></bpmndi:BPMNShape>
    <bpmndi:BPMNShape id="sb" bpmnElement="b"><dc:Bounds x="600" y="200" width="170" height="70"/></bpmndi:BPMNShape>
    <bpmndi:BPMNEdge id="e1" bpmnElement="f1"><di:waypoint x="370" y="235"/><di:waypoint x="600" y="235"/></bpmndi:BPMNEdge>
    <bpmndi:BPMNEdge id="e2" bpmnElement="f2"><di:waypoint x="370" y="235"/><di:waypoint x="600" y="235"/></bpmndi:BPMNEdge>
    <bpmndi:BPMNEdge id="e3" bpmnElement="f3"><di:waypoint x="370" y="235"/><di:waypoint x="600" y="235"/></bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane></bpmndi:BPMNDiagram></definitions>''')
    out=tmp_path/'out'
    run(source,out)
    result=out/'process_08_v23.bpmn'
    assert semantic_equality(source,result)
    assert not geometry(result)['crossings'].get('overlapping_segments',0)
