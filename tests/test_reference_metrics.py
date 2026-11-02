from bpmn_v23.reference_metrics import calibrate,evaluate,features
from pathlib import Path
import pytest


def test_80_percent_requires_every_hard_gate_and_weak_family_guard():
 row=features(Path(__file__).resolve().parents[1]/'output/process_08_v23.bpmn');profile=calibrate([row.copy() for _ in range(5)])
 passed={k:True for k in ['semantic_freeze','DI_freeze','routing_safety','clearance','text_and_labels','no_pathological_bends']}
 assert evaluate(row,profile,{})['target_reached'] is False
 assert evaluate(row,profile)['target_reached'] is False
 assert evaluate(row,profile,{'semantics':True,'geometry':False})['target_reached'] is False
 assert evaluate(row,profile,passed)['target_reached'] is True
 bad={**row,'bends_per_flow':100,'p90_bends':100,'straight_fraction':0}
 assert not evaluate(bad,profile,passed)['target_reached']


def test_better_route_metrics_are_not_penalized():
 row=features(Path(__file__).resolve().parents[1]/'output/process_08_v23.bpmn');profile=calibrate([row.copy() for _ in range(5)])
 improved={**row,'bends_per_flow':0,'p90_bends':0,'straight_fraction':1,'contacts_per_flow':0}
 assert evaluate(improved,profile)['conformity_percent']>=evaluate(row,profile)['conformity_percent']


def test_too_few_reference_models_are_rejected():
 with pytest.raises(ValueError):calibrate([])
