"""Claim-level evidence scenarios, never production qualification."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from math import ceil

from packages.claim_evidence.authoritative_snapshot import MatchStatus
from packages.claim_evidence.enablement import LookupResult

from .models import AuthorityState, FieldNode

CAPABILITIES = frozenset(
    {
        "MEMBER_AUTHORITY",
        "PROVIDER_AUTHORITY",
        "IDENTITY_AUTHORITY",
        "SOURCE_EVIDENCE",
        "SOURCE_REVIEW",
        "BUSINESS_POLICY",
        "REAL_CONFLICT",
    }
)


@dataclass(frozen=True)
class ClaimRequirements:
    claim_id: str
    technical_blockers: int
    requirements: frozenset[str]

    def __post_init__(self):
        if self.technical_blockers < 0 or self.requirements - CAPABILITIES:
            raise ValueError("INVALID_CLAIM_REQUIREMENTS")


def evidence_scenario(claims: tuple[ClaimRequirements, ...], available: frozenset[str]) -> dict:
    if not claims or len({c.claim_id for c in claims}) != len(claims):
        raise ValueError("EMPTY_OR_DUPLICATED_CLAIM_DENOMINATOR")
    if available - CAPABILITIES:
        raise ValueError("UNKNOWN_CAPABILITY")
    technical = sum(c.technical_blockers == 0 for c in claims)
    evidence = sum(not (c.requirements - available) for c in claims)
    possible = sum(c.technical_blockers == 0 and not (c.requirements - available) for c in claims)
    return {
        "claims": len(claims),
        "technically_capable_claims": technical,
        "evidence_capable_claims": evidence,
        "potentially_stp_capable_claims": possible,
        "potential_stp": possible / len(claims),
        "potential_claim_hitl": 1 - possible / len(claims),
        "remaining_blocker_categories": dict(
            Counter(k for c in claims for k in c.requirements - available)
        ),
        "assumption": "ALL_LISTED_REQUIREMENTS_SATISFIED_AND_INDEPENDENT_RELEASE_QUALIFICATION_PASSES",
        "achieved_production_stp": None,
        "production_qualified": False,
    }


def minimum_enablement(claims: tuple[ClaimRequirements, ...], target: float = 0.8) -> dict:
    if not 0 < target <= 1:
        raise ValueError("INVALID_TARGET")
    evidence_scenario(claims, frozenset())
    capabilities = sorted(set().union(*(c.requirements for c in claims)))
    required = ceil(target * len(claims))
    paths = []
    for size in range(len(capabilities) + 1):
        for choice in combinations(capabilities, size):
            result = evidence_scenario(claims, frozenset(choice))
            if result["potentially_stp_capable_claims"] >= required:
                paths.append({"capabilities": list(choice), **result})
        if paths:
            break
    return {
        "target_claims": required,
        "minimum_capability_count": len(paths[0]["capabilities"]) if paths else None,
        "minimum_paths": paths,
        "status": "SCENARIO_PATH_PROVEN" if paths else "TARGET_NOT_REACHABLE",
        "minimality": "EXHAUSTIVE_SUBSET_ENUMERATION",
        "production_qualified": False,
    }


def identity_review_state(
    node: FieldNode, result: LookupResult, *, authority_required: bool
) -> dict:
    """Report extraction separately; adapter agreement is never an ACCEPT action."""
    if node.name not in {
        "member_id",
        "subscriber_id",
        "provider_name",
        "patient_name",
        "insured_name",
        "npi",
    }:
        raise ValueError("NOT_AN_IDENTITY_FIELD")
    conflict = node.authority_state == AuthorityState.AUTHORITATIVE_CONFLICT or result.status in {
        MatchStatus.CONFLICT,
        MatchStatus.NO_MATCH,
    }
    state = (
        AuthorityState.AUTHORITATIVE_CONFLICT
        if conflict
        else AuthorityState.AUTHORITATIVE_MATCH
        if result.status == MatchStatus.MATCH and result.has_record_provenance
        else AuthorityState.AUTHORITATIVE_NOT_AVAILABLE
        if authority_required
        else AuthorityState.AUTHORITATIVE_NOT_REQUIRED
    )
    return {
        "field": node.name,
        "extraction_state": node.extraction_state.value,
        "authority_state": state.value,
        "provider_status": result.status.value,
        "authority_required": authority_required,
        "production_decision": "REVIEW_REQUIRED"
        if conflict or (authority_required and state != AuthorityState.AUTHORITATIVE_MATCH)
        else "EXISTING_ACCEPTANCE_POLICY_REQUIRED",
        "production_authority": False,
        "canonical_value_changed": False,
    }
