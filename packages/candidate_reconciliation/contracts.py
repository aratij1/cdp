from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from packages.domain.common import DomainModel


class Decision(StrEnum):
    ACCEPT = "ACCEPT"
    ESCALATE = "ESCALATE"
    ABSTAIN = "ABSTAIN"
    REVIEW = "REVIEW"


class EvidenceReference(DomainModel):
    evidence_type: str
    reference: str
    source: str
    reason_code: str


class ReconciliationResult(DomainModel):
    field_name: str
    selected_value: str | None
    candidate_ids: list[str]
    decision: Decision
    confidence: float = Field(ge=0, le=1)
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    conflicting_evidence: list[EvidenceReference] = Field(default_factory=list)
    rationale_codes: list[str] = Field(default_factory=list)
    calibration_model_version: str
