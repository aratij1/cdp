from __future__ import annotations

from dataclasses import dataclass

from .models import AuthorityState, Candidate, FieldNode


@dataclass(frozen=True)
class RiskDecision:
    action: str
    risk: float
    reasons: tuple[str, ...]


class RiskScorer:
    """Simple, explainable shadow risk scorer.

    This scorer cannot activate production authority. It exists to compare the
    field-centric path with claim-aware evidence on the same candidates.
    """

    def score(
        self,
        field: FieldNode,
        candidate: Candidate | None,
        *,
        deterministic_proof: bool = False,
        deterministic_conflict: bool = False,
    ) -> RiskDecision:
        if candidate is None:
            return RiskDecision("REVIEW_SHADOW", 1.0, ("NO_CANDIDATE",))
        if deterministic_conflict:
            return RiskDecision("REVIEW_SHADOW", 1.0, ("DETERMINISTIC_CONFLICT",))
        if field.authority_state == AuthorityState.AUTHORITATIVE_CONFLICT:
            return RiskDecision("REVIEW_SHADOW", 1.0, ("AUTHORITATIVE_CONFLICT",))

        confidence = max(
            (item.confidence or 0.0 for item in candidate.evidence),
            default=0.0,
        )
        risk = 1.0 - min(max(confidence, 0.0), 1.0)
        reasons: list[str] = [f"OCR_CONFIDENCE={confidence:.4f}"]

        if deterministic_proof:
            risk *= 0.35
            reasons.append("DETERMINISTIC_PROOF")
        if len(candidate.evidence) >= 2:
            independent = {
                evidence.independent_group
                for evidence in candidate.evidence
                if evidence.independent_group is not None
            }
            if len(independent) >= 2:
                risk *= 0.7
                reasons.append("PROVENANCE_SEPARATED_EVIDENCE")

        # Missing authority does not mean extraction failed; it remains visible
        # as a separate business/evidence state for downstream policy.
        if field.authority_state == AuthorityState.AUTHORITATIVE_NOT_AVAILABLE:
            reasons.append("AUTHORITY_NOT_AVAILABLE")

        action = "ACCEPT_SHADOW" if risk <= 0.08 else "REVIEW_SHADOW"
        return RiskDecision(action, round(risk, 6), tuple(reasons))
