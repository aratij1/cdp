from evaluation.optimize_hitl_evidence import evidence_decision
from packages.criticality import CriticalityLevel
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.domain.common import BoundingBox
from packages.evidence_decision import (
    DecisionContext,
    EvidenceDecisionService,
    ReferenceEvidence,
)
from packages.evidence_router import ReferenceSourceState
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
    evaluation_result = evidence_decision(
        evaluation_field, reference,
        registration_confidence=.95,
        structural_evidence_source="MEASURED_REGISTRATION:test",
        reference_source_state=ReferenceSourceState.AUTHORIZED,
    )
    deterministic = DeterministicEvidenceService().evaluate("patient_first", "JANE")
    runtime_result = EvidenceDecisionService().decide(DecisionContext(
        field_name="patient_first", document_family="*", criticality=CriticalityLevel.C2,
        candidates=[_candidate("rapidocr"), _candidate("paddleocr")],
        deterministic_evidence=deterministic.evidence,
        hard_validation_passed=deterministic.passed,
        registration_confidence=.95,
        structural_evidence_source="MEASURED_REGISTRATION:test",
        reference=ReferenceEvidence(
            value="JANE", verified=True, source="eligibility", version="v1",
        ),
        reference_source_state=ReferenceSourceState.AUTHORIZED,
    ))
    assert evaluation_result["final_disposition"] == runtime_result.disposition.value
    assert evaluation_result["policy_version"] == runtime_result.policy_version
    assert evaluation_result["reason_codes"] == runtime_result.reason_codes


def test_same_persisted_route_status_and_policy_produce_identical_field_decision():
    context = DecisionContext(
        field_name="insured_id_number", document_family="CMS1500",
        criticality=CriticalityLevel.C3, blocks_stp=True,
        candidates=[_candidate("paddleocr"), _candidate("rapidocr")],
        deterministic_evidence={"HARD_VALIDATION_PASSED"},
        hard_validation_passed=True, registration_confidence=.95,
        structural_evidence_source="MEASURED_REGISTRATION:test",
    )

    runtime = EvidenceDecisionService(route_mode="runtime").decide(context)
    evaluation = EvidenceDecisionService(route_mode="evaluation").decide(
        DecisionContext.model_validate(context.model_dump(mode="json"))
    )

    assert runtime.evidence_bundle is not None
    assert evaluation.evidence_bundle is not None
    assert runtime.evidence_bundle.route_id == evaluation.evidence_bundle.route_id
    assert runtime.evidence_bundle.route_status == "PRODUCTION_APPROVED"
    assert evaluation.evidence_bundle.route_status == "PRODUCTION_APPROVED"
    runtime_payload = runtime.model_dump(mode="json")
    evaluation_payload = evaluation.model_dump(mode="json")
    runtime_payload["evidence_bundle"]["route_mode"] = None
    evaluation_payload["evidence_bundle"]["route_mode"] = None
    assert runtime_payload == evaluation_payload
