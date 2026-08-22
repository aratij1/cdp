from pathlib import Path

import pytest

from packages.experiment_ledger import ExperimentRecord, MetricSnapshot, append_record, decide, deltas


def metrics(**changes: float) -> MetricSnapshot:
    values = dict(overall_accuracy=.72, critical_field_accuracy=.65, false_accept_rate=0,
                  stp_rate=0, review_rate=.77, p95_latency_ms=435, cost_per_page_usd=.77)
    values.update(changes)
    return MetricSnapshot(**values)


def test_promotion_is_blocked_on_false_accept_regression() -> None:
    assert decide(metrics(), metrics(false_accept_rate=.001, overall_accuracy=.80), minimum_samples_met=True)[0] == "REJECT"


def test_ledger_is_append_only_and_delta_checked(tmp_path: Path) -> None:
    base, candidate = metrics(), metrics(overall_accuracy=.73)
    record = ExperimentRecord(experiment_id="exp-001", hypothesis="registration improves accuracy",
        dataset_version="dev-v1", code_commit="9eb917b", config_sha256="a" * 64,
        template_version="cms1500@02-12", baseline=base, candidate=candidate,
        delta=deltas(base, candidate), decision="PROMOTE", decision_reason="safe gain")
    ledger = tmp_path / "ledger.jsonl"
    assert len(append_record(ledger, record)) == 64
    with pytest.raises(ValueError, match="already exists"):
        append_record(ledger, record)
