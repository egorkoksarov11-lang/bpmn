"""Version 2 graph contract: distinct process graphs and message exchanges."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from lxml import etree as ET
from bpmn_universal.contract import B, BD, DC, DI, Q


def payload(process, messages):
    return dict(schema_version=1, process={k: process[k] for k in ('id', 'name')},
                messages=messages, **{k: v for k, v in process.items() if k not in ('id', 'name')})


def validate_v2(model):
    from .input_formats import validate, fail, ID
    if type(model.get('schema_version')) is not int: fail('schema_version', 'нужно целое число 2')
    allowed = {'schema_version', 'processes', 'collaboration', 'messages'}
    if model.keys() - allowed or allowed - {'messages'} - model.keys(): fail('$', 'нужны schema_version, processes, collaboration; messages необязателен')
    processes = model['processes']
    if not isinstance(processes, list) or not 1 <= len(processes) <= 2: fail('processes', 'нужен один или два процесса')
    identities = set()
    def identity(value, path):
        if not isinstance(value, str) or not ID.fullmatch(value) or value.startswith('__import_') or value in identities:
            fail(path, 'id неверен или повторяется во всей схеме')
        identities.add(value)
    messages = model.get('messages', [])
    if not isinstance(messages, list): fail('messages', 'требуется массив')
    for message in messages:
        if not isinstance(message, dict) or message.keys() != {'id', 'name'}: fail('messages', 'нужны id, name')
        identity(message['id'], 'messages.id')
    membership = {}
    for i, process in enumerate(processes):
        if not isinstance(process, dict) or not {'id', 'name', 'roles', 'nodes', 'flows'} <= process.keys():
            fail(f'processes[{i}]', 'нужны id, name, roles, nodes, flows')
        try: validate(payload(process, messages))
        except ValueError as error: fail(f'processes[{i}]', str(error))
        identity(process['id'], f'processes[{i}].id')
        for collection in ('roles', 'nodes', 'flows', 'documents', 'associations', 'data_objects', 'data_stores'):
            for obj in process.get(collection, []):
                identity(obj['id'], f'processes[{i}].{collection}.id')
                if collection == 'nodes':
                    membership[obj['id']] = process['id']
                    if 'event_definition' in obj: identity(obj['event_definition']['id'], 'event_definition.id')
    collab = model['collaboration']
    if not isinstance(collab, dict) or not {'id', 'participants', 'message_flows'} <= collab.keys() or collab.keys() - {'id', 'name', 'participants', 'message_flows'}:
        fail('collaboration', 'нужны id, participants, message_flows; name необязателен')
    identity(collab['id'], 'collaboration.id')
    if 'name' in collab and (not isinstance(collab['name'], str) or not collab['name'].strip()): fail('collaboration.name', 'нужна строка')
    if not isinstance(collab['participants'], list) or len(collab['participants']) != len(processes):
        fail('collaboration.participants', 'нужен отдельный участник для каждого процесса')
    process_ids = {p['id'] for p in processes}
    represented = set()
    for part in collab['participants']:
        if not isinstance(part, dict) or part.keys() != {'id', 'name', 'process_ref'}: fail('participants', 'нужны id, name, process_ref')
        identity(part['id'], 'participants.id')
        if not isinstance(part['name'], str) or not part['name'].strip(): fail('participants.name', 'нужна непустая строка')
        if not isinstance(part['process_ref'], str) or part['process_ref'] not in process_ids or part['process_ref'] in represented: fail('participants.process_ref', 'процесс не найден или уже представлен')
        represented.add(part['process_ref']); membership[part['id']] = part['process_ref']
    if not isinstance(collab['message_flows'], list): fail('message_flows', 'нужен массив')
    msg_ids = {m['id'] for m in messages}
    node_types = {n['id']: n['type'] for p in processes for n in p['nodes']}
    for flow in collab['message_flows']:
        if not isinstance(flow, dict) or not {'id', 'source', 'target'} <= flow.keys() or flow.keys() - {'id', 'source', 'target', 'name', 'message_ref'}:
            fail('message_flows', 'нужны id, source, target; name и message_ref необязательны')
        identity(flow['id'], 'message_flows.id')
        for key, value in flow.items():
            if not isinstance(value, str) or not value.strip(): fail('message_flows.' + key, 'нужна строка')
        u, v = flow['source'], flow['target']
        if u not in membership or v not in membership or membership[u] == membership[v]: fail('message_flows', 'концы должны принадлежать разным участникам')
        if any(node_types.get(n, '').endswith('Gateway') for n in (u, v)): fail('message_flows', 'шлюз не является концом сообщения')
        if node_types.get(u) in ('startEvent','intermediateCatchEvent','receiveTask') or node_types.get(v) in ('endEvent','intermediateThrowEvent','sendTask'):
            fail('message_flows', 'неверное направление для события ожидания/отправки')
        if 'message_ref' in flow and flow['message_ref'] not in msg_ids: fail('message_flows.message_ref', 'сообщение не найдено')
    return model


def to_bpmn_v2(model, destination):
    from .input_formats import to_bpmn
    from .collaboration import validate_collaboration
    roots = []
    with tempfile.TemporaryDirectory(prefix='bpmn-process-import-') as directory:
        for i, proc in enumerate(model['processes']):
            path = Path(directory) / f'process{i}.bpmn'
            to_bpmn(payload(proc, model.get('messages', [])), path)
            root = ET.parse(str(path)).getroot()
            # Only generated technical IDs change, never user business IDs.
            for el in root.iter():
                for attr, value in list(el.attrib.items()):
                    if value.startswith('__import_'): el.set(attr, value.replace('__import_', f'__import_p{i}_', 1))
            roots.append(root)
    root = roots[0]
    plane = root.find('.//' + Q(BD, 'BPMNPlane'))
    plane.set('bpmnElement', model['collaboration']['id'])
    for other in roots[1:]:
        for element in other:
            if element.tag in (Q(B, 'process'), Q(B, 'dataStore')): root.append(copy.deepcopy(element))
        other_plane = other.find('.//' + Q(BD, 'BPMNPlane'))
        for element in other_plane: plane.append(copy.deepcopy(element))
    c = model['collaboration']
    collab = ET.SubElement(root, Q(B, 'collaboration'), id=c['id'])
    if 'name' in c: collab.set('name', c['name'])
    for i, part in enumerate(c['participants']):
        ET.SubElement(collab, Q(B, 'participant'), id=part['id'], name=part['name'], processRef=part['process_ref'])
        shape = ET.SubElement(plane, Q(BD, 'BPMNShape'), id=f'__import_pool_{i}', bpmnElement=part['id'], isHorizontal='true')
        ET.SubElement(shape, Q(DC, 'Bounds'), x='0', y=str(i * 600), width='1400', height='500')
    for i, flow in enumerate(c['message_flows']):
        attrs = {'id': flow['id'], 'sourceRef': flow['source'], 'targetRef': flow['target']}
        if 'name' in flow: attrs['name'] = flow['name']
        if 'message_ref' in flow: attrs['messageRef'] = flow['message_ref']
        ET.SubElement(collab, Q(B, 'messageFlow'), **attrs)
        edge = ET.SubElement(plane, Q(BD, 'BPMNEdge'), id=f'__import_message_edge_{i}', bpmnElement=flow['id'])
        ET.SubElement(edge, Q(DI, 'waypoint'), x='100', y='100')
        ET.SubElement(edge, Q(DI, 'waypoint'), x='100', y='600')
    ET.ElementTree(root).write(str(destination), encoding='utf-8', xml_declaration=True)
    report = validate_collaboration(destination)
    return {'schema_version': 2, 'placeholder_geometry_used_for_layout': False,
            'model_sha256': hashlib.sha256(json.dumps(model, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            'counts': report['preflight']['counts']}
