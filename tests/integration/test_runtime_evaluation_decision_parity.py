from evaluation.optimize_hitl_evidence import evidence_decision
from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence_decision import (
    DecisionContext, EvidenceDecisionService, ReferenceEvidence,
)
from packages.ocr.contracts import OCRCandidate


def _candidate(engine: str) -> OCRCandidate:
    return OCRCandidate(
        value="JANE", raw_value="JANE", engine=engine, model_name=engine,
        model_version="evaluation-recorded", preprocessing_variant="recorded",
        raw_confidence=.95, calibrated_confidence=None,
        bounding_box=BoundingBox(x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1),
        latency_ms=0,
    )


def test_runtime_and_evaluation_use_identical_final_decision_logic():
    reference = {
        "decision": "REFERENCE_VERIFIED", "reference_value": "JANE",
        "reference_provider": "eligibility", "reference_dataset_version": "v1",
    }
    evaluation_field = {
        "field_name": "patient_first", "accepted": False,
        "metadata": {"ocr_candidates": [
            {"engine": "rapidocr", "value": "JANE", "confidence": .95},
            {"engine": "paddleocr", "value": "JANE", "confidence": .95},
        ]},
    }
    evaluation_result = evidence_decision(evaluation_field, reference)
    runtime_result = EvidenceDecisionService().decide(DecisionContext(
        field_name="patient_first", document_family="*", criticality=CriticalityLevel.C2,
        candidates=[_candidate("rapidocr"), _candidate("paddleocr")],
        deterministic_evidence={"HARD_VALIDATION_PASSED"}, hard_validation_passed=True,
        reference=ReferenceEvidence(
            value="JANE", verified=True, source="eligibility", version="v1",
        ),
    ))
    assert evaluation_result["final_disposition"] == runtime_result.disposition.value
    assert evaluation_result["policy_version"] == runtime_result.policy_version
    assert evaluation_result["reason_codes"] == runtime_result.reason_codes
