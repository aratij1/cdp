import json

from evaluation.pre_v3_holdout_gate import evaluate


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_gate_passes_only_after_routing_accuracy_and_cost_recovery(tmp_path):
    routing = _write(tmp_path/"routing.json", {
        "metrics": {"UB04": {"recall": 1.0, "precision": 1.0}}
    })
    extraction = _write(tmp_path/"extraction.json", {
        "overall": {"accuracy": .99},
        "qualification": {"false_accepts": 0},
    })

    report = evaluate(routing, extraction)

    assert report["status"] == "READY_TO_CREATE_FRESH_V3_HOLDOUT"
    assert all(report["checks"].values())
    assert report["governance"]["holdout_used_for_tuning"] is False
    assert report["governance"]["v3_holdout_created"] is False


def test_gate_blocks_sub_98pct_ub_recall(tmp_path):
    routing = _write(tmp_path/"routing.json", {
        "metrics": {"UB04": {"recall": .975, "precision": 1.0}}
    })
    extraction = _write(tmp_path/"extraction.json", {
        "overall": {"accuracy": .99},
        "qualification": {"false_accepts": 0},
    })

    report = evaluate(routing, extraction)

    assert report["status"] == "BLOCKED"
    assert not report["checks"]["independent_development_ub04_recall_at_least_98pct"]
