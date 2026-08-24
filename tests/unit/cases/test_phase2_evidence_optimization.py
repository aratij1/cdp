from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence import EvidenceClass, FieldEvidenceBundle, build_evidence_bundle
from packages.evidence_decision import DecisionContext, EvidenceDecisionService, FieldDisposition
from packages.evidence_router import (
    EvidenceAcquisitionAction,
    EvidenceGapRouter,
    ReferenceSourceState,
)
from packages.field_policy import FieldPolicyRegistry
from packages.ocr.contracts import OCRCandidate

BOX = BoundingBox(x0=0, y0=0, x1=10, y1=5, image_width=10, image_height=5)


def candidate(engine: str, value: str, confidence: float = .96) -> OCRCandidate:
    return OCRCandidate(
        value=value, raw_value=value, engine=engine, model_name=engine,
        model_version="1", preprocessing_variant="recorded", raw_confidence=confidence,
        calibrated_confidence=None, bounding_box=BOX, latency_ms=1,
    )


def test_field_evidence_bundle_records_policy_candidate_and_structural_lineage():
    bundle = build_evidence_bundle(
        field_name="patient_dob",
        candidates=[candidate("paddleocr", "01011990")],
        registration_confidence=1.0,
        structural_evidence_source="SYNTHETIC_CANONICAL",
        wrong_crop_suspected=False,
        deterministic_evidence={"DATE_VALID"},
        hard_validation_passed=True,
    )
    assert isinstance(bundle, FieldEvidenceBundle)
    assert bundle.selected_candidate_id in bundle.candidate_ids
    structural = next(item for item in bundle.items if item.evidence_class is EvidenceClass.E3)
    assert structural.source == "SYNTHETIC_CANONICAL"
    assert structural.metadata["structural_source"] == "SYNTHETIC_CANONICAL"


def test_router_uses_propagation_then_e4_e6_e2_and_disables_unauthorized_e5():
    router = EvidenceGapRouter()
    requirement = (frozenset({"E2", "E3", "E4"}),)
    propagated = router.route(
        available={"E1", "E3", "E4"}, requirements=requirement,
        propagatable={"E2"}, confirmation_engine="rapidocr",
    )
    assert propagated.action is EvidenceAcquisitionAction.PROPAGATE_EXISTING_EVIDENCE
    deterministic = router.route(
        available={"E1", "E3"}, requirements=(frozenset({"E1", "E3", "E4", "E6"}),),
        confirmation_engine="rapidocr",
    )
    assert deterministic.action is EvidenceAcquisitionAction.DETERMINISTIC_VALIDATION
    unauthorized_reference = router.route(
        available={"E1", "E3"}, requirements=(frozenset({"E1", "E3", "E5"}),),
        reference_state=ReferenceSourceState.TEST_FIXTURE,
    )
    assert unauthorized_reference.action is EvidenceAcquisitionAction.HUMAN_REVIEW


def test_field_policy_makes_optional_address_nonblocking():
    policy = FieldPolicyRegistry.load().for_field("CMS1500", "patient_addr2")
    assert policy.criticality is CriticalityLevel.C0
    assert not policy.required
    assert not policy.blocks_stp
    assert not policy.requires_review_when_unresolved


def test_runtime_serialization_parity_uses_same_canonical_decision():
    context = DecisionContext(
        field_name="insured_id_number", document_family="CMS1500",
        criticality=CriticalityLevel.C3, required=True, blocks_stp=True,
        requires_review_when_unresolved=True,
        candidates=[
            candidate("paddleocr", "SYN0000042", .98),
            candidate("rapidocr", "SYN0000042", .99),
        ],
        deterministic_evidence={"FORMAT_VALID"}, hard_validation_passed=True,
        registration_confidence=1.0,
        structural_evidence_source="SYNTHETIC_CANONICAL",
    )
    runtime = EvidenceDecisionService().decide(context)
    evaluation = EvidenceDecisionService().decide(
        DecisionContext.model_validate(context.model_dump(mode="json"))
    )
    assert runtime.model_dump(mode="json") == evaluation.model_dump(mode="json")
    assert runtime.disposition is not FieldDisposition.AUTO_ACCEPTED
