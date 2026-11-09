"""Build a source-only desktop distribution; never includes process inputs."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(target):
    paths = [ROOT / name for name in (
        'START_WINDOWS.cmd', 'run_v23.py', 'package.json', 'package-lock.json',
        'README.md', 'desktop/Start.ps1', 'desktop/app.py', 'desktop/index.html',
        'desktop/README.md', 'desktop/requirements.txt', 'desktop/example.json',
        'desktop/example.yaml', 'desktop/example-collaboration.json',
        'desktop/example-collaboration.yaml', 'desktop/INPUT_FORMAT.md',
        'docs/COLLABORATION_V23_5.md', 'docs/FIX_V23_5_1.md', 'tools/package_desktop.py')]
    for name in ('src/v23/bpmn_v23', 'src/v22/bpmn_universal', 'src/v22/bpmn_refkit', 'src/v22/schemas'):
        paths.extend(p for p in (ROOT / name).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    prefix = 'BPMN_Generator'
    manifest = {}
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            name = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            if path.suffix == '.cmd':
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            manifest[name] = hashlib.sha256(data).hexdigest()
            archive.writestr(prefix + '/' + name, data)
        archive.writestr(prefix + '/MANIFEST.sha256.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for name, digest in manifest.items():
            assert hashlib.sha256(archive.read(prefix + '/' + name)).hexdigest() == digest
    summary = {'file': target.name, 'bytes': target.stat().st_size, 'entries': len(manifest) + 1,
               'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    target.with_suffix('.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    print(json.dumps(build(parser.parse_args().output), indent=2))
