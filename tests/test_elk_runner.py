"""Optional actual-engine check; core Python tests do not require Node."""
import json,shutil,subprocess
from pathlib import Path
import pytest


def test_actual_elk_keeps_ids_and_directs_acyclic_chain_right():
    root=Path(__file__).resolve().parents[1]
    module=root/'node_modules/elkjs/lib/elk.bundled.js'
    if not shutil.which('node') or not module.exists():pytest.skip('optional npm ci required')
    graph={'id':'root','layoutOptions':{'elk.algorithm':'layered','elk.direction':'RIGHT'},'children':[{'id':n,'width':100,'height':60} for n in ['a','b','c']],'edges':[{'id':'f','sources':['a'],'targets':['b']},{'id':'g','sources':['b'],'targets':['c']}]}
    r=subprocess.run(['node',str(root/'src/v23/bpmn_v23/assets/elk_runner.cjs'),str(module)],input=json.dumps(graph),capture_output=True,text=True,check=True,timeout=20)
    result=json.loads(r.stdout);boxes={n['id']:n for n in result['children']}
    assert set(boxes)=={'a','b','c'}
    assert boxes['a']['x']<boxes['b']['x']<boxes['c']['x']
    assert {e['id'] for e in result['edges']}=={'f','g'}
