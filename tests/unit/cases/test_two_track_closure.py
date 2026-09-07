"""Watcher integration cannot overwrite owner input or keep stale measured scores."""

import json

from evaluation import two_track_closure as module


def setup_inputs(tmp_path, monkeypatch):
    out = tmp_path / "evaluation_results/real_release"
    out.mkdir(parents=True)
    (out / "governed_30_manifest.json").write_text("{}")
    monkeypatch.setattr(
        module,
        "isolation_check",
        lambda root: {"status": "PASS", "source_seals_verified": True, "overlap": 0},
    )
    monkeypatch.setattr(module, "reference_adapter", lambda root: {})
    monkeypatch.setattr(module, "field_metrics", lambda root: {"status": "NOT_EVALUABLE"})
    return out


def test_owner_editable_request_preserved(tmp_path, monkeypatch):
    out = setup_inputs(tmp_path, monkeypatch)
    csv = out / "150_cohort_missing_membership.csv"
    csv.write_text("owner-supplied-content")
    monkeypatch.setattr(
        module,
        "lineage_recovery",
        lambda root: (_ for _ in ()).throw(AssertionError("must not overwrite")),
    )
    result = module.build(tmp_path)
    assert result["track_a"] == "EXECUTION_INCOMPLETE"
    assert csv.read_text() == "owner-supplied-content"


def test_isolation_failure_withdraws_old_metrics(tmp_path, monkeypatch):
    out = setup_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "isolation_check", lambda root: {"status": "FAIL"})
    (out / "governed_30_engineering_scorecard.json").write_text('{"status":"MEASURED"}')
    assert module.build(tmp_path)["status"] == "INPUT_INVALID_OR_CHANGED"
    assert (
        json.loads((out / "governed_30_engineering_scorecard.json").read_text())["status"]
        == "NOT_EVALUABLE"
    )
