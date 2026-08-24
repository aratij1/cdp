from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import Field

from packages.domain.common import DomainModel

from .contracts import CandidateObservation, CandidateRankingResult

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config/candidate_scoring_phase8_10.yaml"


class CandidateScoringPolicy(DomainModel):
    version: str
    weights: dict[str, float]
    engine_reliability: dict[str, dict[str, float]] = Field(default_factory=dict)
    preprocessing_reliability: dict[str, dict[str, float]] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG) -> CandidateScoringPolicy:
        return cls.model_validate(yaml.safe_load(Path(path).read_text("utf-8")))

    def reliability(self, table: dict[str, dict[str, float]], field: str, key: str) -> float:
        return table.get(field, {}).get(key, table.get("*", {}).get(key, .5))


def rank_candidates(candidates: list[CandidateObservation],
                    policy: CandidateScoringPolicy | None = None) -> CandidateRankingResult:
    selected_policy = policy or CandidateScoringPolicy.load()
    if not candidates:
        return CandidateRankingResult(ranking_version=selected_policy.version,
                                      reason_codes=("NO_CANDIDATES",))
    weights = selected_policy.weights
    scored: list[tuple[float, CandidateObservation, dict[str, float]]] = []
    for candidate in candidates:
        components = {
            "ocr": candidate.ocr_confidence,
            "localization": candidate.localization_confidence,
            "semantic": candidate.semantic_confidence,
            "deterministic": 1.0 if candidate.deterministic_valid else 0.0,
            "cross_field": candidate.cross_field_confidence,
            "engine": candidate.engine_reliability,
            "preprocessing": candidate.preprocessing_reliability,
            "dependency": candidate.dependency_quality,
        }
        score = sum(weights.get(name, 0) * value for name, value in components.items())
        scored.append((min(1.0, max(0.0, score)), candidate, components))
    ranked = sorted(scored, key=lambda item: (item[0], item[1].candidate_id), reverse=True)
    winner = ranked[0]
    reasons = ["VERSIONED_MULTI_SIGNAL_RANKING"]
    if not winner[1].deterministic_valid:
        reasons.append("WINNER_REQUIRES_REVIEW_DETERMINISTIC_INVALID")
    if len(ranked) > 1 and winner[0] - ranked[1][0] < .03:
        reasons.append("RANKING_MARGIN_LOW")
    return CandidateRankingResult(
        selected_candidate_id=winner[1].candidate_id,
        selected_value=winner[1].normalized_value or winner[1].selected_text,
        score=winner[0], ranked_candidate_ids=tuple(item[1].candidate_id for item in ranked),
        score_breakdown={item[1].candidate_id: item[2] for item in ranked},
        ranking_version=selected_policy.version, reason_codes=tuple(reasons),
    )
