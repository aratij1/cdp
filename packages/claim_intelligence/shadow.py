from __future__ import annotations

from dataclasses import dataclass

from .consistency import ClaimConsistencyEngine, proof_candidate_ids, rank_candidates
from .models import ClaimGraph, ExtractionState, FieldNode
from .risk import RiskDecision, RiskScorer


@dataclass(frozen=True)
class ShadowFieldResult:
    field_name: str
    proposed_candidate_id: str | None
    proposed_value: str | None
    decision: RiskDecision
    extraction_state: str
    authority_state: str
    production_authority: bool = False


@dataclass(frozen=True)
class ShadowClaimResult:
    claim_id: str
    fields: tuple[ShadowFieldResult, ...]
    deterministic_proofs: int
    deterministic_conflicts: int
    engineering_accepts: int
    engineering_reviews: int
    production_authority: bool = False


class CDP2ShadowEngine:
    """Claim-aware shadow pipeline layered beside the governed CDP path."""

    def __init__(
        self,
        consistency: ClaimConsistencyEngine | None = None,
        risk: RiskScorer | None = None,
    ) -> None:
        self.consistency = consistency or ClaimConsistencyEngine()
        self.risk = risk or RiskScorer()

    @staticmethod
    def _candidate_for(field: FieldNode, ordered_ids: list[str] | None = None):
        if field.selected() is not None:
            return field.selected()
        candidates = list(field.candidates)
        if ordered_ids:
            order = {candidate_id: index for index, candidate_id in enumerate(ordered_ids)}
            candidates.sort(key=lambda candidate: order.get(candidate.candidate_id, len(order)))
        return candidates[0] if candidates else None

    def evaluate(self, claim: ClaimGraph) -> ShadowClaimResult:
        consistency = self.consistency.evaluate(claim)
        field_results: list[ShadowFieldResult] = []

        for field_name, field in sorted(claim.fields.items()):
            proof_ids = proof_candidate_ids(consistency, field_name)
            conflicts = {
                result.candidate_id
                for result in consistency
                if result.field_name == field_name
                and result.verdict == "CONFLICT"
                and result.candidate_id is not None
            }
            ranked = rank_candidates(field.candidates, proof_ids)
            candidate = self._candidate_for(
                field,
                [candidate.candidate_id for candidate in ranked],
            )
            decision = self.risk.score(
                field,
                candidate,
                deterministic_proof=candidate is not None and candidate.candidate_id in proof_ids,
                deterministic_conflict=candidate is not None and candidate.candidate_id in conflicts,
            )
            extraction_state = field.extraction_state
            if candidate is not None and extraction_state == ExtractionState.EXTRACTION_FAILED:
                extraction_state = ExtractionState.EXTRACTED_AMBIGUOUS
            field_results.append(
                ShadowFieldResult(
                    field_name=field_name,
                    proposed_candidate_id=candidate.candidate_id if candidate else None,
                    proposed_value=candidate.value if candidate else None,
                    decision=decision,
                    extraction_state=str(extraction_state),
                    authority_state=str(field.authority_state),
                )
            )

        proofs = sum(result.verdict == "PROOF" for result in consistency)
        conflicts = sum(result.verdict == "CONFLICT" for result in consistency)
        accepts = sum(result.decision.action == "ACCEPT_SHADOW" for result in field_results)
        reviews = len(field_results) - accepts
        return ShadowClaimResult(
            claim_id=claim.claim_id,
            fields=tuple(field_results),
            deterministic_proofs=proofs,
            deterministic_conflicts=conflicts,
            engineering_accepts=accepts,
            engineering_reviews=reviews,
        )
