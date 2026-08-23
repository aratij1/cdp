"""Static production evidence-policy reachability validation."""

from __future__ import annotations

from enum import StrEnum

from packages.domain.common import DomainModel
from packages.evidence.models import EvidenceClass
from packages.evidence.policy import EvidencePolicy
from packages.field_policy import FieldPolicyRegistry


class PolicyReachabilityStatus(StrEnum):
    REACHABLE = "REACHABLE"
    HUMAN_REQUIRED_EXPLICIT = "HUMAN_REQUIRED_EXPLICIT"
    REFERENCE_REQUIRED_EXPLICIT = "REFERENCE_REQUIRED_EXPLICIT"
    UNREACHABLE_POLICY = "UNREACHABLE_POLICY"


class PolicyReachabilityResult(DomainModel):
    document_family: str
    field_name: str
    policy_id: str
    field_policy_configured: bool
    configured_combinations: tuple[tuple[str, ...], ...]
    available_evidence: tuple[str, ...]
    reachable_combinations: tuple[tuple[str, ...], ...]
    status: PolicyReachabilityStatus
    reason_codes: tuple[str, ...]


class PolicyReachabilityAudit:
    """Prove at least one policy combination can be built by enabled routes."""

    def __init__(self, evidence_policy: EvidencePolicy, field_policy: FieldPolicyRegistry) -> None:
        self.evidence_policy = evidence_policy
        self.field_policy = field_policy

    def audit_field(
        self,
        document_family: str,
        field_name: str,
        available: set[EvidenceClass | str],
        *,
        explicit_status: str | None = None,
    ) -> PolicyReachabilityResult:
        field = self.field_policy.for_field(document_family, field_name)
        policy_field_name = field.canonical_field_name
        options = self.evidence_policy.requirements(
            policy_field_name,
            field.criticality,
            document_family,
        )
        normalized = {
            item if isinstance(item, EvidenceClass) else EvidenceClass(item) for item in available
        }
        reachable = tuple(option for option in options if option <= normalized)
        reason_codes: list[str] = []
        explicitly_configured = self.field_policy.is_explicitly_configured(
            document_family,
            field_name,
        )
        if not explicitly_configured:
            status = PolicyReachabilityStatus.UNREACHABLE_POLICY
            reason_codes.append("FIELD_POLICY_NOT_CONFIGURED")
        elif reachable:
            status = PolicyReachabilityStatus.REACHABLE
            reason_codes.append("AT_LEAST_ONE_ACCEPTANCE_COMBINATION_REACHABLE")
        elif explicit_status in {
            PolicyReachabilityStatus.HUMAN_REQUIRED_EXPLICIT.value,
            PolicyReachabilityStatus.REFERENCE_REQUIRED_EXPLICIT.value,
        }:
            status = PolicyReachabilityStatus(explicit_status)
            reason_codes.append(explicit_status)
        else:
            status = PolicyReachabilityStatus.UNREACHABLE_POLICY
            reason_codes.append("NO_ACCEPTANCE_COMBINATION_REACHABLE")
        policy_id, _ = self.evidence_policy.field_spec(
            document_family,
            policy_field_name,
            field.criticality,
        )
        return PolicyReachabilityResult(
            document_family=document_family,
            field_name=field_name,
            policy_id=policy_id,
            field_policy_configured=explicitly_configured,
            configured_combinations=tuple(
                tuple(sorted(item.value for item in option)) for option in options
            ),
            available_evidence=tuple(sorted(item.value for item in normalized)),
            reachable_combinations=tuple(
                tuple(sorted(item.value for item in option)) for option in reachable
            ),
            status=status,
            reason_codes=tuple(reason_codes),
        )

    @staticmethod
    def assert_no_unexpected_unreachable(
        results: list[PolicyReachabilityResult],
    ) -> None:
        failed = [
            f"{item.document_family}.{item.field_name}"
            for item in results
            if item.status is PolicyReachabilityStatus.UNREACHABLE_POLICY
        ]
        if failed:
            raise ValueError("UNREACHABLE_POLICY:" + ",".join(sorted(failed)))
