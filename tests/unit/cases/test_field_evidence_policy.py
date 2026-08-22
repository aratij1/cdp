from packages.candidate_reconciliation import Decision, EvidenceReconciler
from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence_policy import EvidencePolicyRegistry
from packages.ocr.contracts import OCRCandidate


def _candidate(value: str, engine: str = "rapidocr") -> OCRCandidate:
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine=engine,
        model_name=engine,
        model_version="1",
        preprocessing_variant="original",
        raw_confidence=0.999,
        calibrated_confidence=None,
        bounding_box=BoundingBox(
            x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100
        ),
        latency_ms=1,
    )


def _two(value: str) -> list[OCRCandidate]:
    return [_candidate(value, "rapidocr"), _candidate(value, "tesseract")]


def test_patient_name_requires_reference_even_with_ocr_agreement() -> None:
    reconciler = EvidenceReconciler()
    without_reference = reconciler.reconcile(
        "patient_name", _two("JANE SMITH"), CriticalityLevel.C2
    )
    assert without_reference.decision == Decision.REVIEW
    with_reference = reconciler.reconcile(
        "patient_name",
        _two("JANE SMITH"),
        CriticalityLevel.C2,
        authoritative_value="JANE SMITH",
        authoritative_reference_verified=True,
    )
    assert with_reference.decision == Decision.REFERENCE_CONFIRMED


def test_member_id_requires_ocr_and_reference_or_three_attribute_reference() -> None:
    reconciler = EvidenceReconciler()
    assert reconciler.reconcile("member_id", _two("M123"), CriticalityLevel.C2).decision == Decision.REVIEW
    result = reconciler.reconcile(
        "member_id",
        [_candidate("M123")],
        CriticalityLevel.C2,
        authoritative_value="M123",
        authoritative_reference_verified=True,
        deterministic_evidence={"DOB_MATCH", "NAME_MATCH"},
    )
    assert result.decision == Decision.REFERENCE_CONFIRMED


def test_code_requires_versioned_code_reference_signal_with_ocr_consensus() -> None:
    reconciler = EvidenceReconciler()
    assert reconciler.reconcile("cpt_hcpcs", _two("99213"), CriticalityLevel.C3).decision == Decision.REVIEW
    result = reconciler.reconcile(
        "cpt_hcpcs",
        _two("99213"),
        CriticalityLevel.C3,
        deterministic_evidence={"CODE_REFERENCE_VALID"},
    )
    assert result.decision == Decision.ACCEPT


def test_total_charge_requires_cross_field_financial_reconciliation() -> None:
    reconciler = EvidenceReconciler()
    assert reconciler.reconcile("total_charge", _two("1675.00"), CriticalityLevel.C3).decision == Decision.REVIEW
    result = reconciler.reconcile(
        "total_charge",
        _two("1675.00"),
        CriticalityLevel.C3,
        deterministic_evidence={"FINANCIAL_RECONCILIATION_VALID"},
    )
    assert result.decision == Decision.ACCEPT


def test_document_family_override_precedes_criticality_default() -> None:
    registry = EvidencePolicyRegistry.load()
    cms = registry.rule_for("CMS1500", "insured_id_number", CriticalityLevel.C2)
    ub = registry.rule_for("UB04", "insured_id_number", CriticalityLevel.C2)
    assert cms.any_of != ub.any_of
