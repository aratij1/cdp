from packages.candidate_reconciliation import EvidenceReconciler
from packages.confidence import CalibrationRegistry, PlattCalibration
from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence import StructuralLocalizationEvidence, StructuralLocalizationType
from packages.evidence_decision import (
    DecisionContext,
    EvidenceDecisionService,
    FieldDisposition,
    NextAction,
    ReferenceEvidence,
)
from packages.ocr.contracts import OCRCandidate

BOX = BoundingBox(x0=0, y0=0, x1=10, y1=5, image_width=10, image_height=5)


def structure(field="patient_name"):
    return StructuralLocalizationEvidence(
        evidence_type=StructuralLocalizationType.ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED,
        confidence=.99, confirmed=True,
        reason_codes=("BOUNDED_ALIAS_MATCH", "OBSERVED_VALUE_SPAN_GEOMETRY"),
        source="test", field_name=field, field_bbox=(0, 0, 10, 5),
        localization_mode="ANCHOR_RELATIVE", positive_bounded_roi=True, geometry_valid=True,
    )


def candidate(engine: str, value: str, confidence: float = .99) -> OCRCandidate:
    return OCRCandidate(
        value=value, raw_value=value, engine=engine, model_name=engine,
        model_version="1", preprocessing_variant="test", raw_confidence=confidence,
        calibrated_confidence=None, bounding_box=BOX, latency_ms=1,
    )


def context(**changes) -> DecisionContext:
    values = {
        "field_name": "patient_name", "document_family": "CMS1500",
        "criticality": CriticalityLevel.C2, "blocks_stp": True,
        "candidates": [candidate("rapidocr", "JANE DOE"), candidate("paddleocr", "JANE DOE")],
        "deterministic_evidence": {"HARD_VALIDATION_PASSED"}, "hard_validation_passed": True,
        "structural_localization": structure(),
    }
    values.update(changes)
    return DecisionContext(**values)


def test_critical_field_cannot_bypass_evidence_policy():
    decision = EvidenceDecisionService().decide(context(
        candidates=[candidate("rapidocr", "JANE DOE")],
        registration_confidence=.95,
    ))
    assert decision.disposition != FieldDisposition.AUTO_ACCEPTED
    assert decision.evidence_bundle is not None
    assert not any(item.independent for item in decision.evidence_bundle.items)


def test_reference_plus_independent_ocr_can_confirm_critical_name():
    reference = ReferenceEvidence(
        value="JANE DOE", verified=True, source="eligibility", version="2026-08-22",
    )
    calibration = CalibrationRegistry({
        ("*", "*"): PlattCalibration(12.0, -6.0, "test-calibration-v1")
    })
    decision = EvidenceDecisionService(
        route_mode="evaluation",
        reconciler=EvidenceReconciler(calibration=calibration),
    ).decide(context(
        reference=reference, reference_source_state="AUTHORIZED",
        registration_confidence=.95,
        cross_field_evidence={"IDENTITY_RECONCILED"},
    ))
    assert decision.disposition == FieldDisposition.REFERENCE_CONFIRMED
    assert decision.next_action == NextAction.NONE


def test_verified_reference_replaces_uncalibrated_ocr_as_critical_authority():
    reference = ReferenceEvidence(
        value="JANE DOE", verified=True, source="eligibility", version="2026-08-22",
    )
    decision = EvidenceDecisionService(route_mode="evaluation").decide(context(
        reference=reference, reference_source_state="AUTHORIZED",
        registration_confidence=.95,
        cross_field_evidence={"IDENTITY_RECONCILED"},
    ))
    assert decision.disposition == FieldDisposition.REFERENCE_CONFIRMED
    assert "REFERENCE_MATCH" in decision.reason_codes


def test_uncalibrated_critical_ocr_without_reference_fails_closed():
    decision = EvidenceDecisionService(route_mode="evaluation").decide(context())
    assert decision.disposition == FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert "CALIBRATION_REQUIRED_FOR_CRITICAL_ACCEPTANCE" in decision.reason_codes


def test_high_confidence_cannot_override_wrong_crop():
    decision = EvidenceDecisionService().decide(context(wrong_crop_suspected=True))
    assert decision.disposition == FieldDisposition.ESCALATE
    assert decision.next_action == NextAction.CROP_RECOVERY


def test_reference_contradiction_always_requires_review():
    reference = ReferenceEvidence(value="OTHER", verified=True, contradiction=True)
    decision = EvidenceDecisionService().decide(context(reference=reference))
    assert decision.disposition == FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert decision.reason_codes == ["REFERENCE_CONTRADICTION"]


