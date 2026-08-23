from evaluation.routing.development_gate import evaluate_gate


def _report(value=1.0, false_rate=0.0):
    metrics = {
        "top_level_worst_recall": value, "standard_precision": value,
        "standard_recall": value,
        "cms1500_nomination_recall": value, "ub04_nomination_recall": value,
        "processing_route_accuracy": value, "false_standard_authorization_rate": false_rate,
        "unverified_fixed_authorization_count": 0, "route_extractor_firewall_violations": 0,
    }
    return {"source_metrics": {"source-a": {}},
            "aggregate": {name: {"worst_source": metric} for name, metric in metrics.items()}}


def test_development_gate_passes_only_all_worst_source_thresholds():
    assert evaluate_gate(_report())["passed"]
    failed = _report()
    failed["aggregate"]["ub04_nomination_recall"]["worst_source"] = .97
    assert not evaluate_gate(failed)["passed"]
    assert not evaluate_gate(failed)["frozen_abcd_allowed"]


def test_no_source_results_never_pass():
    assert not evaluate_gate({"source_metrics": {}, "aggregate": {}})["passed"]
