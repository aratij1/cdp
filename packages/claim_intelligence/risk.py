from __future__ import annotations

import math
from dataclasses import dataclass

from .models import AuthorityState, Candidate, FieldNode
from .provenance import complete, corroborated_alternatives


@dataclass(frozen=True)
class RiskDecision:
    action: str
    risk: float
    reasons: tuple[str, ...]
    extraction_supported: bool = False

    @property
    def risk_band(self) -> str:
        return "LOW" if self.risk <= 0.08 else "MEDIUM" if self.risk < 0.5 else "HIGH"


class RiskScorer:
    """Explainable shadow risk; OCR alone and missing authority cannot authorize acceptance."""

    def score(
        self,
        field: FieldNode,
        candidate: Candidate | None,
        *,
        deterministic_proof: bool = False,
        deterministic_conflict: bool = False,
    ) -> RiskDecision:
        if not isinstance(field.authority_state, AuthorityState):
            return RiskDecision("REVIEW_SHADOW", 1.0, ("UNKNOWN_AUTHORITY_STATE",))
        if candidate is None:
            return RiskDecision("REVIEW_SHADOW", 1.0, ("NO_CANDIDATE",))
        f = candidate.features
        if deterministic_conflict or f.contradiction_count or f.cross_field_consistency is False:
            return RiskDecision("REVIEW_SHADOW", 1.0, ("DETERMINISTIC_CONFLICT",))
        confidence = max((e.confidence or 0 for e in candidate.evidence), default=0)
        dimensions = [
            confidence,
            f.geometry_confidence,
            f.anchor_confidence,
            f.structural_confidence,
        ]
        if any(v is not None and (not math.isfinite(v) or not 0 <= v <= 1) for v in dimensions):
            return RiskDecision("REVIEW_SHADOW", 1.0, ("INVALID_EVIDENCE_FEATURE",))
        reasons = []
        if not candidate.evidence or not all(complete(e) for e in candidate.evidence):
            reasons.append("INCOMPLETE_PROVENANCE")
        if f.format_valid is not True:
            reasons.append("FORMAT_INVALID" if f.format_valid is False else "FORMAT_UNKNOWN")
        if any(v is None for v in dimensions[1:]):
            reasons.append("SPATIAL_OR_STRUCTURAL_EVIDENCE_UNKNOWN")
        values = {c.normalized_value or c.value for c in field.candidates}
        if len(values) > 1 and not deterministic_proof:
            reasons.append("CANDIDATE_AMBIGUITY")
        geometry, anchor, structure = (v or 0 for v in dimensions[1:])
        risk = (
            0.25 * (1 - confidence)
            + 0.3 * (1 - geometry)
            + 0.15 * (1 - anchor)
            + 0.3 * (1 - structure)
        )
        if deterministic_proof:
            risk *= 0.65
        if corroborated_alternatives(candidate, field.candidates):
            risk *= 0.8
        supported = not reasons and risk <= (0.06 if field.critical else 0.08)
        if reasons:
            risk = max(risk, 0.6)
        if supported:
            reasons.append("MULTISIGNAL_EXTRACTION_SUPPORTED")
        if field.authority_state == AuthorityState.AUTHORITATIVE_CONFLICT:
            return RiskDecision(
                "REVIEW_SHADOW", 1.0, (*reasons, "AUTHORITATIVE_CONFLICT"), supported
            )
        if field.authority_state == AuthorityState.AUTHORITATIVE_NOT_AVAILABLE:
            reasons.append("AUTHORITY_NOT_AVAILABLE")
            return RiskDecision("REVIEW_SHADOW", max(0.4, risk), tuple(reasons), supported)
        return RiskDecision(
            "ACCEPT_SHADOW" if supported else "REVIEW_SHADOW",
            round(risk, 6),
            tuple(reasons),
            supported,
        )
