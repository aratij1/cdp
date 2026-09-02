"""Human-in-the-loop review task and correction record."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, ObjectRef, new_id, utcnow
from packages.domain.enums import ReviewTaskStatus


class FieldCorrection(DomainModel):
    correction_id: UUID = Field(default_factory=new_id)
    reviewer: str
    corrected_at: datetime = Field(default_factory=utcnow)
    previous_value: str | None = None
    new_value: str
    reason: str


class ReviewTask(DomainModel):
    """A review task scoped to ONE failed field, not the whole claim."""

    task_id: UUID = Field(default_factory=new_id)
    claim_id: UUID
    document_id: UUID
    field_id: UUID
    field_name: str
    page_number: int
    crop_object: ObjectRef | None = None
    page_context_object: ObjectRef | None = None
    ocr_candidates: list[str] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    vlm_candidate: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    # Populated from evidence_decision's dynamic reason-code system, which is
    # a separate, broader vocabulary than the closed ReviewReasonCode enum
    # (that enum backs the unrelated classify_review_reasons() path) -- kept
    # as free-form strings so a legitimate-but-unlisted code (e.g.
    # FIELD_POLICY_NOT_CONFIGURED) never fails validation and silently drops
    # the review task.
    review_reason_codes: list[str] = Field(default_factory=list)
    candidate_evidence: list[dict[str, Any]] = Field(default_factory=list)
    reference_evidence: list[dict[str, Any]] = Field(default_factory=list)
    registration_evidence: dict[str, Any] = Field(default_factory=dict)
    system_recommendation: str | None = None
    policy_requirement: list[list[str]] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    reason_for_review: list[str] = Field(default_factory=list)
    claim_impact: str | None = None
    blocks_stp: bool = True
    single_blocker_claim: bool = False
    blocking_field_count: int = Field(default=0, ge=0)
    claim_unlock_value: float = Field(default=0, ge=0)
    claim_value_usd: float | None = Field(default=None, ge=0)
    sla_due_at: datetime | None = None
    route_id: str | None = None
    route_status: str | None = None
    evidence_versions: dict[str, str] = Field(default_factory=dict)
    status: ReviewTaskStatus = ReviewTaskStatus.OPEN
    assigned_to: str | None = None
    correction: FieldCorrection | None = None
    created_at: datetime = Field(default_factory=utcnow)
    version: int = Field(default=0, ge=0)
    claimed_at: datetime | None = None
