"""Local desktop front end; standard library only, no cloud processing."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit
import webbrowser
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_INPUT = 25_000_000


def command(source, output):
    # Never pass reference coordinates, incumbent layouts or lexical hints.
    return [sys.executable, '-u', str(ROOT / 'run_v23.py'), '--input', str(source),
            '--output-dir', str(output), '--layout-engine', 'scratch',
            '--candidate-timeout', '60', '--search-seconds', '200']


class Application:
    def __init__(self, results=None):
        self.results = Path(results or ROOT / 'results').resolve()
        self.lock = threading.Lock()
        self.state = {'status': 'idle', 'log': '', 'files': []}
        self.process = None

    def snapshot(self):
        with self.lock:
            result = dict(self.state)
            if 'started' in result:
                result['elapsed'] = round(time.monotonic() - result['started'])
            return result

    def start(self, name, data):
        suffix = Path(name).suffix.lower()
        if suffix not in {'.bpmn', '.json', '.yaml', '.yml', '.ylm'}:
            raise ValueError('Выберите .bpmn, .json, .yaml или .yml (.ylm также принимается)')
        if not data or len(data) > MAX_INPUT:
            raise ValueError('Размер файла должен быть от 1 байта до 25 МБ')
        with self.lock:
            if self.state['status'] == 'running':
                raise ValueError('Дождитесь завершения текущей схемы')
            # Never use user-provided names as paths. Keep originals untouched.
            folder = self.results / (time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3))
            folder.mkdir(parents=True)
            source = folder / ('original' + suffix)
            source.write_bytes(data)
            self.state = {'status': 'running', 'name': name, 'started': time.monotonic(),
                          'folder': str(folder), 'log': 'Построение новой схемы по связям…\n', 'files': []}
            self.folder = folder
            worker = threading.Thread(target=self._run, args=(source, folder), daemon=True)
            worker.start()

    def _run(self, source, folder):
        log = folder / 'generation.log'
        try:
            env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
            with log.open('w', encoding='utf-8') as stream:
                with self.lock:
                    process = subprocess.Popen(command(source, folder / 'output'), cwd=ROOT,
                                               stdout=stream, stderr=subprocess.STDOUT, env=env)
                    self.process = process
                while process.poll() is None:
                    with self.lock:
                        self.state['log'] = log.read_text(encoding='utf-8', errors='replace')[-16000:]
                    time.sleep(.5)
                if process.returncode:
                    lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
                    errors = [line for line in lines if line.startswith('ValueError:') or ': error:' in line]
                    detail = errors[-1][:600] if errors else 'Подробности — в журнале ниже.'
                    raise RuntimeError('Генератор отклонил схему. ' + detail)
            output = folder / 'output'
            semantic = json.loads((output / 'semantic_diff.json').read_text(encoding='utf-8'))
            if semantic.get('equal') is not True or semantic.get('diff_count') != 0:
                raise RuntimeError('Проверка сохранности бизнес-логики не пройдена')
            shutil.copy2(output / 'process_08_v23.bpmn', folder / 'generated.bpmn')
            shutil.copy2(output / 'process_08_v23.svg', folder / 'generated.svg')
            for name in ('geometry_report.json', 'semantic_diff.json', 'run_report.json'):
                shutil.copy2(output / name, folder / name)
            names = ['generated.bpmn', 'generated.svg', 'geometry_report.json',
                     'semantic_diff.json', 'run_report.json', 'generation.log']
            for name in ('input_model.bpmn', 'input_report.json'):
                if (output / name).is_file():
                    shutil.copy2(output / name, folder / name)
                    names.append(name)
            if source.suffix.lower() != '.bpmn':
                names.append(source.name)
            manifest = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in names}
            (folder / 'SHA256.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            with zipfile.ZipFile(folder / 'result.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
                for name in names + ['SHA256.json']:
                    archive.write(folder / name, name)
            with self.lock:
                self.state.update(status='done', files=['result.zip', 'generated.bpmn', 'generated.svg',
                                                       'geometry_report.json', 'semantic_diff.json'],
                                  log=log.read_text(encoding='utf-8', errors='replace')[-16000:])
        except Exception as error:
            with log.open('a', encoding='utf-8') as stream:
                traceback.print_exc(file=stream)
            with self.lock:
                files=['generation.log']
                diagnostic=folder/'output/geometry_error.json'
                if diagnostic.is_file():
                    shutil.copy2(diagnostic,folder/'geometry_error.json');files.append('geometry_error.json')
                self.state.update(status='error', error=str(error), files=files,
                                  log=log.read_text(encoding='utf-8', errors='replace')[-16000:])
        finally:
            with self.lock:
                self.process = None

    def stop(self):
        with self.lock:
            process = self.process
        if process and process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            else:
                process.terminate()
            process.wait(timeout=15)


def make_server(app):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, content, kind='application/json; charset=utf-8', filename=None):
            if not isinstance(content, bytes):
                content = content.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            if filename:
                self.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
            self.end_headers()
            self.wfile.write(content)

        def authorized(self):
            params = parse_qs(urlsplit(self.path).query)
            expected_host = '127.0.0.1:' + str(self.server.server_port)
            return (self.headers.get('Host') == expected_host and
                    secrets.compare_digest(params.get('token', [''])[0], token))

        def do_GET(self):
            if not self.authorized():
                self.send(403, '{}')
                return
            path = urlsplit(self.path).path
            if path == '/':
                self.send(200, (ROOT / 'desktop/index.html').read_bytes(), 'text/html; charset=utf-8')
            elif path == '/status':
                self.send(200, json.dumps(app.snapshot(), ensure_ascii=False))
            elif path in ('/example.json', '/example.yaml', '/example-collaboration.json', '/example-collaboration.yaml'):
                name = path[1:]
                self.send(200, (ROOT / 'desktop' / name).read_bytes(),
                          'application/octet-stream', name)
            elif path == '/download':
                name = parse_qs(urlsplit(self.path).query).get('name', [''])[0]
                with app.lock:
                    valid = name in app.state['files']
                    folder = getattr(app, 'folder', None)
                if not valid or folder is None:
                    self.send(404, '{}')
                else:
                    self.send(200, (folder / name).read_bytes(), 'application/octet-stream', name)
            else:
                self.send(404, '{}')

        def do_POST(self):
            if not self.authorized() or urlsplit(self.path).path != '/generate':
                self.send(403, '{}')
                return
            expected_origin = 'http://127.0.0.1:' + str(self.server.server_port)
            if self.headers.get('Origin') not in (None, expected_origin):
                self.send(403, '{}')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_INPUT:
                    raise ValueError('Размер файла должен быть от 1 байта до 25 МБ')
                name = parse_qs(urlsplit(self.path).query).get('name', [''])[0]
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('Файл передан не полностью')
                app.start(name, data)
                self.send(202, '{}')
            except (ValueError, OSError) as error:
                self.send(400, json.dumps({'error': str(error)}, ensure_ascii=False))

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    return server, 'http://127.0.0.1:' + str(server.server_port) + '/?token=' + quote(token)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, help='headless generation for automated checks')
    parser.add_argument('--results', type=Path)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    app = Application(args.results)
    if args.input:
        app.start(args.input.name, args.input.read_bytes())
        try:
            while app.snapshot()['status'] == 'running':
                time.sleep(.5)
        finally:
            app.stop()
        print(json.dumps(app.snapshot(), ensure_ascii=False, indent=2))
        return 0 if app.snapshot()['status'] == 'done' else 1
    server, url = make_server(app)
    print('BPMN Generator: ' + url, flush=True)
    print('Ctrl+C to exit. Results: ' + str(app.results), flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