def test_optional_low_criticality_field_is_non_blocking():
    decision = EvidenceDecisionService().decide(context(
        field_name="address_line_2", criticality=CriticalityLevel.C0,
        blocks_stp=False, candidates=[],
    ))
    assert decision.disposition == FieldDisposition.UNRESOLVED_NON_BLOCKING
    assert decision.evidence_bundle is not None
    assert decision.evidence_bundle.route_status == "DISABLED"
    assert decision.evidence_bundle.route_id == "CMS1500.address_line_2.no-route"


def test_gpt4o_crop_authorized_for_member_id_and_dob():
    """v12.3n: azure_gpt4o_crop must not be stripped as ENGINE_NOT_AUTHORIZED."""
    from packages.evidence.builder import engine_family

    assert engine_family("azure_gpt4o_crop") == "CLOUD_AI_FAMILY"
    service = EvidenceDecisionService(route_mode="evaluation")
    id_decision = service.decide(context(
        field_name="insured_id_number",
        criticality=CriticalityLevel.C1,
        candidates=[
            candidate("paddleocr", "Mrieniian", 0.53),
            candidate("azure_gpt4o_crop", "949774145", 0.99),
        ],
        registration_confidence=0.95,
        structural_localization=structure("insured_id_number"),
    ))
    assert not any(
        code.startswith("CANDIDATE_ENGINE_NOT_AUTHORIZED")
        for code in id_decision.reason_codes
    )
    assert id_decision.selected_value == "949774145"
    sources = {
        item.source
        for item in (id_decision.evidence_bundle.items if id_decision.evidence_bundle else [])
    }
    assert "azure_gpt4o_crop" in sources

    dob_decision = service.decide(context(
        field_name="patient_dob",
        criticality=CriticalityLevel.C1,
        candidates=[
            candidate("rapidocr", "30:", 0.7),
            candidate("azure_gpt4o_crop", "07/30/1977", 0.99),
        ],
        registration_confidence=0.95,
        structural_localization=structure("patient_dob"),
    ))
    assert not any(
        code.startswith("CANDIDATE_ENGINE_NOT_AUTHORIZED")
        for code in dob_decision.reason_codes
    )
    dob_sources = {
        item.source
        for item in (dob_decision.evidence_bundle.items if dob_decision.evidence_bundle else [])
    }
    assert "azure_gpt4o_crop" in dob_sources


def test_gpt4o_crop_authorized_for_patient_and_insured_name():
    """Name ink residual: azure_gpt4o_crop must not be stripped as unauthorized."""
    service = EvidenceDecisionService(route_mode="evaluation")
    for field_name, value in (
        ("patient_name", "THOMAS DARLENE"),
        ("insured_name", "THOMAS DARLENE"),
    ):
        decision = service.decide(context(
            field_name=field_name,
            criticality=CriticalityLevel.C1,
            candidates=[
                candidate("paddleocr", "THOMAS.DARLENE.M", 0.9),
                candidate("rapidocr", "THOMAS, DARLENE", 0.88),
                candidate("azure_gpt4o_crop", value, 0.98),
            ],
            registration_confidence=0.95,
            structural_localization=structure(field_name),
        ))
        assert not any(
            code.startswith("CANDIDATE_ENGINE_NOT_AUTHORIZED")
            for code in decision.reason_codes
        ), field_name
        sources = {
            item.source
            for item in (decision.evidence_bundle.items if decision.evidence_bundle else [])
        }
        assert "azure_gpt4o_crop" in sources, field_name


def test_document_family_finance_authorized_for_total_charge():
    """Line-sum finance candidate must not be stripped as ENGINE_NOT_AUTHORIZED."""
    service = EvidenceDecisionService(route_mode="evaluation")
    decision = service.decide(context(
        field_name="total_charge",
        criticality=CriticalityLevel.C1,
        candidates=[
            candidate("paddleocr", "", 0.99),
            candidate("document_family_finance", "1825.00", 0.95),
            candidate("azure_document_intelligence_read", "182500.00", 0.85),
        ],
        registration_confidence=0.95,
        structural_localization=structure("total_charge"),
        deterministic_evidence={"HARD_VALIDATION_PASSED", "CHARGE_TOTAL_AUTHORITY"},
        hard_validation_passed=True,
    ))
    assert not any(
        code.startswith("CANDIDATE_ENGINE_NOT_AUTHORIZED")
        for code in decision.reason_codes
    )
    sources = {
        item.source
        for item in (decision.evidence_bundle.items if decision.evidence_bundle else [])
    }
    assert "document_family_finance" in sources
    values = {
        getattr(item, "value", None)
        for item in (decision.evidence_bundle.items if decision.evidence_bundle else [])
    }
    assert "1825.00" in values or decision.selected_value == "1825.00"
