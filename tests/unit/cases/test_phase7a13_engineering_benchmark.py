from evaluation.engineering_benchmark_v1.contracts import (
    EngineeringBenchmarkManifest, EngineeringBenchmarkRecord,
)
from evaluation.engineering_benchmark_v1.metrics import summarize_routing
from evaluation.engineering_benchmark_v1.phase7a13b import _route_metrics


def _row(expected, predicted, expected_route, predicted_route):
    return {"expected_family": expected, "predicted_family": predicted,
            "expected_processing_route": expected_route,
            "predicted_processing_route": predicted_route,
            "predicted_top_level": "CLAIM" if expected in {"CMS1500", "UB04"} else "UNKNOWN",
            "source_dataset": "TEST", "quality_bucket": "clean",
            "latency_ms": {"total": 10}, "ocr_calls": 1, "cloud_api_calls": 0}


def test_manifest_is_explicitly_engineering_only():
    record = EngineeringBenchmarkRecord(document_id="d", page_id="1", expected_family="CMS1500",
        expected_processing_route="CMS_STANDARD_EXTRACTOR", source_dataset="TEST",
        synthetic_or_test=True, image_path="x.png", sha256="0" * 64)
    manifest = EngineeringBenchmarkManifest(records=[record], record_count=1)
    assert manifest.evidence_class == "ENGINEERING_BENCHMARK_ONLY"
    assert manifest.production_promotion_authority is False


def test_false_standard_authorization_uses_nonstandard_denominator():
    rows = [_row("CUSTOM_PROFESSIONAL", "CMS1500", "LAYOUT_STRUCTURED_EXTRACTOR",
                 "CMS_STANDARD_EXTRACTOR"),
            _row("CMS1500", "CMS1500", "CMS_STANDARD_EXTRACTOR", "CMS_STANDARD_EXTRACTOR")]
    metrics, _ = summarize_routing(rows)
    assert metrics["false_standard_authorization_count"] == 1
    assert metrics["false_standard_authorization_rate"] == 1.0


def test_safe_standard_fallback_is_not_false_authorization():
    rows = [_row("UB04", "UB04", "UB_STANDARD_EXTRACTOR", "LAYOUT_STRUCTURED_EXTRACTOR")]
    metrics, _ = summarize_routing(rows)
    assert metrics["safe_standard_fallback_rate"] == 1.0
    assert metrics["false_standard_authorization_count"] == 0


def test_phase7a13b_marks_unknown_unstructured_low_sample_without_a_gate():
    row = _row("UNKNOWN_UNSTRUCTURED", "UNKNOWN_UNSTRUCTURED", "UNSTRUCTURED_EXTRACTOR",
               "UNSTRUCTURED_EXTRACTOR")
    row["predicted_top_level"] = "UNKNOWN"
    metrics = _route_metrics([row])
    assert metrics["unknown_unstructured_sample_size"] == 1
    assert metrics["unknown_unstructured_status"] == "LOW_SAMPLE_SUPPORT"
    assert metrics["unknown_unstructured_recall"] == 1.0


def test_phase7a13b_fixed_route_requires_verified_firewall_evidence():
    row = _row("CMS1500", "CMS1500", "CMS_STANDARD_EXTRACTOR", "CMS_STANDARD_EXTRACTOR")
    row["standard_verification"] = None
    metrics = _route_metrics([row])
    assert metrics["unverified_fixed_authorization_count"] == 1
    assert metrics["route_extractor_firewall_violations"] == 1
