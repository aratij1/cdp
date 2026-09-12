"""Synthetic control-plane tests; no production measurement or human truth claim."""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from packages.real_data_evaluation.blind_workflow import BlindReviewStore, content_digest
from packages.real_data_evaluation.closure_control import (
    DEPLOYMENT_CHECKS,
    deployment_evidence,
    freeze_prerequisites,
)
from packages.real_data_evaluation.qualification_jobs import advance
from tests.unit.cases.test_qualification_closure_inputs import (
    annotation,
    snapshots,
    sources,
)


def test_raw_scores_before_final_and_disjoint_claim_outcomes():
    truth, raw, final, membership, score = snapshots()
    result = score(truth, raw, None, membership)
    assert result["status"] == "RAW_EVALUATED_FINAL_PENDING"
    assert result["raw"]["critical_field_hitl"] == 1 / 8
    assert result["post_hitl"] == {}
    assert result["breakdowns"]["form"]["CMS1500"]["critical_false_accepts"] == 1
    result = score(truth, raw, final, membership)
    assert result["post_hitl"]["hitl_closed_claims"] == 1
    assert result["post_hitl"]["true_stp_claims"] == 0
    assert result["post_hitl"]["unresolved"] == 0


def test_human_corrected_raw_claim_cannot_be_stp():
    truth, raw, final, membership, score = snapshots()
    raw["fields"] = copy.deepcopy(final["fields"])
    raw["claims"]["claim"]["human_corrected"] = True
    raw["snapshot_sha256"] = content_digest(
        {k: v for k, v in raw.items() if k != "snapshot_sha256"}
    )
    assert score(truth, raw, final, membership)["raw"]["stp"] == 0


def inputs(tmp_path):
    source = sources()
    manifest = json.dumps({"pages": [{"page_id": "page", "package_id": "package"}]}).encode()
    sha = hashlib.sha256(manifest).hexdigest()
    bindings = {
        "blind_manifest_sha256": sha,
        "bindings": [
            {
                "source_page_id": "page",
                "cdp_page_id": "cdp-page",
                "state": "EXACT",
                "package_id": "package",
                "rendered_page_sha256": source["page"]["rendered_page_sha256"],
                "cdp_page_sha256": source["page"]["rendered_page_sha256"],
            }
        ],
    }
    reservation = {
        "blind_manifest_sha256": content_digest(json.loads(manifest)),
        "assignments": {"package": "HOLDOUT"},
    }
    return source, manifest, bindings, reservation


def test_truth_cannot_freeze_on_summary_coverage_or_changed_reservation(tmp_path):
    source, manifest, bindings, reservation = inputs(tmp_path)
    sha = hashlib.sha256(manifest).hexdigest()
    assert (
        freeze_prerequisites(source, bindings, reservation, sha, json.loads(manifest))["status"]
        == "PASS"
    )
    bindings["binding_coverage"] = 1
    bindings["bindings"][0]["state"] = "AMBIGUOUS"
    assert (
        freeze_prerequisites(source, bindings, reservation, sha, json.loads(manifest))["status"]
        == "FAIL"
    )
    bindings["bindings"][0]["state"] = "EXACT"
    reservation["blind_manifest_sha256"] = "changed"
    assert (
        freeze_prerequisites(source, bindings, reservation, sha, json.loads(manifest))["status"]
        == "FAIL"
    )


