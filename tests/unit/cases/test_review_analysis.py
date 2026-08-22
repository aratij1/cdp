from evaluation.normalizers import NormalizerRegistry
from evaluation.review_analysis import analyze, safe_review_reduction
from evaluation.schemas import (
    GroundTruthDataset,
    GroundTruthDocument,
    GroundTruthField,
    PredictedField,
    PredictionDataset,
    PredictionDocument,
)
from packages.domain.enums import ReviewReasonCode
from packages.review_reasons import ReviewReasonContext, classify_review_reasons


def _truth() -> GroundTruthDataset:
    return GroundTruthDataset(
        documents=[
            GroundTruthDocument(
                document_id="doc-1",
                file_name="safe.png",
                form_type="CMS1500",
                fields=[
                    GroundTruthField(
                        field_name="patient_first",
                        expected_raw="ALICE",
                        critical=True,
                    )
                ],
            )
        ]
    )


def _pred(*, accepted: bool, value: str = "ALICE") -> PredictionDataset:
    return PredictionDataset(
        documents=[
            PredictionDocument(
                document_id="doc-1",
                fields=[
                    PredictedField(
                        field_name="patient_first",
                        raw_value=value,
                        confidence=0.95,
                        accepted=accepted,
                        metadata={
                            "independent_families": ["RAPID_ONNX_FAMILY"],
                            "ocr_candidates": [
                                {"engine": "rapidocr", "value": value},
                                {"engine": "paddleocr", "value": "AL1CE"},
                            ],
                        },
                    )
                ],
            )
        ]
    )


def test_review_reason_classifier_is_structured_and_multilabel():
    field = _pred(accepted=False).documents[0].fields[0]
    reasons = classify_review_reasons(
        ReviewReasonContext("CMS1500", "patient_first", True, field)
    )
    assert ReviewReasonCode.CRITICAL_NAME_UNVERIFIED in reasons
    assert ReviewReasonCode.OCR_DISAGREEMENT in reasons
    assert ReviewReasonCode.NO_REFERENCE_MATCH in reasons


def test_every_unaccepted_or_missing_field_gets_a_reason():
    rows, summary = analyze(_truth(), PredictionDataset(documents=[]), {})
    assert rows[0]["review_reason"] == "NO_EVIDENCE"
    assert summary["review_fields"] == 1
    assert summary["reason_coverage"] == 1.0


def test_safe_review_reduction_counts_only_correct_new_accepts():
    result = safe_review_reduction(
        _truth(), _pred(accepted=False), _pred(accepted=True), NormalizerRegistry()
    )
    assert result["safe_review_reduction"] == 1.0
    assert result["review_cases_removed"] == 1
    assert result["false_accepts_introduced"] == 0


def test_safe_review_reduction_exposes_new_false_accepts():
    result = safe_review_reduction(
        _truth(),
        _pred(accepted=False),
        _pred(accepted=True, value="BOB"),
        NormalizerRegistry(),
    )
    assert result["safe_review_reduction"] == 0.0
    assert result["false_accepts_introduced"] == 1
