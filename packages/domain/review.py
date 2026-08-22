"""Human-in-the-loop review task and correction record."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, ObjectRef, new_id, utcnow
from packages.domain.enums import ReviewReasonCode, ReviewTaskStatus


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
    vlm_candidate: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    review_reason_codes: list[ReviewReasonCode] = Field(default_factory=list)
    status: ReviewTaskStatus = ReviewTaskStatus.OPEN
    assigned_to: str | None = None
    correction: FieldCorrection | None = None
    created_at: datetime = Field(default_factory=utcnow)
    version: int = Field(default=0, ge=0)
    claimed_at: datetime | None = None