def test_watcher_freezes_and_runs_raw_then_final_without_manual_snapshots(tmp_path, monkeypatch):
    from evaluation import candidate_runtime_freeze

    monkeypatch.setattr(candidate_runtime_freeze, "readiness", lambda root: {"status":"PASS"})
    from evaluation import final_qualification
    from evaluation import qualification_closure as watcher

    source, manifest, bindings, reservation = inputs(tmp_path)
    out = tmp_path / "evaluation_results/qualification_closure"
    out.mkdir(parents=True)

    def put(name, payload):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))

    manifest_path = tmp_path / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(manifest)
    put("evaluation_results/production_closure/release/package_reservation.local.json", reservation)
    put(
        "evaluation_results/qualification_closure/blind_source_views.local.json",
        [{"page_id": "page", **source["page"]}],
    )
    put("evaluation_results/qualification_closure/source_page_bindings.local.json", bindings)
    put(
        "evaluation_results/qualification_closure/source_binding_summary.json",
        {"binding_coverage": 1},
    )
    from tests.track_b_helpers import governed_registry

    governed_registry(tmp_path, out, monkeypatch)
    _, raw, final, membership, _ = snapshots()
    membership["complete_claim_membership_confirmed"] = True
    membership["claims"]["claim"].update(
        {
            "claim_form_page_ids": ["page"],
            "attachment_page_ids": [],
            "documents": {
                "doc": {
                    "page_ids": ["page"],
                    "boundary": "CONFIRMED",
                    "boundary_provenance": "synthetic-owner-approval",
                }
            },
        }
    )
    put("evaluation_results/qualification_closure/claim_membership.local.json", membership)
    store = BlindReviewStore(out / "blind_reviews.sqlite3")
    for person in ("one", "two"):
        store.save(
            "page", person, source["page"]["rendered_page_sha256"], annotation(), complete=True
        )
    from evaluation.track_b_review_provenance import record

    for row in store.completed():
        record(
            out,
            "REVIEW_COMPLETE",
            row["page_id"],
            row["reviewer_id"],
            row["source_sha256"],
            row["annotation"],
            round_name="synthetic",
        )
    monkeypatch.setattr(watcher, "ROOT", tmp_path)
    monkeypatch.setattr(watcher, "OUT", out)
    monkeypatch.setattr(final_qualification, "build", lambda: None)
    finished = False
    calls = []

    def executor(directory, phase, inputs, config):
        calls.append(phase)
        if phase == "RAW":
            (out / "raw_predictions.local.json").write_text(json.dumps(raw))
        if phase == "HITL_FINAL" and finished:
            (out / "post_hitl_predictions.local.json").write_text(json.dumps(final))
        return {"status": "IN_PROGRESS"}

    monkeypatch.setattr(watcher, "advance", executor)
    contract = tmp_path / "config/qualification/reviewer_registry.yaml"
    contract_bytes = contract.read_bytes()
    contract.unlink()
    blocked = watcher.refresh()
    assert not (out / "release_truth_manifest.local.json").exists()
    assert blocked["scoring"]["status"] == "NOT_EVALUABLE"
    assert "RAW" not in calls
    contract.write_bytes(contract_bytes)
    first = watcher.refresh()
    assert (out / "release_truth_manifest.local.json").exists()
    assert first["scoring"]["status"] == "RAW_EVALUATED_FINAL_PENDING"
    assert "HITL_FINAL" in calls and first["scoring"]["raw"]["critical_false_accepts"] == 1
    finished = True
    second = watcher.refresh()
    assert second["scoring"]["post_hitl"]["final_accuracy"] == 1
    assert second["scoring"]["raw"]["accuracy"] == 0.875
    assert second["status"] == "NO_GO"
    assert second["release_authority_enabled"] is False


