"""Desktop transport, failure handling, package isolation and Windows deadline."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('desktop_app', ROOT / 'desktop/app.py')
app_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_module)


def await_result(app):
    end = time.monotonic() + 10
    while app.snapshot()['status'] == 'running' and time.monotonic() < end:
        time.sleep(.02)
    assert app.snapshot()['status'] != 'running'
    return app.snapshot()


def test_success_and_archive(tmp_path, monkeypatch):
    # Exercise real process, artifact checks and packaging with a tiny producer.
    script = """import pathlib,json,sys
p=pathlib.Path(sys.argv[1]);p.mkdir()
for name,data in {'process_08_v23.bpmn':'<xml/>','process_08_v23.svg':'<svg/>','semantic_diff.json':json.dumps({'equal':True,'diff_count':0}),'geometry_report.json':'{}','run_report.json':'{}'}.items():
 (p/name).write_text(data)
"""
    monkeypatch.setattr(app_module, 'command', lambda source, output: [sys.executable, '-c', script, str(output)])
    app = app_module.Application(tmp_path)
    app.start('../путь/договор.bpmn', b'original')
    result = await_result(app)
    assert result['status'] == 'done'
    folder = Path(result['folder'])
    assert folder.parent == tmp_path
    assert (folder / 'original.bpmn').read_bytes() == b'original'
    with zipfile.ZipFile(folder / 'result.zip') as archive:
        assert archive.testzip() is None
        assert 'generated.bpmn' in archive.namelist()


def test_failed_engine_does_not_offer_diagram(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, 'command', lambda *_: [sys.executable, '-c', 'raise ValueError("bad model")'])
    app = app_module.Application(tmp_path)
    app.start('bad.bpmn', b'not xml')
    result = await_result(app)
    assert result['status'] == 'error'
    assert result['files'] == ['generation.log']
    assert 'bad model' in result['log']


def test_http_access_and_input_rejection(tmp_path):
    app = app_module.Application(tmp_path)
    server, url = app_module.make_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert urllib.request.urlopen(url).status == 200
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(url.split('?')[0] + 'status')
        assert missing.value.code == 403
        req = urllib.request.Request(url.replace('/?', '/generate?') + '&name=x.txt', data=b'x')
        with pytest.raises(urllib.error.HTTPError) as invalid:
            urllib.request.urlopen(req)
        assert invalid.value.code == 400
        req = urllib.request.Request(url.replace('/?', '/generate?') + '&name=x.bpmn', data=b'x',
                                     headers={'Origin': 'https://example.com'})
        with pytest.raises(urllib.error.HTTPError) as foreign:
            urllib.request.urlopen(req)
        assert foreign.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as traversal:
            urllib.request.urlopen(url.replace('/?', '/download?') + '&name=../app.py')
        assert traversal.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_cooperative_deadline_restores_profiler(monkeypatch):
    from bpmn_v23 import deadline as module
    monkeypatch.delattr(module.signal, 'SIGALRM', raising=False)
    before = sys.getprofile()
    def step():
        return time.monotonic()
    with pytest.raises(TimeoutError):
        with module.deadline(.02):
            end = time.monotonic() + 2
            while step() < end:
                step()
    assert sys.getprofile() is before


def test_distribution_contains_code_and_no_inputs(tmp_path):
    spec = importlib.util.spec_from_file_location('package_desktop', ROOT / 'tools/package_desktop.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / 'app.zip'
    module.build(target)
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert 'BPMN_Generator/START_WINDOWS.cmd' in names
        assert any(name.endswith('OpenSans-Regular.ttf') for name in names)
        assert any(name.endswith('elk_runner.cjs') for name in names)
        assert not any('/inputs/' in name or '/node_modules/' in name or '/results/' in name for name in names)
