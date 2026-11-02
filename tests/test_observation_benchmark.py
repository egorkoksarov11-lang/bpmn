from pathlib import Path
import importlib.util,json,hashlib,zipfile
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('prepare_observation',ROOT/'tools/prepare_observation_benchmark.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_latest_snapshot_selected_by_event_sequence_and_hash_not_client_path(tmp_path):
    source=ROOT/'tests/fixtures/straight_pair.bpmn';body=source.read_bytes();archive=tmp_path/'observations.zip'
    event={'sequence':2,'snapshot':'snapshots/second.bpmn','sha256_after':hashlib.sha256(body).hexdigest(),'file':'C:/client/private/nonexistent.bpmn'}
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('session/events.jsonl',json.dumps(event));z.writestr('session/snapshots/second.bpmn',body)
    r=m.prepare(archive,tmp_path/'input',1)
    assert (tmp_path/'input/S1.bpmn').read_bytes()==body
    assert 'client' not in json.dumps(r) and r['sessions'][0]['last_sequence']==2


def test_bad_snapshot_hash_is_rejected_before_any_file_is_written(tmp_path):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('session/events.jsonl',json.dumps({'sequence':1,'snapshot':'snapshots/a.bpmn','sha256_after':'bad'}));z.writestr('session/snapshots/a.bpmn','wrong')
    with pytest.raises(ValueError,match='SHA256'):m.prepare(archive,tmp_path/'input',1)
    assert not (tmp_path/'input').exists()