def test_executor_submits_once_and_validates_receipt(tmp_path, monkeypatch):
    executable = Path(sys.executable)
    config = {
        "governed": True,
        "deployment_id": "synthetic",
        "approval_reference": "unit-test",
        "jobs": {
            "RAW": {
                "argv": [str(executable), "-V"],
                "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            }
        },
    }
    launches = []

    class Process:
        pid = 123

    monkeypatch.setattr(
        "packages.real_data_evaluation.qualification_jobs.subprocess.Popen",
        lambda *a, **k: launches.append(a) or Process(),
    )
    first = advance(tmp_path, "RAW", {"cohort": "synthetic"}, config)
    advance(tmp_path, "RAW", {"cohort": "synthetic"}, config)
    assert len(launches) == 1
    with pytest.raises(ValueError, match="IMMUTABLE_EXECUTION_INPUT_CHANGED"):
        advance(tmp_path, "RAW", {"cohort": "changed"}, config)
    output = tmp_path / "result.local.json"
    output.write_text("{}")
    receipt = {
        "request_id": first["request_id"],
        "status": "PASS",
        "outputs": {output.name: hashlib.sha256(output.read_bytes()).hexdigest()},
    }
    receipt["receipt_sha256"] = content_digest(receipt)
    path = tmp_path / "jobs/RAW/receipt.local.json"
    path.write_text(json.dumps(receipt))
    assert advance(tmp_path, "RAW", {"cohort": "synthetic"}, config)["status"] == "PASS"
    output.write_text("changed")
    with pytest.raises(ValueError, match="OUTPUT_HASH_MISMATCH"):
        advance(tmp_path, "RAW", {"cohort": "synthetic"}, config)


def test_operational_evidence_requires_every_check_and_real_load_counters():
    assert deployment_evidence({}, None, None)["status"] == "NOT_AVAILABLE"
    payload = {
        "scope": "PRODUCTION_DEPLOYMENT",
        "configuration_sha256": "config",
        "truth_sha256": "truth",
        "run_id": "synthetic",
        "checks": {
            k: {"status": "PASS", "artifact_sha256": "synthetic"} for k in DEPLOYMENT_CHECKS
        },
    }
    assert (
        deployment_evidence(payload, "config", "truth")["checks"]["load"]["status"]
        == "NOT_AVAILABLE"
    )
    payload["checks"]["security"]["status"] = "FAIL"
    assert deployment_evidence(payload, "config", "truth")["status"] == "FAIL"
    assert (
        deployment_evidence(payload, "different", "truth")["checks"]["database"]["status"]
        == "NOT_AVAILABLE"
    )


def test_deployment_pass_requires_present_unchanged_artifact(tmp_path):
    artifact = tmp_path / "database-run.local.json"
    artifact.write_text('{"synthetic_test": true}')
    payload = {
        "scope": "PRODUCTION_DEPLOYMENT",
        "configuration_sha256": "config",
        "truth_sha256": "truth",
        "run_id": "synthetic",
        "checks": {
            "database": {
                "status": "PASS",
                "artifact": artifact.name,
                "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        },
    }
    assert (
        deployment_evidence(payload, "config", "truth", tmp_path)["checks"]["database"]["status"]
        == "PASS"
    )
    artifact.write_text("changed")
    assert (
        deployment_evidence(payload, "config", "truth", tmp_path)["checks"]["database"]["status"]
        == "FAIL"
    )
    artifact.unlink()
    assert (
        deployment_evidence(payload, "config", "truth", tmp_path)["checks"]["database"]["status"]
        == "NOT_AVAILABLE"
    )


def test_invalid_input_withdraws_board_and_raw_final_scores(tmp_path, monkeypatch):
    from evaluation import final_qualification
    from evaluation import qualification_closure as watcher

    monkeypatch.setattr(watcher, "ROOT", tmp_path)
    monkeypatch.setattr(watcher, "OUT", tmp_path)
    monkeypatch.setattr(final_qualification, "build", lambda: None)
    watcher.write(
        "closure_tracker.json",
        {
            "status": "PRODUCTION_CANDIDATE",
            "release_decision": "GO",
            "scoring": {"raw": {"accuracy": 1}, "post_hitl": {"final_accuracy": 1}},
            "blockers": [{"gate": "ACCURACY", "status": "PASS", "current_value": 1}],
        },
    )
    watcher.invalidate()
    tracker = watcher.load(tmp_path / "closure_tracker.json")
    board = watcher.load(tmp_path / "release_blocker_board.json")
    assert tracker["release_decision"] == "NO_GO"
    assert tracker["scoring"]["raw"] == tracker["scoring"]["post_hitl"] == {}
    assert board["gates"] == tracker["blockers"]
    assert board["gates"][0]["status"] == "NOT_EVALUABLE"


def test_deployment_jobs_advance_without_human_truth(tmp_path, monkeypatch):
    from evaluation import candidate_runtime_freeze

    monkeypatch.setattr(candidate_runtime_freeze, "readiness", lambda root: {"status":"PASS"})
    from evaluation import final_qualification
    from evaluation import qualification_closure as watcher

    monkeypatch.setattr(watcher, "ROOT", tmp_path)
    monkeypatch.setattr(watcher, "OUT", tmp_path / "qualification")
    monkeypatch.setattr(final_qualification, "build", lambda: None)
    calls = []

    def advance(directory, phase, inputs, config):
        calls.append(phase)
        return {"status": "NOT_AVAILABLE"}

    monkeypatch.setattr(watcher, "advance", advance)
    result = watcher.refresh()
    assert calls == ["TARGET_LATENCY", "OPERATIONAL_PREFLIGHT"]
    assert result["scoring"]["status"] == "NOT_EVALUABLE"
    assert result["status"] == "EXTERNAL_INPUT_REQUIRED"


def test_frozen_manifest_rejects_subset_and_changed_content(tmp_path):
    source, manifest, bindings, reservation = inputs(tmp_path)
    parsed = json.loads(manifest)
    sha = hashlib.sha256(manifest).hexdigest()
    assert freeze_prerequisites(source, bindings, reservation, sha, parsed)["status"] == "PASS"
    parsed["pages"].append({"page_id": "missing", "package_id": "package"})
    assert freeze_prerequisites(source, bindings, reservation, sha, parsed)["status"] == "FAIL"
    reservation["blind_manifest_sha256"] = content_digest(parsed)
    assert freeze_prerequisites(source, bindings, reservation, sha, parsed)["status"] == "FAIL"
