"""Portable launcher: python run_v23.py --input source.bpmn --output-dir output."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parent
sys.path[:0]=[str(root/'src/v23'),str(root/'src/v22')]
from bpmn_v23.pipeline import main
main()
