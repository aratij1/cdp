from __future__ import annotations

import csv
import json

import pytest

from evaluation.metrics import character_error_rate, evaluate
from evaluation.normalizers import NormalizerRegistry, amount, code, date, digits, identifier, text
from evaluation.reports import write_reports
from evaluation.schemas import GroundTruthDataset, PredictionDataset


@pytest.mark.parametrize(
    ("normalizer", "raw", "expected"),
    [
        (text, "  Jane   Doe ", "Jane Doe"),
        (identifier, " ab-12 3 ", "AB123"),
        (digits, "13-96827531", "1396827531"),
        (code, " e11. 9 ", "E11.9"),
        (date, "07/30/2026", "2026-07-30"),
        (amount, "$1,234.5", "1234.50"),
    ],
)
def test_normalizers(normalizer, raw, expected):
    assert normalizer(raw) == expected


def _datasets() -> tuple[GroundTruthDataset, PredictionDataset]:
    truth = GroundTruthDataset.model_validate(
        {
            "schema_version": "1.0",
            "documents": [
                {
                    "document_id": "A-01",
                    "file_name": "M047FJFL.001",
                    "form_type": "CMS1500",
                    "fields": [
                        {
                            "field_name": "billing_provider_npi",
                            "expected_raw": "1396827531",
                            "expected_normalized": "1396827531",
                            "required": True,
                            "critical": True,
                        },
                        {
                            "field_name": "total_charge",
                            "expected_raw": "100.00",
                            "expected_normalized": "100.00",
                        },
                    ],
                }
            ],
        }
    )
    predictions = PredictionDataset.model_validate(
        {
            "documents": [
                {
                    "document_id": "A-01",
                    "fields": [
                        {
                            "field_name": "billing_provider_npi",
                            "raw_value": "139682753I",
                            "normalized_value": "1396827531",
                            "confidence": 0.99,
                            "validation_result": "VALID",
                            "extraction_method": "REGIONAL_PADDLEOCR",
                            "accepted": True,
                        },
                        {
                            "field_name": "total_charge",
                            "raw_value": "900.00",
                            "normalized_value": "900.00",
                            "confidence": 0.98,
                            "validation_result": "VALID",
                            "extraction_method": "REGIONAL_PADDLEOCR",
                            "accepted": True,
                        },
                    ],
                }
            ]
        }
    )
    return truth, predictions


def test_metrics_distinguish_raw_normalized_and_false_accepts():
    truth, predictions = _datasets()
    metrics = evaluate(
        truth,
        predictions,
        NormalizerRegistry({"billing_provider_npi": "digits", "total_charge": "amount"}),
    )
    assert metrics.raw_exact_match_accuracy == 0
    assert metrics.normalized_field_accuracy == 0.5
    assert metrics.critical_field_accuracy == 1
    assert metrics.false_accept_rate == 0.5
    assert metrics.critical_false_accept_rate == 0
    assert metrics.perfect_claim_rate == 0
    assert metrics.straight_through_processing_rate is None
    assert metrics.mismatches[0].field_name == "total_charge"
    assert metrics.mismatches[0].failure_category == "FALSE_ACCEPT"


def test_reports_emit_json_csv_and_escaped_html(tmp_path):
    truth, predictions = _datasets()
    metrics = evaluate(truth, predictions)
    metrics.mismatches[0].extracted_value = "<script>alert(1)</script>"
    write_reports(metrics, tmp_path)
    assert json.loads((tmp_path / "evaluation.json").read_text())["field_count"] == 2
    with (tmp_path / "mismatches.csv").open(newline="", encoding="utf-8") as handle:
        assert next(csv.DictReader(handle))["field_name"] == "total_charge"
    report = (tmp_path / "mismatches.html").read_text(encoding="utf-8")
    assert "<script>" not in report
    assert "&lt;script&gt;" in report


def test_character_error_rate_uses_edit_distance():
    assert character_error_rate("ABC", "ADC") == pytest.approx(1 / 3)
