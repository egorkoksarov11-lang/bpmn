from collections import Counter
from pathlib import Path
from lxml import etree as ET
import pytest
from bpmn_universal.contract import B,BD,DC,DI,Q,NS
from bpmn_refkit.model import read_bpmn
from bpmn_v23.document_policy import apply_first_appearance,first_appearance_plan,allowed_projection_equal


def fixture(path,assemble=False):
    root=ET.Element(Q(B,'definitions'),nsmap={'b':B,'bd':BD,'dc':DC,'di':DI},targetNamespace='urn:test')
    process=ET.SubElement(root,Q(B,'process'),id='p')
    nodes={'s':'startEvent','a':'task','b':'task','j':'task','e':'endEvent'}
    flows=[('s','a'),('a','b'),('b','j'),('j','e')]
    if assemble:flows=[('s','a'),('s','b'),('a','j'),('b','j'),('j','e'),('j','s')]
    for n,kind in nodes.items():ET.SubElement(process,Q(B,kind),id=n,name=n)
    for i,(u,v) in enumerate(flows):ET.SubElement(process,Q(B,'sequenceFlow'),id='f'+str(i),sourceRef=u,targetRef=v)
    ET.SubElement(process,Q(B,'dataObject'),id='logical',name='Payload')
    for d in ('d1','d2'):ET.SubElement(process,Q(B,'dataObjectReference'),id=d,name='Payload',dataObjectRef='logical')
    links=[('out','a','d1'),('reuse','d2','j')]
    if assemble:links+=[('out2','b','d1')]
    for i,u,v in links:ET.SubElement(process,Q(B,'association'),id=i,sourceRef=u,targetRef=v,associationDirection='One')
    diagram=ET.SubElement(root,Q(BD,'BPMNDiagram'),id='diagram');plane=ET.SubElement(diagram,Q(BD,'BPMNPlane'),id='plane',bpmnElement='p')
    for i,n in enumerate([*nodes,'d1','d2']):
        sh=ET.SubElement(plane,Q(BD,'BPMNShape'),id='di_'+n,bpmnElement=n);ET.SubElement(sh,Q(DC,'Bounds'),x=str(i*160),y='100',width='100',height='60')
    for i in ['f'+str(k) for k in range(len(flows))]+[x[0] for x in links]:
        edge=ET.SubElement(plane,Q(BD,'BPMNEdge'),id='di_'+i,bpmnElement=i)
        for x in ('100','200'):ET.SubElement(edge,Q(DI,'waypoint'),x=x,y='130')
    ET.ElementTree(root).write(str(path),encoding='utf-8',xml_declaration=True)
    return path


def test_first_appearance_removes_repeated_references_and_fanout_only(tmp_path):
    source=fixture(tmp_path/'in.bpmn');before=source.read_bytes();out=tmp_path/'out.bpmn'
    plan=apply_first_appearance(source,out,tmp_path/'journal.json');a,b=read_bpmn(source),read_bpmn(out)
    assert source.read_bytes()==before and a[4]==b[4] and a[5]==b[5] and a[8:10]==b[8:10]
    assert len(b[7])==len(b[6])==1 and b[6][0][0]=='out'
    assert b[1].xpath('.//b:dataObject[@id="logical"]',namespaces=NS)
    assert allowed_projection_equal(source,out,plan)
    assert len(b[1].xpath('.//bd:BPMNShape',namespaces=NS))==len(a[4])+1
    assert not b[1].xpath('.//*[@bpmnElement="d2" or @bpmnElement="reuse"]',namespaces=NS)
    # The whitelist does not permit even a one-word task edit.
    b[1].xpath('.//b:task[@id="a"]',namespaces=NS)[0].set('name','Changed');b[0].write(str(out))
    assert not allowed_projection_equal(source,out,plan)


def test_common_package_appears_after_contributors_even_with_rework_loop(tmp_path):
    source=fixture(tmp_path/'in.bpmn',assemble=True);plan=first_appearance_plan(source)
    assert plan['decisions'][0]['first_operation']=='j'
    assert plan['decisions'][0]['kept_association']=='reuse'


def test_distinct_explicit_document_states_are_not_merged(tmp_path):
    source=fixture(tmp_path/'in.bpmn');tree=ET.parse(str(source))
    for d,state in [('d1','Draft'),('d2','Approved')]:ET.SubElement(tree.xpath('//*[@id=$i]',i=d)[0],Q(B,'dataState'),name=state)
    tree.write(str(source));plan=first_appearance_plan(source)
    assert plan['after']['information_objects']==2 and plan['after']['information_links']==2


def test_explicit_omission_is_separate_from_logical_data_deletion(tmp_path):
    source=fixture(tmp_path/'in.bpmn');out=tmp_path/'out.bpmn'
    plan=apply_first_appearance(source,out,tmp_path/'journal.json',{'d1':'Already stated by operation a'})
    assert read_bpmn(out)[1].xpath('.//b:dataObject[@id="logical"]',namespaces=NS)
    assert 'd1' in plan['removed_reference_ids'] and allowed_projection_equal(source,out,plan)
    with pytest.raises(ValueError):first_appearance_plan(source,{'unknown':'No such document'})


def test_equal_names_do_not_merge_different_logical_documents(tmp_path):
    source=fixture(tmp_path/'in.bpmn');tree=ET.parse(str(source))
    process=tree.xpath('.//b:process',namespaces=NS)[0];ET.SubElement(process,Q(B,'dataObject'),id='different',name='Payload')
    tree.xpath('//*[@id="d2"]')[0].set('dataObjectRef','different');tree.write(str(source))
    plan=first_appearance_plan(source)
    assert plan['after']=={'information_objects':2,'information_links':2}


def test_non_operation_document_relationships_are_protected(tmp_path):
    source=fixture(tmp_path/'in.bpmn');tree=ET.parse(str(source));process=tree.xpath('.//b:process',namespaces=NS)[0]
    ET.SubElement(process,Q(B,'association'),id='related_docs',sourceRef='d1',targetRef='d2',associationDirection='One')
    plane=tree.xpath('.//bd:BPMNPlane',namespaces=NS)[0];edge=ET.SubElement(plane,Q(BD,'BPMNEdge'),id='di_related_docs',bpmnElement='related_docs')
    for x in ('100','200'):ET.SubElement(edge,Q(DI,'waypoint'),x=x,y='130')
    tree.write(str(source));out=tmp_path/'out.bpmn';plan=apply_first_appearance(source,out,tmp_path/'journal.json')
    assert {'d1','d2'}==set(read_bpmn(out)[7])
    assert any(i=='related_docs' for i,_,_,_ in read_bpmn(out)[6])
    assert plan['protected_reference_ids']==['d1','d2']
    with pytest.raises(ValueError):first_appearance_plan(source,{'d1':'Cannot remove its document relationship'})
