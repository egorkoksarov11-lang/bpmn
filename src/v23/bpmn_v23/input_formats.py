"""Strict graph input adapter. No placement or routing policy lives here."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
from lxml import etree as ET
from bpmn_universal.contract import B, BD, DC, DI, Q, preflight

EXTENSIONS = {'.bpmn', '.json', '.yaml', '.yml', '.ylm'}
NODE_TYPES = {'task', 'userTask', 'manualTask', 'serviceTask', 'sendTask',
              'receiveTask', 'businessRuleTask', 'startEvent', 'endEvent',
              'exclusiveGateway', 'parallelGateway', 'inclusiveGateway',
              'intermediateCatchEvent', 'intermediateThrowEvent'}
ID = re.compile(r'^[A-Za-z_][A-Za-z0-9_.-]*$')


def fail(path, message):
    raise ValueError(f'{path}: {message}')


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            fail(str(key), 'ключ должен быть строкой и не повторяться')
        result[key] = value
    return result


def load_model(source):
    source = Path(source)
    if source.stat().st_size > 25_000_000:
        fail('file', 'размер превышает 25 МБ')
    text = source.read_text(encoding='utf-8-sig')
    try:
        if source.suffix.lower() == '.json':
            model = json.loads(text, object_pairs_hook=unique_pairs,
                               parse_constant=lambda x: fail(x, 'не является JSON-числом'))
        else:
            import yaml
            # Explicit graph references use IDs, never YAML aliases or merges.
            if any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for t in yaml.scan(text)):
                fail('YAML', 'якоря и ссылки запрещены; используйте id')
            class Loader(yaml.SafeLoader):
                pass
            def mapping(loader, node):
                return unique_pairs([(loader.construct_object(k), loader.construct_object(v))
                                     for k, v in node.value])
            Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
            model = yaml.load(text, Loader=Loader)
    except (ValueError, UnicodeError) as error:
        raise ValueError(f'Ошибка входного файла: {error}') from error
    except Exception as error:
        # YAML syntax errors include line and column; retain them for the UI.
        kind = 'JSON' if source.suffix.lower() == '.json' else 'YAML'
        raise ValueError(f'Ошибка {kind}: {error}') from error
    return validate(model)


def validate(model):
    if isinstance(model, dict) and model.get('schema_version') == 2:
        from .structured_collaboration import validate_v2
        return validate_v2(model)
    def obj(value, path, required, optional=()):
        if not isinstance(value, dict): fail(path, 'требуется объект')
        missing = set(required) - value.keys()
        extra = value.keys() - set(required) - set(optional)
        if missing: fail(path, 'нет полей: ' + ', '.join(sorted(missing)))
        if extra: fail(path, 'неизвестные поля: ' + ', '.join(sorted(extra)))
    def string(value, path):
        if not isinstance(value, str) or not value.strip(): fail(path, 'требуется непустая строка')
        try:
            ET.Element('test').set('value', value)
        except (ValueError, UnicodeError):
            fail(path, 'недопустимые символы XML')
    all_ids = set()
    def identity(value, path):
        string(value, path)
        if not ID.fullmatch(value) or value.startswith('__import_'):
            fail(path, 'id: латинские буквы, цифры, _ . -; первый символ — буква или _; префикс __import_ зарезервирован')
        if value in all_ids: fail(path, 'id повторяется: ' + value)
        all_ids.add(value)
    obj(model, '$', ('schema_version', 'process', 'roles', 'nodes', 'flows'), ('documents', 'associations', 'messages', 'data_objects', 'data_stores'))
    if type(model['schema_version']) is not int or model['schema_version'] != 1:
        fail('schema_version', 'поддерживается только целое число 1')
    obj(model['process'], 'process', ('id', 'name'))
    identity(model['process']['id'], 'process.id'); string(model['process']['name'], 'process.name')
    for collection in ('roles', 'nodes', 'flows', 'documents', 'associations', 'messages', 'data_objects', 'data_stores'):
        value = model.get(collection, [])
        if not isinstance(value, list): fail(collection, 'требуется массив')
        if collection in ('roles', 'nodes') and not value: fail(collection, 'массив не может быть пустым')
        for i, item in enumerate(value):
            path = f'{collection}[{i}]'
            specs = {'roles': (('id', 'name'), ()),
                     'nodes': (('id', 'type', 'name', 'role'), ('default', 'event_definition')),
                     'flows': (('id', 'source', 'target'), ('name', 'condition')),
                     'documents': (('id', 'type', 'name'), ('object_ref', 'store_ref')),
                     'associations': (('id', 'source', 'target'), ()),
                     'messages': (('id', 'name'), ()), 'data_objects': (('id', 'name'), ()),
                     'data_stores': (('id', 'name'), ())}
            obj(item, path, *specs[collection])
            identity(item['id'], path + '.id')
            for key, v in item.items():
                if key != 'event_definition': string(v, path + '.' + key)
            if 'event_definition' in item:
                event = item['event_definition']
                obj(event, path + '.event_definition', ('id', 'type', 'message_ref'))
                identity(event['id'], path + '.event_definition.id')
                if event['type'] != 'message': fail(path + '.event_definition.type', 'поддерживается message')
                string(event['message_ref'], path + '.event_definition.message_ref')
    roles = {r['id'] for r in model['roles']}
    nodes = {n['id']: n for n in model['nodes']}
    docs = {d['id']: d for d in model.get('documents', [])}
    flows = {f['id']: f for f in model['flows']}
    messages = {m['id'] for m in model.get('messages', [])}
    for i, node in enumerate(nodes.values()):
        if node['type'] not in NODE_TYPES: fail(f'nodes[{i}].type', 'неподдерживаемый тип: ' + node['type'])
        if node['role'] not in roles: fail(f'nodes[{i}].role', 'роль не найдена: ' + node['role'])
        if 'event_definition' in node:
            if node['type'] not in ('startEvent', 'endEvent', 'intermediateCatchEvent', 'intermediateThrowEvent'):
                fail(f'nodes[{i}].event_definition', 'определение сообщения допустимо только у события')
            if node['event_definition']['message_ref'] not in messages:
                fail(f'nodes[{i}].event_definition.message_ref', 'сообщение не найдено')
        if 'default' in node:
            flow = flows.get(node['default'])
            if node['type'] not in ('exclusiveGateway', 'inclusiveGateway') or not flow or flow['source'] != node['id'] or 'condition' in flow:
                fail(f'nodes[{i}].default', 'нужен исходящий переход без condition у exclusiveGateway/inclusiveGateway')
    for i, flow in enumerate(flows.values()):
        if flow['source'] not in nodes or flow['target'] not in nodes:
            fail(f'flows[{i}]', 'source и target должны ссылаться на nodes')
        if nodes[flow['source']]['type'] == 'endEvent' or nodes[flow['target']]['type'] == 'startEvent':
            fail(f'flows[{i}]', 'из endEvent нельзя выходить, в startEvent нельзя входить')
        if 'condition' in flow and nodes[flow['source']]['type'] in ('startEvent', 'parallelGateway'):
            fail(f'flows[{i}].condition', 'этот тип источника не допускает условие')
    for i, doc in enumerate(docs.values()):
        if doc['type'] not in ('document', 'store'): fail(f'documents[{i}].type', 'нужен document или store')
        for key, collection, kind in [('object_ref', 'data_objects', 'document'), ('store_ref', 'data_stores', 'store')]:
            if key in doc and (doc['type'] != kind or doc[key] not in {o['id'] for o in model.get(collection, [])}):
                fail(f'documents[{i}].{key}', 'неверный тип или отсутствует определение документа/хранилища')
    linked = set()
    for i, edge in enumerate(model.get('associations', [])):
        u, v = edge['source'], edge['target']
        if not ((u in nodes and v in docs) or (u in docs and v in nodes)):
            fail(f'associations[{i}]', 'нужна связь документа/базы с шагом в любом направлении')
        linked.update({u, v} & docs.keys())
    if docs.keys() - linked: fail('documents', 'нет associations у: ' + ', '.join(sorted(docs.keys() - linked)))
    return model


def to_bpmn(model, destination):
    """Placeholder DI only satisfies the existing contract; scratch erases it."""
    validate(model)
    if model['schema_version'] == 2:
        from .structured_collaboration import to_bpmn_v2
        return to_bpmn_v2(model, destination)
    root = ET.Element(Q(B, 'definitions'), nsmap={None: B, 'bpmndi': BD, 'dc': DC, 'di': DI,
                                                'xsi': 'http://www.w3.org/2001/XMLSchema-instance'},
                      id='__import_definitions', targetNamespace='urn:bpmn-universal:graph-input:v1')
    proc = ET.SubElement(root, Q(B, 'process'), id=model['process']['id'], name=model['process']['name'], isExecutable='false')
    for message in model.get('messages', []):
        ET.SubElement(root, Q(B, 'message'), **message)
    for obj in model.get('data_objects', []):
        ET.SubElement(proc, Q(B, 'dataObject'), **obj)
    for store in model.get('data_stores', []):
        ET.SubElement(root, Q(B, 'dataStore'), **store)
    lanes = ET.SubElement(proc, Q(B, 'laneSet'), id='__import_lane_set')
    for role in model['roles']:
        lane = ET.SubElement(lanes, Q(B, 'lane'), id=role['id'], name=role['name'])
        for node in model['nodes']:
            if node['role'] == role['id']: ET.SubElement(lane, Q(B, 'flowNodeRef')).text = node['id']
    for node in model['nodes']:
        element = ET.SubElement(proc, Q(B, node['type']), id=node['id'], name=node['name'])
        if 'default' in node: element.set('default', node['default'])
        if 'event_definition' in node:
            event = node['event_definition']
            ET.SubElement(element, Q(B, 'messageEventDefinition'), id=event['id'], messageRef=event['message_ref'])
        for flow in model['flows']:
            if flow['target'] == node['id']: ET.SubElement(element, Q(B, 'incoming')).text = flow['id']
            if flow['source'] == node['id']: ET.SubElement(element, Q(B, 'outgoing')).text = flow['id']
    for i, doc in enumerate(model.get('documents', [])):
        definition = doc.get('object_ref' if doc['type'] == 'document' else 'store_ref')
        if definition is None:
            definition = f'__import_data_{i}'
            ET.SubElement(proc if doc['type'] == 'document' else root, Q(B, 'dataObject' if doc['type'] == 'document' else 'dataStore'), id=definition, name=doc['name'])
        el = ET.SubElement(proc, Q(B, 'dataObjectReference' if doc['type'] == 'document' else 'dataStoreReference'), id=doc['id'], name=doc['name'])
        el.set('dataObjectRef' if doc['type'] == 'document' else 'dataStoreRef', definition)
    for flow in model['flows']:
        el = ET.SubElement(proc, Q(B, 'sequenceFlow'), id=flow['id'], sourceRef=flow['source'], targetRef=flow['target'])
        if 'name' in flow: el.set('name', flow['name'])
        if 'condition' in flow:
            condition = ET.SubElement(el, Q(B, 'conditionExpression'))
            condition.set(Q('http://www.w3.org/2001/XMLSchema-instance', 'type'), 'tFormalExpression')
            condition.text = flow['condition']
    for edge in model.get('associations', []):
        ET.SubElement(proc, Q(B, 'association'), id=edge['id'], sourceRef=edge['source'], targetRef=edge['target'], associationDirection='One')
    diagram = ET.SubElement(root, Q(BD, 'BPMNDiagram'), id='__import_diagram')
    plane = ET.SubElement(diagram, Q(BD, 'BPMNPlane'), id='__import_plane', bpmnElement=proc.get('id'))
    boxes = {}
    def shape(identity, box):
        boxes[identity] = box
        el = ET.SubElement(plane, Q(BD, 'BPMNShape'), id='__import_shape_' + identity, bpmnElement=identity)
        ET.SubElement(el, Q(DC, 'Bounds'), **dict(zip(('x', 'y', 'width', 'height'), map(str, box))))
    for i, role in enumerate(model['roles']): shape(role['id'], (0, i * 400, len(model['nodes']) * 280 + 400, 400))
    for i, node in enumerate(model['nodes']):
        lane = next(j for j, r in enumerate(model['roles']) if r['id'] == node['role'])
        shape(node['id'], (100 + i * 280, lane * 400 + 160, 200, 80))
    for i, doc in enumerate(model.get('documents', [])): shape(doc['id'], (100 + i * 100, 40, 36, 50))
    for edge in model['flows'] + model.get('associations', []):
        el = ET.SubElement(plane, Q(BD, 'BPMNEdge'), id='__import_edge_' + edge['id'], bpmnElement=edge['id'])
        for identity in (edge['source'], edge['target']):
            x, y, w, h = boxes[identity]
            ET.SubElement(el, Q(DI, 'waypoint'), x=str(x + w / 2), y=str(y + h / 2))
    destination = Path(destination)
    ET.ElementTree(root).write(str(destination), encoding='utf-8', xml_declaration=True)
    result = preflight(destination)
    if not result['compatible']: fail('BPMN', '; '.join(result['errors']))
    return {'schema_version': 1, 'placeholder_geometry_used_for_layout': False,
            'model_sha256': hashlib.sha256(json.dumps(model, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            'counts': result['counts']}
