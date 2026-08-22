import json
from pathlib import Path
import pytest
from evaluation.freeze_router_v4_candidate import freeze
from evaluation.router_v4_holdout_gate import validate_holdout

def test_failed_cross_source_run_cannot_create_candidate(tmp_path):
    report=tmp_path/"report.json"; report.write_text(json.dumps({"gates":{"ALL":False}}))
    with pytest.raises(RuntimeError,match="cross-source gates failed"): freeze(report)

def test_holdout_cannot_run_without_candidate(tmp_path):
    result=validate_holdout(tmp_path/"manifest.json",tmp_path/"candidate.json")
    assert result=={"decision":"NEEDS_MORE_DATA","reason":"ROUTER_V4_CANDIDATE_1_DOES_NOT_EXIST","routing_permitted":False}

def test_incomplete_provenance_fails_closed(tmp_path):
    candidate=tmp_path/"candidate.json"; candidate.write_text("{}")
    manifest=tmp_path/"manifest.json"; manifest.write_text(json.dumps({"dataset_id":"x"}))
    result=validate_holdout(manifest,candidate)
    assert result["routing_permitted"] is False
    assert "ground_truth_hash" in result["missing"]
