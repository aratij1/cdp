"""Immutable experiment records and conservative promotion decisions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MetricSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    overall_accuracy: float = Field(ge=0, le=1)
    critical_field_accuracy: float = Field(ge=0, le=1)
    false_accept_rate: float = Field(ge=0, le=1)
    stp_rate: float = Field(ge=0, le=1)
    review_rate: float = Field(ge=0, le=1)
    p95_latency_ms: float = Field(ge=0)
    cost_per_page_usd: float = Field(ge=0)


class MetricDelta(MetricSnapshot):
    overall_accuracy: float
    critical_field_accuracy: float
    false_accept_rate: float
    stp_rate: float
    review_rate: float
    p95_latency_ms: float
    cost_per_page_usd: float


class ExperimentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hypothesis: str = Field(min_length=10)
    dataset_version: str = Field(min_length=1)
    code_commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_version: str = Field(min_length=1)
    baseline: MetricSnapshot
    candidate: MetricSnapshot
    delta: MetricDelta
    decision: Literal["PROMOTE", "REJECT", "NEEDS_MORE_DATA"]
    decision_reason: str = Field(min_length=3)

    @model_validator(mode="after")
    def validate_delta(self) -> "ExperimentRecord":
        for name in MetricSnapshot.model_fields:
            expected = getattr(self.candidate, name) - getattr(self.baseline, name)
            if abs(getattr(self.delta, name) - expected) > 1e-9:
                raise ValueError(f"delta.{name} does not equal candidate - baseline")
        return self


def decide(baseline: MetricSnapshot, candidate: MetricSnapshot, *, minimum_samples_met: bool) -> tuple[str, str]:
    """Apply the release invariant: accuracy gains may not buy unsafe accepts."""
    if not minimum_samples_met:
        return "NEEDS_MORE_DATA", "minimum governed sample size was not met"
    if candidate.false_accept_rate > baseline.false_accept_rate:
        return "REJECT", "false-accept rate regressed"
    if candidate.critical_field_accuracy < baseline.critical_field_accuracy:
        return "REJECT", "critical-field accuracy regressed"
    if candidate.overall_accuracy <= baseline.overall_accuracy and candidate.review_rate >= baseline.review_rate:
        return "REJECT", "no accuracy or review-rate improvement"
    return "PROMOTE", "safety invariants held and a governed outcome improved"


def deltas(baseline: MetricSnapshot, candidate: MetricSnapshot) -> MetricDelta:
    return MetricDelta(**{name: getattr(candidate, name) - getattr(baseline, name) for name in MetricSnapshot.model_fields})


def append_record(path: Path, record: ExperimentRecord) -> str:
    """Append one canonical JSON record; duplicate identifiers fail closed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            if line and json.loads(line).get("experiment_id") == record.experiment_id:
                raise ValueError(f"experiment_id already exists: {record.experiment_id}")
    encoded = json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded + "\n")
    return hashlib.sha256(encoded.encode()).hexdigest()
