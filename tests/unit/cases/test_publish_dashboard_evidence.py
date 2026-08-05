import json
from pathlib import Path

from PIL import Image

from evaluation.publish_dashboard_evidence import publish


def test_publish_dashboard_adds_evidence_and_optimization(tmp_path: Path) -> None:
    image = tmp_path / "crop.png"
    Image.new("RGB", (20, 10), "white").save(image)
    report_path = tmp_path / "public" / "reports" / "evaluation.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({
        "llm_diverted_fields": 2, "llm_diversion_rate": 0.2,
        "report_metadata": {},
    }), encoding="utf-8")
    details_path = tmp_path / "details.json"
    details_path.write_text(json.dumps([{
        "field_identity": {"document_id": "D1", "document_family": "CMS1500", "semantic_field": "dob"},
        "expected_value": "01012000", "selected_value": "01/01/2000",
        "normalized_value": "01012000", "provider": "paddle", "confidence": 0.9,
        "selected_correct": True, "provenance": {"crop_path": str(image), "original_page": str(image)},
    }]), encoding="utf-8")
    optimization_path = tmp_path / "optimization.json"
    optimization_path.write_text(json.dumps({
        "total_fields": 10, "baseline_correct": 8, "azure_correct_recoveries": 1,
        "paddle_correct_recoveries": 1, "deterministic_derived_recoveries": 1,
    }), encoding="utf-8")

    result = publish(
        report_path,
        details_path,
        optimization_path,
        tmp_path / "no-local-first.json",
        tmp_path / "runtime" / "evaluation.json",
        llm_cost_path=tmp_path / "no-llm-cost.json",
    )
    published = json.loads(report_path.read_text(encoding="utf-8"))

    assert result["published_fields"] == 1
    assert published["field_evidence"][0]["crop_url"].startswith("/reports/evidence/")
    assert published["optimization_metrics"]["llm_incremental_recovery_rate"] == 0.1
    assert published["report_metadata"]["production_generalization_claim"] is False
    assert "document_family_report" not in published
    assert published["llm_processing_cost"] == {
        "currency": "USD",
        "run_cost_usd": None,
        "routed_fields": 2,
        "status": "NOT_METERED",
        "basis": "LLM fields were routed, but provider token usage was not captured.",
    }


def test_publish_dashboard_projects_llm_processing_cost(tmp_path: Path) -> None:
    report_path = tmp_path / "evaluation.json"
    report_path.write_text(json.dumps({
        "llm_diverted_fields": 5,
        "llm_diversion_rate": 0.02,
        "report_metadata": {},
    }), encoding="utf-8")
    details_path = tmp_path / "details.json"
    details_path.write_text(json.dumps([{
        "field_identity": {
            "document_id": "D1", "document_family": "CMS1500",
            "semantic_field": "patient_name",
        },
        "expected_value": "JANE DOE", "selected_value": "JANE DOE",
        "normalized_value": "JANE DOE", "provider": "paddle",
        "confidence": 0.99, "selected_correct": True, "provenance": {},
    }]), encoding="utf-8")
    optimization_path = tmp_path / "optimization.json"
    optimization_path.write_text(json.dumps({
        "total_fields": 239, "baseline_correct": 200,
        "azure_correct_recoveries": 4, "paddle_correct_recoveries": 0,
        "deterministic_derived_recoveries": 0,
    }), encoding="utf-8")
    llm_cost_path = tmp_path / "llm-cost.json"
    llm_cost_path.write_text(json.dumps({
        "fields_attempted": 9, "estimated_cost_usd": 0.03456,
    }), encoding="utf-8")

    publish(
        report_path, details_path, optimization_path,
        tmp_path / "no-local-first.json",
        tmp_path / "runtime.json",
        hitl_predictions_path=tmp_path / "no-hitl.json",
        llm_cost_path=llm_cost_path,
    )

    published = json.loads(report_path.read_text(encoding="utf-8"))
    assert published["llm_processing_cost"]["run_cost_usd"] == 0.0192
    assert published["llm_processing_cost"]["status"] == "ESTIMATED"
