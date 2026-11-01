"""Unit and integration regression tests; no network required."""
import json
from pathlib import Path
import pytest
from bpmn_universal.settings import Settings
from bpmn_universal.contract import preflight,semantic_equality
from bpmn_universal.cli import optimize

HERE=Path(__file__).resolve().parents[1]
EXAMPLES=HERE/'examples'/'references'
SOURCE=HERE/'examples'/'process01_source.bpmn'


def test_default_config():
    cfg=Settings.load(HERE/'examples'/'default_config.json')
    assert cfg.semantics.mode=='strict'
    assert cfg.geometry.task_gap>0


def test_reject_unknown_config(tmp_path):
    f=tmp_path/'wrong.json';f.write_text('{"geometry":{"not_existing":12}}')
    with pytest.raises(ValueError):Settings.load(f)


def test_process01_strict_semantics(tmp_path):
    output=tmp_path/'out.bpmn'
    info=optimize(SOURCE,output,Settings.load(HERE/'examples'/'default_config.json'))
    assert output.exists() and semantic_equality(SOURCE,output)
    assert info['unchanged_sequence_flows']==51
    assert info['removed_redundant_associations']==[]


def test_reference02_data_associations(tmp_path):
    src=EXAMPLES/'изм 02 Оформление приема сотрудника.bpmn'
    out=tmp_path/'02.bpmn'
    scan=preflight(src)
    assert scan['compatible'] and scan['counts']['associations']>9
    optimize(src,out,Settings.load(HERE/'examples'/'default_config.json'))
    assert semantic_equality(src,out)


def test_unsupported_cross_pool():
    src=EXAMPLES/'изм 11 Сокращение численности и штата.bpmn'
    scan=preflight(src)
    assert not scan['compatible']
    assert 'messageFlow' in str(scan['errors'])


def test_approval_whitelist(tmp_path):
    src=HERE/'examples'/'process01_with_duplicates.bpmn'
    cfg=Settings()
    cfg.semantics.mode='approved-associations'
    cfg.semantics.approved_association_removals=['a10','a26']
    cfg.execution.timeout_seconds=30
    out=tmp_path/'approved.bpmn'
    info=optimize(src,out,cfg)
    assert info['removed_redundant_associations']==['a10','a26']
    assert semantic_equality(src,out,approved_removed=['a10','a26'])


def test_wrong_approval_rejected(tmp_path):
    src=HERE/'examples'/'process01_with_duplicates.bpmn'
    cfg=Settings()
    cfg.semantics.mode='approved-associations'
    cfg.semantics.approved_association_removals=['a09']
    with pytest.raises(ValueError):
        optimize(src,tmp_path/'wrong.bpmn',cfg)
    assert not (tmp_path/'wrong.bpmn').exists()


def test_source_and_output_must_differ():
    with pytest.raises(ValueError):optimize(SOURCE,SOURCE,Settings())
