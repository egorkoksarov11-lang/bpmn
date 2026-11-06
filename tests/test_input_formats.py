import copy
import json
from pathlib import Path
import sys
import pytest
import yaml
from lxml import etree as ET
from bpmn_universal.contract import NS, normalized_model, preflight
from bpmn_v23.input_formats import load_model, to_bpmn, validate

ROOT = Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT / 'desktop/example.json').read_text(encoding='utf-8'))


def test_json_yaml_identical_semantics(tmp_path):
    a = load_model(ROOT / 'desktop/example.json')
    b = load_model(ROOT / 'desktop/example.yaml')
    assert a == b
    left, right = tmp_path / 'a.bpmn', tmp_path / 'b.bpmn'
    assert to_bpmn(a, left)['counts'] == to_bpmn(b, right)['counts']
    assert normalized_model(left) == normalized_model(right)
    assert preflight(left)['compatible']


def test_all_graph_fields_survive_xml(tmp_path):
    model = example()
    model['nodes'].extend([
        {'id': 'choice', 'type': 'exclusiveGateway', 'name': 'Согласовано?', 'role': 'manager', 'default': 'retry'},
        {'id': 'revise', 'type': 'manualTask', 'name': 'Исправить', 'role': 'manager'}])
    model['flows'][1]['target'] = 'choice'
    model['flows'].extend([
        {'id': 'yes', 'source': 'choice', 'target': 'pay', 'name': 'Да', 'condition': 'amount < 100 && approved'},
        {'id': 'retry', 'source': 'choice', 'target': 'revise', 'name': 'Нет'},
        {'id': 'again', 'source': 'revise', 'target': 'prepare'}])
    model['documents'].append({'id': 'archive', 'type': 'store', 'name': 'Архив'})
    model['associations'].append({'id': 'record', 'source': 'pay', 'target': 'archive'})
    target = tmp_path / 'graph.bpmn'
    to_bpmn(model, target)
    tree = ET.parse(str(target))
    for node in model['nodes']:
        el = tree.xpath('//*[@id=$id]', id=node['id'])[0]
        assert ET.QName(el).localname == node['type']
        assert el.get('name') == node['name']
        assert tree.xpath('//b:lane[@id=$id]/b:flowNodeRef/text()', namespaces=NS, id=node['role']).count(node['id']) == 1
    for collection, tag in [('flows', 'sequenceFlow'), ('associations', 'association')]:
        for edge in model[collection]:
            el = tree.xpath('//b:' + tag + '[@id=$id]', namespaces=NS, id=edge['id'])[0]
            assert el.get('sourceRef') == edge['source'] and el.get('targetRef') == edge['target']
    assert tree.xpath('//b:conditionExpression/text()', namespaces=NS) == ['amount < 100 && approved']
    assert tree.xpath('//b:exclusiveGateway/@default', namespaces=NS) == ['retry']
    assert tree.xpath('//b:dataStoreReference/@id', namespaces=NS) == ['archive']


@pytest.mark.parametrize('change,path', [
    (lambda m: m.update(schema_version=True), 'schema_version'),
    (lambda m: m.update(coordinates=[]), 'неизвестные поля'),
    (lambda m: m['nodes'][0].update(id='manager'), 'повторяется'),
    (lambda m: m['nodes'][0].update(id='__import_reserved'), 'зарезервирован'),
    (lambda m: m['nodes'][0].update(role='missing'), 'роль не найдена'),
    (lambda m: m['nodes'][0].update(type='boundaryEvent'), 'неподдерживаемый'),
    (lambda m: m['flows'][0].update(source='invoice'), 'source и target'),
    (lambda m: m['flows'][0].update(target='start'), 'нельзя входить'),
    (lambda m: m['flows'][0].update(condition='x'), 'не допускает'),
    (lambda m: m['nodes'][0].update(default='request_to_prepare'), 'исходящий переход'),
    (lambda m: m.update(associations=[]), 'нет associations'),
    (lambda m: m['associations'][0].update(target='pay'), 'связь документа'),
    (lambda m: m['documents'][0].update(type='file'), 'document или store'),
    (lambda m: m['nodes'][1].update(name='\x01'), 'символы XML'),
])
def test_invalid_graph_rejected_with_path(change, path):
    model = example()
    change(model)
    with pytest.raises(ValueError, match=path): validate(model)


@pytest.mark.parametrize('suffix,text', [
    ('.json', '{"schema_version":1,"schema_version":2}'),
    ('.yaml', 'schema_version: 1\nschema_version: 2'),
    ('.yaml', 'nodes: &a [*a]'),
    ('.yaml', '!!python/object/apply:os.system ["echo unsafe"]'),
    ('.json', '{"schema_version": NaN}'),
])
def test_unsafe_or_ambiguous_syntax_rejected(tmp_path, suffix, text):
    source = tmp_path / ('bad' + suffix)
    source.write_text(text)
    with pytest.raises(ValueError): load_model(source)


@pytest.mark.parametrize('suffix', ['.yaml', '.yml', '.ylm', '.json'])
def test_bom_and_format_aliases(tmp_path, suffix):
    source = tmp_path / ('source' + suffix)
    model = example()
    text = json.dumps(model) if suffix == '.json' else yaml.safe_dump(model, allow_unicode=True)
    source.write_text(text, encoding='utf-8-sig')
    assert load_model(source) == model


def test_cli_keeps_bpmn_path_untouched(monkeypatch):
    from bpmn_v23 import pipeline, input_cli
    args = ['run_v23.py', '--input', 'a.bpmn', '--output-dir', 'out', '--layout-engine', 'scratch']
    monkeypatch.setattr(sys, 'argv', args[:])
    seen = []
    monkeypatch.setattr(pipeline, 'main', lambda: seen.append(sys.argv[:]))
    input_cli.main()
    assert seen == [args]


@pytest.mark.parametrize('equals', [True, False])
def test_cli_only_adapts_input_and_restores_args(tmp_path, monkeypatch, equals):
    from bpmn_v23 import pipeline, input_cli
    source = tmp_path / 'original.json'
    source.write_text(json.dumps(example()))
    output = tmp_path / 'result'
    args = ['run_v23.py', *(['--input=' + str(source)] if equals else ['--input', str(source)]),
            '--output-dir', str(output), '--layout-engine', 'scratch', '--candidate-timeout', '60']
    monkeypatch.setattr(sys, 'argv', args[:])
    seen = []
    def run():
        seen.extend(sys.argv)
        output.mkdir()
    monkeypatch.setattr(pipeline, 'main', run)
    input_cli.main()
    assert sys.argv == args
    assert seen[-4:] == args[-4:]
    assert (output / 'input_model.bpmn').is_file()
    assert json.loads((output / 'input_report.json').read_text())['counts']['sequence_flows'] == 3
    assert json.loads(source.read_text()) == example()
