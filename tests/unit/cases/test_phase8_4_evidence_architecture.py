from pathlib import Path

import pytest

from packages.claim_decision import ClaimDecisionContext, ClaimDecisionService
from packages.claim_evidence import ClaimEvidenceBuilder
from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence import (
    EvidenceClass,
    EvidencePolicy,
    FieldEvidenceBundle,
    PolicyReachabilityAudit,
    PolicyReachabilityStatus,
    StructuralLocalizationEvidence,
    StructuralLocalizationType,
    build_evidence_bundle,
)
from packages.evidence_decision import (
    DecisionContext,
    EvidenceDecisionService,
    FieldDecision,
    FieldDisposition,
    NextAction,
)
from packages.field_localization import FieldDefinitionRegistry
from packages.field_policy import FieldPolicyRegistry
from packages.ocr.contracts import OCRCandidate

ROOT = Path(__file__).resolve().parents[3]
BOX = BoundingBox(x0=0, y0=0, x1=10, y1=5, image_width=10, image_height=5)


def _candidate(value: str = "123") -> OCRCandidate:
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine="rapidocr_full_page",
        model_name="rapidocr",
        model_version="1",
        preprocessing_variant="test",
        raw_confidence=0.99,
        calibrated_confidence=None,
        bounding_box=BOX,
        latency_ms=1,
    )


def test_e3_requires_qualified_structural_evidence_not_a_mode_string():
    unqualified = build_evidence_bundle(
        field_name="type_of_bill",
        candidates=[_candidate()],
        registration_confidence=0.99,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID"},
        hard_validation_passed=True,
        structural_localization=StructuralLocalizationEvidence(
            evidence_type=StructuralLocalizationType.ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED,
            confidence=0.99,
            confirmed=False,
            source="DYNAMIC_GEOMETRY:ANCHOR_RELATIVE",
        ),
    )
    assert EvidenceClass.E3 not in unqualified.available_classes

    qualified = build_evidence_bundle(
        field_name="type_of_bill",
        candidates=[_candidate()],
        registration_confidence=0.99,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID"},
        hard_validation_passed=True,
        structural_localization=StructuralLocalizationEvidence(
            evidence_type=StructuralLocalizationType.ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED,
            confidence=0.99,
            confirmed=True,
            reason_codes=("ANCHOR_MATCH_PASSED", "BOUNDED_ROI_PASSED"),
            source="DYNAMIC_GEOMETRY:ANCHOR_RELATIVE",
        ),
    )
    e3 = [item for item in qualified.evidence_items if item.evidence_class is EvidenceClass.E3]
    assert [item.evidence_type for item in e3] == [
        StructuralLocalizationType.ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED.value
    ]


def test_wrong_crop_firewall_suppresses_otherwise_qualified_e3():
    bundle = build_evidence_bundle(
        field_name="type_of_bill",
        candidates=[_candidate()],
        registration_confidence=0.99,
        wrong_crop_suspected=True,
        deterministic_evidence={"FORMAT_VALID"},
        hard_validation_passed=True,
        structural_localization=StructuralLocalizationEvidence(
            evidence_type=StructuralLocalizationType.STRUCTURAL_LAYOUT_CONFIRMED,
            confidence=0.99,
            confirmed=True,
            reason_codes=("STRUCTURAL_REGION_CONFIRMED",),
            source="DYNAMIC_GEOMETRY:STRUCTURAL_LAYOUT",
        ),
    )
    assert EvidenceClass.E3 not in bundle.available_classes


def test_all_cms_and_ub_field_definitions_have_explicit_field_policy():
    policies = FieldPolicyRegistry.load()
    for family, filename in (
        ("CMS1500", "cms1500_v1.yaml"),
        ("UB04", "ub04_v1.yaml"),
    ):
        definitions = FieldDefinitionRegistry.load(ROOT / "config" / "field_definitions" / filename)
        for definition in definitions.for_family(family):
            assert policies.is_explicitly_configured(family, definition.field_name), (
                family,
                definition.field_name,
            )


