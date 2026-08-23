from evaluation.routing.leave_one_source_out import evaluate, run_runtime_parity_loso


def _row(source, truth, predicted, route, **extra):
    return {"source_family": source, "truth_top_level": extra.get("truth_top_level", "CLAIM"),
            "predicted_top_level": extra.get("predicted_top_level", "CLAIM"),
            "truth_standard": extra.get("truth_standard", True),
            "standard_nominated": extra.get("standard_nominated", True),
            "truth_subtype": truth, "nominated_family": predicted,
            "verified_family": extra.get("verified_family", predicted), "latency_ms": extra.get("latency_ms", 10),
            "outcome": {"truth": truth, "prediction": predicted, "authorized_route": route}}


def test_loso_reports_each_source_and_worst_source_metrics():
    report = evaluate([
        _row("A", "CMS1500", "CMS1500", "CMS_STANDARD_EXTRACTOR"),
        _row("B", "UB04", "UNKNOWN", "SAFE_UNKNOWN", standard_nominated=False,
             verified_family=None),
    ])
    assert set(report["source_metrics"]) == {"A", "B"}
    assert report["aggregate"]["processing_route_accuracy"]["worst_source"] == 0
    assert "latency_p95_ms" in report["source_metrics"]["A"]
    assert "latency_p99_ms" in report["source_metrics"]["A"]
    assert "stage_latency_ms" in report["source_metrics"]["A"]


def test_error_metrics_use_highest_source_as_worst():
    report = evaluate([
        _row("A", "EOB", "EOB", "LAYOUT_STRUCTURED_EXTRACTOR",
             truth_top_level="CLAIM_SUPPORT", predicted_top_level="CLAIM_SUPPORT",
             truth_standard=False, standard_nominated=False, verified_family=None),
        _row("B", "EOB", "UB04", "UB_STANDARD_EXTRACTOR",
             truth_top_level="CLAIM_SUPPORT", predicted_top_level="CLAIM",
             truth_standard=False, standard_nominated=True, verified_family="UB04"),
    ])
    assert report["aggregate"]["false_standard_authorization_rate"]["worst_source"] == 1


def test_runtime_parity_runner_calls_canonical_decision_service():
    routing = {"route": "UNKNOWN_STRUCTURED", "confidence": .8,
        "scores": {"CMS1500": .1, "UB04": .1, "UNKNOWN_STRUCTURED": .8,
                   "UNKNOWN_UNSTRUCTURED": .2, "NON_CLAIM": .1},
        "best_score": .8, "second_best_score": .2, "margin": .6, "grid_score": .8,
        "horizontal_line_score": .8, "vertical_line_score": .8,
        "healthcare_label_density": .4, "matched_anchors": {}, "reason_codes": ["STRUCTURED"]}
    report = run_runtime_parity_loso([{"source_family": "source-a", "document_id": "d",
        "page_id": "p", "truth_top_level": "CLAIM", "truth_subtype": "OTHER_STRUCTURED_CLAIM",
        "expected_processing_route": "LAYOUT_STRUCTURED_EXTRACTOR", "routing_evidence": routing}])
    assert report["execution_contract"].startswith("DocumentRoutingDecisionService")
    assert report["source_metrics"]["source-a"]["processing_route_accuracy"] == 1
