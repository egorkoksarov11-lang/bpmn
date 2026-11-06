"""Normalize only the input, then call the unchanged pipeline CLI."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from .input_formats import EXTENSIONS, load_model, to_bpmn


def main():
    from .pipeline import main as pipeline_main
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args, _ = parser.parse_known_args()
    if args.input is None or args.input.suffix.lower() == '.bpmn':
        return pipeline_main()
    if args.input.suffix.lower() not in EXTENSIONS:
        parser.error('Поддерживаются .bpmn, .json, .yaml, .yml, .ylm')
    if args.output_dir is None: parser.error('Нужен --output-dir')
    if args.input.resolve().is_relative_to(args.output_dir.resolve()):
        parser.error('Каталог результата должен быть отдельным от каталога входного файла')
    original = sys.argv[:]
    with tempfile.TemporaryDirectory(prefix='bpmn-import-') as tmp:
        source = Path(tmp) / 'input_model.bpmn'
        report = to_bpmn(load_model(args.input), source)
        report.update(source_file=args.input.name, source_format=args.input.suffix.lower(),
                      source_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest())
        try:
            sys.argv = [original[0]]
            i = 1
            while i < len(original):
                if original[i] == '--input':
                    sys.argv.extend(['--input', str(source)]); i += 2
                elif original[i].startswith('--input='):
                    sys.argv.append('--input=' + str(source)); i += 1
                else:
                    sys.argv.append(original[i]); i += 1
            pipeline_main()
            shutil.copy2(source, args.output_dir / 'input_model.bpmn')
            (args.output_dir / 'input_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            sys.argv = original
