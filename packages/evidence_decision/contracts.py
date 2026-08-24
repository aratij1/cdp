from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from packages.candidate_reconciliation.contracts import EvidenceReference
from packages.criticality import CriticalityLevel
from packages.domain.common import DomainModel
from packages.evidence.models import FieldEvidenceBundle, StructuralLocalizationEvidence
from packages.evidence_router import ReferenceSourceState
from packages.ocr.contracts import OCRCandidate
from packages.route_registry import RouteLifecycle as OCRRouteState  # noqa: F401


class FieldDisposition(StrEnum):
    AUTO_ACCEPTED = "AUTO_ACCEPTED"
    REFERENCE_CONFIRMED = "REFERENCE_CONFIRMED"
    UNRESOLVED_NON_BLOCKING = "UNRESOLVED_NON_BLOCKING"
    ESCALATE = "ESCALATE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class NextAction(StrEnum):
    NONE = "NONE"
    PROPAGATE_EXISTING_EVIDENCE = "PROPAGATE_EXISTING_EVIDENCE"
    PRIMARY_OCR = "PRIMARY_OCR"
    CROP_RECOVERY = "CROP_RECOVERY"
    SECONDARY_OCR = "SECONDARY_OCR"
    REFERENCE_LOOKUP = "REFERENCE_LOOKUP"
    DETERMINISTIC_VALIDATION = "DETERMINISTIC_VALIDATION"
    CROSS_FIELD_RECONCILIATION = "CROSS_FIELD_RECONCILIATION"
    CLOUD_AI = "CLOUD_AI"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    REJECT_DOCUMENT = "REJECT_DOCUMENT"


class ReferenceEvidence(DomainModel):
    value: str | None = None
    verified: bool = False
    contradiction: bool = False
    source: str | None = None
    version: str | None = None
    reference_key: str | None = None
    matched_attributes: list[str] = Field(default_factory=list)
    match_scores: dict[str, float] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)
    snapshot_timestamp: datetime | None = None
    snapshot_checksum: str | None = None


class DecisionContext(DomainModel):
    field_id: str | None = None
    field_name: str
    document_family: str
    criticality: CriticalityLevel
    required: bool | None = None
    blocks_stp: bool | None = None
    requires_review_when_unresolved: bool | None = None
    candidates: list[OCRCandidate] = Field(default_factory=list)
    deterministic_evidence: set[str] = Field(default_factory=set)
    deterministic_evidence_version: str | None = None
    hard_validation_passed: bool = False
    registration_confidence: float | None = Field(default=None, ge=0, le=1)
    structural_evidence_source: str | None = None
    structural_localization: StructuralLocalizationEvidence | None = None
    wrong_crop_suspected: bool = False
    image_quality_score: float | None = Field(default=None, ge=0, le=1)
    reference: ReferenceEvidence | None = None
    reference_source_state: ReferenceSourceState = ReferenceSourceState.DISABLED
    cross_field_evidence: set[str] = Field(default_factory=set)
    propagatable_evidence: set[str] = Field(default_factory=set)
    cost_spent_usd: float = Field(default=0, ge=0)
    remaining_sla_ms: float | None = Field(default=None, ge=0)


class FieldDecision(DomainModel):
    field_id: str | None = None
    field_name: str
    selected_value: str | None = None
    disposition: FieldDisposition
    calibrated_probability: float = Field(ge=0, le=1)
    candidate_ids: list[str] = Field(default_factory=list)
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    conflicting_evidence: list[EvidenceReference] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    evidence_bundle: FieldEvidenceBundle | None = None
    available_evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    next_action: NextAction
    policy_version: str
    runtime_profile_id: str = "UNBOUND"
    evidence_policy_version: str = "UNBOUND"
    evidence_policy_hash: str = "UNBOUND"
    route_registry_version: str = "UNBOUND"
    route_registry_hash: str = "UNBOUND"
    route_mode: str = "UNBOUND"
    field_policy_version: str = "UNBOUND"
    field_policy_hash: str = "UNBOUND"
    criticality: CriticalityLevel | None = None
    required: bool | None = None
    blocks_stp: bool | None = None
    requires_review_when_unresolved: bool | None = None
