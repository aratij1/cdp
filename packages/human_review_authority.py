"""The sole application-layer authority for creating field HITL events."""

from __future__ import annotations

from uuid import UUID, uuid5

from packages.events.envelope import EventEnvelope
from packages.events.topics import Topic

HITL_AUTHORITY = "CANONICAL_POST_EVIDENCE_DECISION_V1"
HITL_NAMESPACE = UUID("6b810c83-33d7-4a51-b14e-1998d5e30db1")


class CanonicalHITLAuthority:
    version = HITL_AUTHORITY

    def create_field_review_event(
        self,
        *,
        correlation_id,
        document_id,
        claim_id,
        pipeline_version: str,
        field,
        decision,
        required_policy: str,
    ) -> EventEnvelope:
        """Authorize HITL only for a completed canonical evidence decision."""
        if not getattr(decision, "policy_version", None):
            raise ValueError("HITL_REQUIRES_CANONICAL_EVIDENCE_DECISION")
        authorization_id = uuid5(
            HITL_NAMESPACE,
            f"{document_id}:{field.field_id}:{decision.policy_version}",
        )
        return EventEnvelope(
            event_type=Topic.HUMAN_REVIEW_REQUESTED.value,
            correlation_id=correlation_id,
            document_id=document_id,
            claim_id=claim_id,
            pipeline_version=pipeline_version,
            payload={
                "hitl_authority": self.version,
                "hitl_authorization_id": str(authorization_id),
                "field_id": str(field.field_id),
                "field_name": field.field_name,
                "page_number": field.page_number,
                "review_reason_codes": decision.reason_codes,
                "validation_errors": field.validation_reasons,
                "ocr_candidates": [candidate.raw_text for candidate in field.candidates],
                "candidate_evidence": [
                    candidate.model_dump(mode="json") for candidate in field.candidates
                ],
                "system_recommendation": decision.selected_value,
                "available_evidence": decision.available_evidence,
                "missing_evidence": decision.missing_evidence,
                "evidence_bundle": (
                    decision.evidence_bundle.model_dump(mode="json")
                    if decision.evidence_bundle else None
                ),
                "required_policy": required_policy,
                "evidence_versions": {"decision_policy": decision.policy_version},
            },
        )
