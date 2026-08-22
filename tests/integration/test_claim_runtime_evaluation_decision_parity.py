from packages.claim_decision import ClaimDecisionContext, ClaimDecisionService
from packages.evidence.models import FieldEvidenceBundle
from packages.evidence_decision import FieldDecision, FieldDisposition, NextAction


def test_identical_runtime_and_evaluation_contexts_produce_identical_claim_decisions():
    service = ClaimDecisionService.load()
    fields = []
    for field_name in service.field_policy.required_fields("CMS1500"):
        policy = service.field_policy.for_field("CMS1500", field_name)
        fields.append(FieldDecision(
            field_name=field_name,
            selected_value="TEST",
            disposition=FieldDisposition.AUTO_ACCEPTED,
            calibrated_probability=.99,
            next_action=NextAction.NONE,
            policy_version="evidence-policy-v2-candidate",
            criticality=policy.criticality,
            required=policy.required,
            blocks_stp=policy.blocks_stp,
            requires_review_when_unresolved=policy.requires_review_when_unresolved,
            evidence_bundle=FieldEvidenceBundle(
                field_name=field_name,
                policy_id=f"CMS1500:{field_name}",
                policy_version="evidence-policy-v2-candidate",
            ),
        ))
    source = ClaimDecisionContext(
        claim_id="parity-claim",
        document_family="CMS1500",
        field_decisions=fields,
        policy_id=service.policy_id,
        policy_version=service.policy_version,
    ).model_dump(mode="json")
    runtime_context = ClaimDecisionContext.model_validate(source)
    evaluation_context = ClaimDecisionContext.model_validate(source)
    assert service.decide(runtime_context).model_dump(mode="json") == service.decide(
        evaluation_context
    ).model_dump(mode="json")
