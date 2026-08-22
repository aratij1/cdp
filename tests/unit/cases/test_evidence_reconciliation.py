from packages.candidate_reconciliation import Decision, EvidenceReconciler
from packages.confidence import CalibrationRegistry, IsotonicCalibration
from packages.criticality import CriticalityLevel, CriticalityPolicy
from packages.domain.common import BoundingBox
from packages.ocr.contracts import OCRCandidate


def _candidate(value: str, engine: str, confidence: float = 0.999) -> OCRCandidate:
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine=engine,
        model_name=engine,
        model_version="1",
        preprocessing_variant="original",
        raw_confidence=confidence,
        calibrated_confidence=None,
        bounding_box=BoundingBox(x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100),
        latency_ms=1,
    )


def test_c3_rejects_single_engine_regardless_of_confidence():
    result = EvidenceReconciler().reconcile(
        "npi", [_candidate("1234567893", "rapidocr", 1.0)], CriticalityLevel.C3
    )
    assert result.decision == Decision.REVIEW
    assert "FIELD_EVIDENCE_POLICY_NOT_SATISFIED" in result.rationale_codes


def test_two_paddle_variants_are_not_independent_evidence():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "paddleocr"), _candidate("1234567893", "pp-ocr-v5")],
        CriticalityLevel.C3,
    )
    assert result.decision == Decision.REVIEW
    assert "MULTI_ENGINE_AGREEMENT" not in result.rationale_codes


def test_npi_accepts_independent_agreement_plus_checksum():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "rapidocr"), _candidate("1234567893", "tesseract")],
        CriticalityLevel.C3,
        deterministic_evidence={"CHECKSUM_VALID"},
    )
    assert result.decision == Decision.ACCEPT
    assert result.selected_value == "1234567893"
    assert "MULTI_ENGINE_AGREEMENT" in result.rationale_codes
    assert len([item for item in result.supporting_evidence if item.evidence_type == "OCR_CANDIDATE"]) == 2


def test_npi_checksum_alone_cannot_supply_complete_evidence():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "rapidocr")],
        CriticalityLevel.C3,
        deterministic_evidence={"CHECKSUM_VALID"},
    )
    assert result.decision == Decision.REVIEW
    assert "CHECKSUM_VALID" in result.rationale_codes
    assert "FIELD_EVIDENCE_POLICY_NOT_SATISFIED" in result.rationale_codes


def test_unverified_reference_value_cannot_authorize_c3_acceptance():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "rapidocr")],
        CriticalityLevel.C3,
        authoritative_value="1234567893",
    )
    assert result.decision == Decision.REVIEW
    assert "REFERENCE_MATCH" not in result.rationale_codes


def test_governed_reference_can_authorize_c3_acceptance():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "rapidocr")],
        CriticalityLevel.C3,
        authoritative_value="1234567893",
        authoritative_reference_verified=True,
        authoritative_source="nppes-snapshot",
        authoritative_version="2026-08",
    )
    assert result.decision == Decision.REFERENCE_CONFIRMED
    assert "REFERENCE_MATCH" in result.rationale_codes
    reference = next(
        item for item in result.supporting_evidence
        if item.evidence_type == "AUTHORITATIVE_REFERENCE"
    )
    assert reference.source == "nppes-snapshot"
    assert reference.reference == "2026-08"


def test_governed_reference_contradiction_blocks_consensus_acceptance():
    result = EvidenceReconciler().reconcile(
        "npi",
        [_candidate("1234567893", "rapidocr"), _candidate("1234567893", "tesseract")],
        CriticalityLevel.C3,
        deterministic_evidence={"CHECKSUM_VALID"},
        authoritative_value="1999999999",
        authoritative_reference_verified=True,
        authoritative_source="nppes-snapshot",
        authoritative_version="2026-08",
    )
    assert result.decision == Decision.REVIEW
    assert "REFERENCE_CONTRADICTION" in result.rationale_codes
    assert any(
        item.reason_code == "REFERENCE_CONTRADICTION"
        for item in result.conflicting_evidence
    )


def test_calibrated_probability_not_raw_score_drives_threshold():
    registry = CalibrationRegistry(
        {("rapidocr", "member_id"): IsotonicCalibration((0.0, 1.0), (0.1, 0.7), "member-v2")}
    )
    result = EvidenceReconciler(registry).reconcile(
        "member_id", [_candidate("A123", "rapidocr", 0.99)], CriticalityLevel.C2
    )
    assert result.decision == Decision.ESCALATE
    assert result.calibration_model_version == "member-v2"


def test_criticality_policy_is_externalized():
    policy = CriticalityPolicy.load("config/field_criticality.yaml")
    assert policy.for_field("rendering_provider_npi") == CriticalityLevel.C3
    assert policy.for_field("unknown_optional") == CriticalityLevel.C1
