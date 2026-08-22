from packages.claim_decision import (
    ClaimDecisionContext,
    ClaimDecisionService,
    ClaimDisposition,
)
from packages.evidence.models import EvidenceClass, EvidenceItem, FieldEvidenceBundle
from packages.evidence_decision import FieldDecision, FieldDisposition, NextAction


def _decision(service, family, field_name, disposition=FieldDisposition.AUTO_ACCEPTED):
    policy = service.field_policy.for_field(family, field_name)
    return FieldDecision(
        field_name=field_name,
        selected_value="VALUE",
        disposition=disposition,
        calibrated_probability=.99,
        next_action=(
            NextAction.NONE if disposition is FieldDisposition.AUTO_ACCEPTED
            else NextAction.HUMAN_REVIEW
        ),
        policy_version="evidence-policy-v2-candidate",
        criticality=policy.criticality,
        required=policy.required,
        blocks_stp=policy.blocks_stp,
        requires_review_when_unresolved=policy.requires_review_when_unresolved,
        evidence_bundle=FieldEvidenceBundle(
            field_name=field_name,
            policy_id=f"{family}:{field_name}",
            policy_version="evidence-policy-v2-candidate",
        ),
    )


def _context(service, family="CMS1500"):
    return ClaimDecisionContext(
        claim_id="claim-1",
        document_family=family,
        field_decisions=[
            _decision(service, family, name)
            for name in service.field_policy.required_fields(family)
        ],
        policy_id=service.policy_id,
        policy_version=service.policy_version,
    )


def test_all_explicit_blockers_safely_resolved_is_stp_safe():
    service = ClaimDecisionService.load()
    decision = service.decide(_context(service))
    assert decision.disposition is ClaimDisposition.STP_SAFE
    assert decision.stp_eligible


def test_one_isolated_blocker_requires_field_review():
    service = ClaimDecisionService.load()
    context = _context(service)
    context.field_decisions[0].disposition = FieldDisposition.HUMAN_REVIEW_REQUIRED
    context.field_decisions[0].next_action = NextAction.HUMAN_REVIEW
    decision = service.decide(context)
    assert decision.disposition is ClaimDisposition.FIELD_REVIEW_REQUIRED
    assert decision.blocking_unresolved_fields == [context.field_decisions[0].field_name]
    assert not decision.stp_eligible


def test_unresolved_nonblocking_field_does_not_prevent_stp():
    service = ClaimDecisionService.load()
    context = _context(service)
    context.field_decisions.append(_decision(
        service, "CMS1500", "patient_addr2",
        FieldDisposition.UNRESOLVED_NON_BLOCKING,
    ))
    decision = service.decide(context)
    assert decision.disposition is ClaimDisposition.STP_SAFE
    assert decision.nonblocking_unresolved_fields == ["patient_addr2"]


def test_claim_contradiction_requires_claim_review():
    service = ClaimDecisionService.load()
    context = _context(service)
    context.contradictions.append(EvidenceItem(
        evidence_class=EvidenceClass.E6,
        evidence_type="CLAIM_TOTAL_CONTRADICTION",
        evidence_family="claim-cross-field",
        source="test",
    ))
    decision = service.decide(context)
    assert decision.disposition is ClaimDisposition.CLAIM_REVIEW_REQUIRED
    assert decision.contradictions == ["CLAIM_TOTAL_CONTRADICTION"]


def test_missing_required_decisions_fail_closed_without_review_task_proxy():
    service = ClaimDecisionService.load()
    decision = service.decide(ClaimDecisionContext(
        claim_id="claim-1",
        document_family="CMS1500",
        policy_id=service.policy_id,
        policy_version=service.policy_version,
    ))
    assert decision.disposition is ClaimDisposition.FIELD_REVIEW_REQUIRED
    assert set(decision.blocking_unresolved_fields) == set(
        service.field_policy.required_fields("CMS1500")
    )


def test_invalid_document_integrity_is_rejected():
    service = ClaimDecisionService.load()
    context = _context(service)
    context.document_integrity_valid = False
    assert service.decide(context).disposition is ClaimDisposition.DOCUMENT_REJECTED


def test_identical_contexts_produce_identical_serialized_decisions():
    service = ClaimDecisionService.load()
    serialized = _context(service).model_dump(mode="json")
    runtime = service.decide(ClaimDecisionContext.model_validate(serialized))
    evaluation = service.decide(ClaimDecisionContext.model_validate(serialized))
    assert runtime.model_dump(mode="json") == evaluation.model_dump(mode="json")
