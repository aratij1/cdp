from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from dataclasses import field as datafield

from .consistency import ClaimConsistencyEngine, proof_candidate_ids, rank_candidates
from .models import ClaimGraph, ExtractionState, FieldNode
from .risk import RiskDecision, RiskScorer
from .telemetry import PerformanceProfile


@dataclass(frozen=True)
class ShadowFieldResult:
    field_name: str
    proposed_candidate_id: str | None
    proposed_value: str | None
    decision: RiskDecision
    extraction_state: str
    authority_state: str
    production_authority: bool = datafield(default=False, init=False)


@dataclass(frozen=True)
class ShadowClaimResult:
    claim_id: str
    fields: tuple[ShadowFieldResult, ...]
    deterministic_proofs: int
    deterministic_conflicts: int
    engineering_accepts: int
    engineering_reviews: int
    production_authority: bool = datafield(default=False, init=False)
    runtime_authority: bool = datafield(default=False, init=False)
    unknown_constraints: int = 0
    claim_decision: str = "REVIEW_SHADOW"


class CDP2ShadowEngine:
    """Pure shadow reasoning over candidate alternatives; no canonical writes."""

    def __init__(
        self, consistency: ClaimConsistencyEngine | None = None, risk: RiskScorer | None = None
    ) -> None:
        self.consistency = consistency or ClaimConsistencyEngine()
        self.risk = risk or RiskScorer()

    @staticmethod
    def _candidate_for(field: FieldNode, ordered_ids: list[str] | None = None):
        order = {key: i for i, key in enumerate(ordered_ids or [])}
        return (
            min(field.candidates, key=lambda c: order.get(c.candidate_id, len(order)))
            if field.candidates
            else None
        )

    def evaluate(
        self, claim: ClaimGraph, profiler: PerformanceProfile | None = None
    ) -> ShadowClaimResult:
        with profiler.measure("constraint_engine_ms") if profiler else nullcontext():
            consistency = self.consistency.evaluate(claim)
        field_results = []
        with profiler.measure("risk_scoring_ms") if profiler else nullcontext():
            for name, node in sorted(claim.fields.items()):
                proofs = proof_candidate_ids(consistency, name)
                conflicting = {
                    r.candidate_id
                    for r in consistency
                    if r.field_name == name and r.verdict == "CONFLICT"
                }
                ranked = rank_candidates(node.candidates, proofs)
                candidate = ranked[0] if ranked else None
                decision = self.risk.score(
                    node,
                    candidate,
                    deterministic_proof=candidate is not None and candidate.candidate_id in proofs,
                    deterministic_conflict=None in conflicting
                    or (candidate is not None and candidate.candidate_id in conflicting),
                )
                if not claim.form_identity_confirmed or claim.form_type not in {"CMS1500", "UB04"}:
                    decision = RiskDecision(
                        "REVIEW_SHADOW",
                        1.0,
                        (*decision.reasons, "FORM_IDENTITY_NOT_CONFIRMED"),
                        False,
                    )
                extraction = (
                    ExtractionState.EXTRACTED_CONFIDENT
                    if decision.extraction_supported
                    else ExtractionState.EXTRACTED_AMBIGUOUS
                    if candidate
                    else ExtractionState.EXTRACTION_FAILED
                )
                field_results.append(
                    ShadowFieldResult(
                        name,
                        candidate.candidate_id if candidate else None,
                        candidate.normalized_value or candidate.value if candidate else None,
                        decision,
                        extraction.value,
                        node.authority_state.value,
                    )
                )
        accepts = sum(f.decision.action == "ACCEPT_SHADOW" for f in field_results)
        return ShadowClaimResult(
            claim.claim_id,
            tuple(field_results),
            sum(r.verdict == "PROOF" for r in consistency),
            sum(r.verdict == "CONFLICT" for r in consistency),
            accepts,
            len(field_results) - accepts,
            unknown_constraints=sum(r.verdict == "UNKNOWN" for r in consistency),
            claim_decision="ACCEPT_SHADOW"
            if field_results
            and accepts == len(field_results)
            and not any(r.verdict == "CONFLICT" for r in consistency)
            else "REVIEW_SHADOW",
        )
