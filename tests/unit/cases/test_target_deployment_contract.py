"""Synthetic qualification contract tests; never deployment evidence."""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from evaluation.production_latency_governor import SEMANTIC_KEYS
from evaluation.qualification_latency import target_latency_evidence
from packages.real_data_evaluation.blind_workflow import content_digest
from packages.real_data_evaluation.qualification_jobs import advance, publish


def fixture():
    page = {k: "synthetic" for k in SEMANTIC_KEYS}
    page.update(
        page_id="page",
        strict_family="UNKNOWN",
        identity_confirmed=False,
        canonical_localization_invoked=False,
        cache_hit=False,
        full_page_ocr_calls=1,
        memory_rss_bytes=1024,
        full_claim_context_available=True,
        stages={"total_ms": 1000},
    )
    runs = [
        {
            "mode": "COLD_FIRST_PASS" if i == 0 else "WARM_STEADY_STATE",
            "pages": [copy.deepcopy(page)],
            "latency": {"P50": 1000, "P95": 1000, "P99": 1000, "throughput_pages_per_second": 1},
        }
        for i in range(4)
    ]
    baseline = {"scope": "FROZEN_SEMANTIC_BASELINE", "experiments": copy.deepcopy(runs)}
    canaries = {str(i): str(i) * 64 for i in range(3)}
    payload = {
        "scope": "COMPLETE_PRODUCTION_PAGE_PATH",
        "configuration_sha256": "config",
        "deployment_id": "target",
        "run_id": "synthetic",
        "baseline_sha256": content_digest(baseline),
        "profile": {"scope": "COMPLETE_PRODUCTION_PAGE_PATH", "experiments": runs},
        "runtime": {
            k: "synthetic"
            for k in (
                "host_id",
                "cpu_model",
                "logical_cpus",
                "execution_provider",
                "runtime_version",
                "os",
                "gpu_model",
            )
        },
        "ub04_canaries": [
            {
                "page_id": k,
                "semantic_sha256": v,
                "strict_family": "UB04",
                "identity_confirmed": True,
                "canonical_localization_invoked": True,
                "critical_safety": "PASS",
            }
            for k, v in canaries.items()
        ],
    }
    return baseline, payload, canaries


def evaluate(baseline, payload, canaries):
    payload["evidence_sha256"] = content_digest(
        {k: v for k, v in payload.items() if k != "evidence_sha256"}
    )
    return target_latency_evidence(payload, baseline, "config", "target", canaries)


def test_measured_target_recomputes_gate():
    baseline, payload, canaries = fixture()
    result = evaluate(baseline, payload, canaries)
    assert result["status"] == "PASS"
    assert result["run_p95_ms"] == [1000] * 3
    payload["profile"]["experiments"][1]["pages"][0]["candidate_semantics_sha256"] = "changed"
    assert evaluate(baseline, payload, canaries)["status"] == "FAIL"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (
            lambda p: p["profile"]["experiments"][1]["latency"].update(P99=1),
            "PERCENTILE_DOES_NOT_MATCH_MEASUREMENTS",
        ),
        (
            lambda p: p["profile"]["experiments"][1]["latency"].update(
                throughput_pages_per_second=2
            ),
            "THROUGHPUT_DOES_NOT_MATCH_MEASUREMENTS",
        ),
        (
            lambda p: p["profile"]["experiments"][1]["pages"][0].update(
                canonical_localization_invoked=True
            ),
            "UNSAFE_UNKNOWN_OR_OTHER_LOCALIZATION",
        ),
        (
            lambda p: p["ub04_canaries"][0].update(semantic_sha256="changed"),
            "UB04_CANARY_SEMANTIC_OR_SAFETY_FAILURE",
        ),
    ],
)
def test_target_rejects_corrupt_measurements(mutation, reason):
    baseline, payload, canaries = fixture()
    mutation(payload)
    result = evaluate(baseline, payload, canaries)
    assert result["status"] == "FAIL"
    assert reason in result["reasons"]


def test_summary_or_wrong_host_cannot_pass():
    assert (
        target_latency_evidence(
            {"semantic_equality": True, "median_warm_p95_ms": 1}, {}, "config", "target"
        )["status"]
        == "NOT_AVAILABLE"
    )
    baseline, payload, canaries = fixture()
    payload["deployment_id"] = "different"
    assert evaluate(baseline, payload, canaries)["status"] == "NOT_AVAILABLE"
    payload["deployment_id"] = "target"
    assert evaluate(baseline, payload, {})["status"] == "NOT_AVAILABLE"


def test_failed_start_can_be_retried(tmp_path, monkeypatch):
    executable = Path(sys.executable)
    config = {
        "governed": True,
        "deployment_id": "synthetic",
        "approval_reference": "test",
        "jobs": {
            "RAW": {
                "argv": [str(executable)],
                "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            }
        },
    }
    calls = []

    def start(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise OSError("synthetic launch failure")
        return type("Process", (), {"pid": 123})()

    monkeypatch.setattr("packages.real_data_evaluation.qualification_jobs.subprocess.Popen", start)
    assert advance(tmp_path, "RAW", {}, config)["status"] == "NOT_AVAILABLE"
    assert advance(tmp_path, "RAW", {}, config)["status"] == "IN_PROGRESS"
    assert advance(tmp_path, "RAW", {}, config)["status"] == "IN_PROGRESS"
    assert len(calls) == 2


def test_publication_is_complete_before_visible(tmp_path, monkeypatch):
    import os

    original = os.link
    observed = []

    def link(source, destination):
        observed.append(json.loads(Path(source).read_text()))
        assert not Path(destination).exists()
        original(source, destination)

    monkeypatch.setattr("packages.real_data_evaluation.qualification_jobs.os.link", link)
    path = tmp_path / "request.json"
    publish(path, {"complete": True})
    assert observed == [{"complete": True}]
    assert not list(tmp_path.glob("*.tmp"))


def test_executor_checks_content_not_just_stored_hash(tmp_path):
    from evaluation.deployment_control_executor import validate_execution_inputs

    cohort = {"claims": {"synthetic": {}}}
    cohort["cohort_sha256"] = content_digest(cohort)
    request = {
        "contract": "CDP_QUALIFICATION_EXECUTION_V1",
        "phase": "RAW",
        "inputs": {"cohort_sha256": cohort["cohort_sha256"]},
    }
    request["request_id"] = content_digest(request)
    validate_execution_inputs(request, cohort, tmp_path)
    cohort["claims"]["tampered"] = {}
    with pytest.raises(ValueError, match="EXECUTION_COHORT_CHANGED"):
        validate_execution_inputs(request, cohort, tmp_path)


def test_executor_requires_original_raw_snapshot_for_final(tmp_path):
    from evaluation.deployment_control_executor import validate_execution_inputs

    cohort = {"claims": {"synthetic": {}}}
    cohort["cohort_sha256"] = content_digest(cohort)
    raw = {"fields": []}
    raw["snapshot_sha256"] = content_digest(raw)
    request = {
        "contract": "CDP_QUALIFICATION_EXECUTION_V1",
        "phase": "HITL_FINAL",
        "inputs": {"cohort_sha256": cohort["cohort_sha256"], "raw_sha256": raw["snapshot_sha256"]},
    }
    request["request_id"] = content_digest(request)
    (tmp_path / "raw_predictions.local.json").write_text(json.dumps(raw))
    validate_execution_inputs(request, cohort, tmp_path)
    raw["fields"].append({"accepted": True})
    (tmp_path / "raw_predictions.local.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="RAW_EXECUTION_SNAPSHOT_CHANGED"):
        validate_execution_inputs(request, cohort, tmp_path)
