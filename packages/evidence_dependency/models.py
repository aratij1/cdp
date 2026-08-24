from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from packages.domain.common import DomainModel


class DependencyRelation(StrEnum):
    INDEPENDENT = "INDEPENDENT"
    PARTIALLY_INDEPENDENT = "PARTIALLY_INDEPENDENT"
    CORRELATED = "CORRELATED"
    UNKNOWN = "UNKNOWN"


class EvidenceDependencyResult(DomainModel):
    relation: DependencyRelation
    reasons: tuple[str, ...] = ()
    dependency_dimensions: dict[str, bool | float | str | None] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
