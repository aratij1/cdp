from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from packages.domain.common import DomainModel
from packages.evidence.models import EvidenceItem
from packages.evidence_decision import FieldDecision


class ClaimDisposition(StrEnum):
    STP_SAFE = "STP_SAFE"
    STP_STANDARD = "STP_STANDARD"
    FIELD_REVIEW_REQUIRED = "FIELD_REVIEW_REQUIRED"
    CLAIM_REVIEW_REQUIRED = "CLAIM_REVIEW_REQUIRED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"


class ClaimDecisionContext(DomainModel):
    claim_id: str
    document_family: str
    field_decisions: list[FieldDecision] = Field(default_factory=list)
    claim_evidence: list[EvidenceItem] = Field(default_factory=list)
    contradictions: list[EvidenceItem] = Field(default_factory=list)
    policy_id: str = "claim-stp"
    policy_version: str | None = None
    document_integrity_valid: bool = True
    template_integrity_valid: bool = True
    registration_integrity_valid: bool = True
    process_integrity_valid: bool = True
    structural_consistency_valid: bool = True
    dependent_field_groups: list[list[str]] = Field(default_factory=list)
    enforce_configured_required_fields: bool = True


class ClaimDecision(DomainModel):
    claim_id: str
    disposition: ClaimDisposition
    blocking_unresolved_fields: list[str] = Field(default_factory=list)
    nonblocking_unresolved_fields: list[str] = Field(default_factory=list)
    critical_blockers: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    stp_eligible: bool
    policy_id: str
    policy_version: str