def test_unknown_field_fails_closed_without_silently_blocking_claim_stp():
    policy = FieldPolicyRegistry.load().for_field("CMS1500", "new_unknown_field")
    assert not policy.configured
    assert not policy.blocks_stp
    decision = EvidenceDecisionService().decide(
        DecisionContext(
            field_name="new_unknown_field",
            document_family="CMS1500",
            criticality=CriticalityLevel.C1,
            candidates=[_candidate("VALUE")],
            deterministic_evidence={"FORMAT_VALID"},
            hard_validation_passed=True,
        )
    )
    assert decision.disposition is FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert decision.reason_codes == ["FIELD_POLICY_NOT_CONFIGURED"]
    assert not decision.blocks_stp


def test_balanced_policy_reachability_has_no_unexpected_unreachable_fields():
    evidence = EvidencePolicy.load(ROOT / "config" / "evidence_policies_phase8_4_balanced.yaml")
    fields = FieldPolicyRegistry.load()
    audit = PolicyReachabilityAudit(evidence, fields)
    reachable = audit.audit_field(
        "UB04",
        "type_of_bill",
        {EvidenceClass.E1, EvidenceClass.E3, EvidenceClass.E4},
    )
    explicit = audit.audit_field(
        "UB04",
        "federal_tax_no",
        {EvidenceClass.E3, EvidenceClass.E4},
        explicit_status=PolicyReachabilityStatus.HUMAN_REQUIRED_EXPLICIT.value,
    )
    audit.assert_no_unexpected_unreachable([reachable, explicit])
    assert reachable.status is PolicyReachabilityStatus.REACHABLE
    assert explicit.status is PolicyReachabilityStatus.HUMAN_REQUIRED_EXPLICIT


def test_unexpected_unreachable_policy_fails_architecture_gate():
    evidence = EvidencePolicy.load(ROOT / "config" / "evidence_policies_phase8_4_balanced.yaml")
    fields = FieldPolicyRegistry.load()
    result = PolicyReachabilityAudit(evidence, fields).audit_field(
        "CMS1500", "patient_name", {EvidenceClass.E1, EvidenceClass.E3}
    )
    with pytest.raises(ValueError, match="UNREACHABLE_POLICY:CMS1500.patient_name"):
        PolicyReachabilityAudit.assert_no_unexpected_unreachable([result])


def test_dob_service_date_relationship_is_truth_blind_e6():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="UB04",
        claim_values={"patient_dob": "1980-01-01"},
        service_lines=[{"service_date": "2026-08-01"}],
    )
    assert "DOB_SERVICE_DATE_CONSISTENT" in {item.evidence_type for item in result.evidence_items}


def test_legacy_decision_modules_have_no_production_callers():
    production_roots = [ROOT / "workers", ROOT / "apps"]
    forbidden = ("packages.hitl_optimization", "packages.stp_policy")
    hits = []
    for production_root in production_roots:
        for path in production_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if any(module in source for module in forbidden):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == []


def test_canonical_production_path_has_no_synthetic_legacy_claim_gate():
    for relative in (
        "packages/evidence_decision/service.py",
        "packages/claim_decision/service.py",
        "workers/validation/consumer.py",
        "workers/output_generation/consumer.py",
    ):
        assert "__legacy_claim_gate__" not in (ROOT / relative).read_text(encoding="utf-8")


def test_member_id_alias_satisfies_cms_required_field_presence():
    service = ClaimDecisionService.load()
    decisions = []
    for name in service.field_policy.required_fields("CMS1500"):
        actual = "member_id" if name == "insured_id_number" else name
        policy = service.field_policy.for_field("CMS1500", actual)
        decisions.append(
            FieldDecision(
                field_name=actual,
                selected_value="VALUE",
                disposition=FieldDisposition.AUTO_ACCEPTED,
                calibrated_probability=0.99,
                next_action=NextAction.NONE,
                policy_version="test",
                criticality=policy.criticality,
                required=policy.required,
                blocks_stp=policy.blocks_stp,
                requires_review_when_unresolved=policy.requires_review_when_unresolved,
                evidence_bundle=FieldEvidenceBundle(field_name=actual),
            )
        )
    result = service.decide(
        ClaimDecisionContext(
            claim_id="claim-1",
            document_family="CMS1500",
            field_decisions=decisions,
            policy_id=service.policy_id,
            policy_version=service.policy_version,
        )
    )
    assert "insured_id_number" not in result.blocking_unresolved_fields
