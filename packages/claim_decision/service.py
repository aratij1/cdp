from __future__ import annotations

from pathlib import Path

import yaml

from packages.claim_decision.contracts import (
    ClaimDecision,
    ClaimDecisionContext,
    ClaimDisposition,
)
from packages.criticality import CriticalityLevel
from packages.evidence_decision import FieldDecision, FieldDisposition
from packages.field_policy import FieldPolicyRegistry

DEFAULT_CLAIM_POLICY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "claim_decision_policies.yaml"
)

_ACCEPTED = {
    FieldDisposition.AUTO_ACCEPTED,
    FieldDisposition.REFERENCE_CONFIRMED,
    FieldDisposition.HUMAN_CONFIRMED,
}


class ClaimDecisionService:
    """Sole authority for claim STP, field review, claim review, and rejection."""

    def __init__(
        self,
        config: dict,
        field_policy: FieldPolicyRegistry | None = None,
        configuration_identity: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self.policy_id = str(config["policy_id"])
        self.policy_version = str(config["version"])
        self.field_policy = field_policy or FieldPolicyRegistry.load()
        self.configuration_identity = configuration_identity or {
            "runtime_profile_id": "UNBOUND",
            "claim_policy_hash": "UNBOUND",
        }

    @classmethod
    def load(
        cls,
        path: str | Path = DEFAULT_CLAIM_POLICY_PATH,
        field_policy: FieldPolicyRegistry | None = None,
        configuration_identity: dict[str, str] | None = None,
    ) -> ClaimDecisionService:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(
            payload,
            field_policy=field_policy,
            configuration_identity=configuration_identity,
        )

    def decide(self, context: ClaimDecisionContext) -> ClaimDecision:
        if context.policy_id != self.policy_id:
            return self._result(
                context,
                ClaimDisposition.CLAIM_REVIEW_REQUIRED,
                reasons=["CLAIM_POLICY_ID_MISMATCH"],
            )
        if context.policy_version not in {None, self.policy_version}:
            return self._result(
                context,
                ClaimDisposition.CLAIM_REVIEW_REQUIRED,
                reasons=["CLAIM_POLICY_VERSION_MISMATCH"],
            )

        invalid_integrity = [
            reason
            for valid, reason in (
                (context.document_integrity_valid, "DOCUMENT_INTEGRITY_FAILED"),
                (context.template_integrity_valid, "TEMPLATE_INTEGRITY_FAILED"),
                (context.registration_integrity_valid, "REGISTRATION_INTEGRITY_FAILED"),
                (context.process_integrity_valid, "PROCESS_INTEGRITY_FAILED"),
            )
            if not valid
        ]
        if invalid_integrity:
            return self._result(
                context,
                ClaimDisposition.DOCUMENT_REJECTED,
                reasons=invalid_integrity,
            )

        present_fields = {
            self.field_policy.canonical_name(context.document_family, decision.field_name)
            for decision in context.field_decisions
        }
        missing_required = (
            [
                name
                for name in self.field_policy.required_fields(context.document_family)
                if name not in present_fields
            ]
            if context.enforce_configured_required_fields
            else []
        )
        if missing_required:
            return self._result(
                context,
                ClaimDisposition.FIELD_REVIEW_REQUIRED,
                extra_blocking=missing_required,
                reasons=["REQUIRED_FIELD_DECISIONS_MISSING"],
            )

        blocking: list[FieldDecision] = []
        nonblocking: list[FieldDecision] = []
        for decision in context.field_decisions:
            if decision.disposition in _ACCEPTED:
                continue
            blocks_stp = decision.blocks_stp
            if blocks_stp is None:
                blocks_stp = self.field_policy.for_field(
                    context.document_family,
                    decision.field_name,
                ).blocks_stp
            (blocking if blocks_stp else nonblocking).append(decision)

        contradictions = self._contradictions(context)
        if contradictions:
            return self._result(
                context,
                ClaimDisposition.CLAIM_REVIEW_REQUIRED,
                blocking=blocking,
                nonblocking=nonblocking,
                contradictions=contradictions,
                reasons=["UNRESOLVED_CLAIM_CONTRADICTION"],
            )

        coordinated = self._coordinated_blockers(context, blocking)
        if not context.structural_consistency_valid or coordinated:
            reasons = []
            if not context.structural_consistency_valid:
                reasons.append("CLAIM_STRUCTURE_INCONSISTENT")
            if coordinated:
                reasons.append("DEPENDENT_FIELD_GROUP_UNRESOLVED")
            return self._result(
                context,
                ClaimDisposition.CLAIM_REVIEW_REQUIRED,
                blocking=blocking,
                nonblocking=nonblocking,
                reasons=reasons,
            )

        if blocking:
            return self._result(
                context,
                ClaimDisposition.FIELD_REVIEW_REQUIRED,
                blocking=blocking,
                nonblocking=nonblocking,
                reasons=["BLOCKING_FIELDS_UNRESOLVED"],
            )

        safe = self._qualifies_safe(context)
        return self._result(
            context,
            ClaimDisposition.STP_SAFE if safe else ClaimDisposition.STP_STANDARD,
            nonblocking=nonblocking,
            reasons=[
                "ALL_BLOCKING_FIELDS_SAFELY_RESOLVED"
                if safe
                else "ALL_BLOCKING_FIELDS_RESOLVED_STANDARD"
            ],
        )

    def _qualifies_safe(self, context: ClaimDecisionContext) -> bool:
        critical_blocking: list[FieldDecision] = []
        for decision in context.field_decisions:
            policy = self.field_policy.for_field(
                context.document_family,
                decision.field_name,
            )
            level = decision.criticality or policy.criticality
            blocks = policy.blocks_stp if decision.blocks_stp is None else decision.blocks_stp
            if blocks and level in {CriticalityLevel.C2, CriticalityLevel.C3}:
                critical_blocking.append(decision)
        if not critical_blocking:
            return False
        return all(
            decision.disposition in _ACCEPTED
            and decision.evidence_bundle is not None
            and not decision.evidence_bundle.contradictions
            and not decision.evidence_bundle.missing_evidence_classes
            for decision in critical_blocking
        )

    @staticmethod
    def _coordinated_blockers(
        context: ClaimDecisionContext,
        blocking: list[FieldDecision],
    ) -> bool:
        blocked = {decision.field_name for decision in blocking}
        return any(len(blocked.intersection(group)) > 1 for group in context.dependent_field_groups)

    @staticmethod
    def _contradictions(context: ClaimDecisionContext) -> list[str]:
        descriptions = [item.evidence_type for item in context.contradictions]
        for decision in context.field_decisions:
            if decision.conflicting_evidence:
                descriptions.append(f"FIELD_CONFLICT:{decision.field_name}")
            if decision.evidence_bundle and decision.evidence_bundle.contradictions:
                descriptions.extend(
                    f"{decision.field_name}:{item.evidence_type}"
                    for item in decision.evidence_bundle.contradictions
                )
        return list(dict.fromkeys(descriptions))

    def _result(
        self,
        context: ClaimDecisionContext,
        disposition: ClaimDisposition,
        *,
        blocking: list[FieldDecision] | None = None,
        nonblocking: list[FieldDecision] | None = None,
        contradictions: list[str] | None = None,
        extra_blocking: list[str] | None = None,
        reasons: list[str],
    ) -> ClaimDecision:
        blocking = blocking or []
        nonblocking = nonblocking or []
        extra_blocking = extra_blocking or []
        critical = []
        for decision in blocking:
            policy = self.field_policy.for_field(
                context.document_family,
                decision.field_name,
            )
            if (decision.criticality or policy.criticality) in {
                CriticalityLevel.C2,
                CriticalityLevel.C3,
            }:
                critical.append(decision.field_name)
        for field_name in extra_blocking:
            if self.field_policy.for_field(
                context.document_family,
                field_name,
            ).criticality in {CriticalityLevel.C2, CriticalityLevel.C3}:
                critical.append(field_name)
        return ClaimDecision(
            claim_id=context.claim_id,
            disposition=disposition,
            blocking_unresolved_fields=[
                *[item.field_name for item in blocking],
                *extra_blocking,
            ],
            nonblocking_unresolved_fields=[item.field_name for item in nonblocking],
            critical_blockers=critical,
            contradictions=contradictions or [],
            reason_codes=list(dict.fromkeys(reasons)),
            stp_eligible=disposition
            in {
                ClaimDisposition.STP_SAFE,
                ClaimDisposition.STP_STANDARD,
            },
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            runtime_profile_id=self.configuration_identity["runtime_profile_id"],
            claim_policy_hash=self.configuration_identity["claim_policy_hash"],
        )
