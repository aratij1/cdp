"""Conditional capability scenarios using explicit review conclusions, not labels."""

from __future__ import annotations

from collections import Counter

from packages.claim_evidence.source_review import ReviewStatus

from .enablement import ClaimRequirements


def reviewed_scenario(
    claims: tuple[ClaimRequirements, ...],
    capabilities: frozenset[str],
    reviews: dict[str, tuple[ReviewStatus, ...]],
) -> dict:
    """All supplied outstanding field reviews must confirm a value to clear review.

    The caller must supply the complete required review set per claim from the
    governed claim matrix. This is scenario arithmetic, not acceptance policy.
    A capability flag alone never clears SOURCE_REVIEW.
    """
    ids = {c.claim_id for c in claims}
    if len(ids) != len(claims) or not set(reviews) <= ids:
        raise ValueError("INVALID_SCENARIO_CLAIM_SCOPE")
    if any(not isinstance(s, ReviewStatus) for states in reviews.values() for s in states):
        raise ValueError("INVALID_REVIEW_STATE")
    unlocked = 0
    remaining: Counter[str] = Counter()
    resolved = 0
    for claim in claims:
        blockers = set(claim.requirements - (capabilities - {"SOURCE_REVIEW"}))
        states = reviews.get(claim.claim_id, ())
        if (
            "SOURCE_REVIEW" in blockers
            and states
            and all(s == ReviewStatus.CONFIRMED_VALUE for s in states)
        ):
            blockers.remove("SOURCE_REVIEW")
            resolved += 1
        if claim.technical_blockers:
            blockers.add("TECHNICAL_BLOCKER")
        remaining.update(blockers)
        unlocked += not blockers
    return {
        "claims": len(claims),
        "potentially_stp_capable_claims": unlocked,
        "potential_stp": unlocked / len(claims) if claims else None,
        "potential_claim_hitl": 1 - unlocked / len(claims) if claims else None,
        "source_review_claims_resolved": resolved,
        "remaining_blocker_claim_counts": dict(sorted(remaining.items())),
        "achieved_production_stp": None,
        "production_qualified": False,
    }
