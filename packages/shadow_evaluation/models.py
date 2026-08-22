from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from pydantic import ConfigDict, Field

from packages.domain.common import DomainModel


class CandidateSnapshot(DomainModel):
    """PHI-safe persisted identity for a candidate; raw values stay out of metrics/events."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_id: str
    value_sha256: str
    engine: str
    model_version: str

    @classmethod
    def from_candidate(cls, candidate) -> "CandidateSnapshot":
        from packages.evidence.builder import candidate_identifier

        return cls(
            candidate_id=candidate_identifier(candidate),
            value_sha256=sha256((candidate.value or "").encode()).hexdigest(),
            engine=candidate.engine,
            model_version=candidate.model_version,
        )


class ShadowObservation(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    field_name: str
    document_family: str
    route_id: str
    route_status: str
    production_candidate: CandidateSnapshot
    shadow_candidate: CandidateSnapshot | None = None
    agreement: bool | None = None
    runtime_latency_ms: float = Field(ge=0)
    additional_cpu_ms: float = Field(ge=0)
    additional_memory_bytes: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    execution_status: str
    truth_status: str = "UNAVAILABLE"
    truth_value_sha256: str | None = None
    shadow_correct: bool | None = None


class ShadowResult(DomainModel):
    canonical_candidate_id: str
    canonical_value: str | None
    canonical_unchanged: bool
    observation: ShadowObservation
