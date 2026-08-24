from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packages.claim_decision import ClaimDecisionService
from packages.criticality import CriticalityPolicy
from packages.evidence import EvidencePolicy
from packages.evidence_decision import EvidenceDecisionService
from packages.field_policy import FieldPolicyRegistry
from packages.reference_enrichment.evidence_adapter import ReferenceEvidenceService
from packages.route_registry import RouteRegistry
from packages.runtime_profile.contracts import (
    CANONICAL_RUNTIME_PROFILE_PATH,
    RuntimeDecisionProfile,
)


@dataclass(frozen=True)
class DecisionServiceBundle:
    profile: RuntimeDecisionProfile
    evidence_decision: EvidenceDecisionService
    claim_decision: ClaimDecisionService
    field_policy: FieldPolicyRegistry
    route_registry: RouteRegistry
    criticality: CriticalityPolicy
    reference_evidence: ReferenceEvidenceService


class DecisionServiceFactory:
    """The only normal constructor for runtime/evaluation decision services."""

    @classmethod
    def from_profile(
        cls,
        profile_or_path: RuntimeDecisionProfile | str | Path = CANONICAL_RUNTIME_PROFILE_PATH,
    ) -> DecisionServiceBundle:
        profile = (
            profile_or_path
            if isinstance(profile_or_path, RuntimeDecisionProfile)
            else RuntimeDecisionProfile.load(profile_or_path)
        )
        field_policy = FieldPolicyRegistry.load(profile.resolve(profile.field_policy_path))
        route_registry = RouteRegistry.load(profile.resolve(profile.route_registry_path))
        evidence_policy = EvidencePolicy.load(profile.resolve(profile.evidence_policy_path))
        identity = {
            **profile.decision_identity(),
            "evidence_policy_version": evidence_policy.version,
            "route_registry_version": route_registry.version,
            "field_policy_version": field_policy.version,
        }
        field_identity = {
            key: value for key, value in identity.items() if key != "claim_policy_hash"
        }
        claim_identity = {
            "runtime_profile_id": identity["runtime_profile_id"],
            "claim_policy_hash": identity["claim_policy_hash"],
        }
        return DecisionServiceBundle(
            profile=profile,
            evidence_decision=EvidenceDecisionService(
                evidence_policy=evidence_policy,
                field_policy=field_policy,
                route_mode=profile.route_mode,
                route_registry=route_registry,
                configuration_identity=field_identity,
            ),
            claim_decision=ClaimDecisionService.load(
                profile.resolve(profile.claim_policy_path),
                field_policy=field_policy,
                configuration_identity=claim_identity,
            ),
            field_policy=field_policy,
            route_registry=route_registry,
            criticality=CriticalityPolicy.load(profile.resolve(profile.criticality_config_path)),
            reference_evidence=ReferenceEvidenceService.from_config(
                profile.resolve(profile.reference_config_path)
            ),
        )
