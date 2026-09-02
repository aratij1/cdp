"""API-facing request/response models -- separate from the internal
`packages.domain.review.ReviewTask` so the wire contract can evolve
independently."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from packages.domain.review import ReviewTask


class ReviewTaskSummary(BaseModel):
    task_id: UUID
    claim_id: UUID
    document_id: UUID
    field_name: str
    status: str
    created_at: datetime
    version: int
    assigned_to: str | None = None
    patient_name: str | None = None

    @classmethod
    def from_domain(cls, task: ReviewTask, patient_name: str | None = None) -> ReviewTaskSummary:
        return cls(
            task_id=task.task_id,
            claim_id=task.claim_id,
            document_id=task.document_id,
            field_name=task.field_name,
            status=task.status.value,
            created_at=task.created_at,
            version=task.version,
            assigned_to=task.assigned_to,
            patient_name=patient_name,
        )


class ReviewTaskDetail(BaseModel):
    task_id: UUID
    claim_id: UUID
    document_id: UUID
    field_name: str
    page_number: int
    crop_signed_url: str | None
    page_context_signed_url: str | None
    ocr_candidates: list[str]
    vlm_candidate: str | None
    validation_errors: list[str]
    review_reason_codes: list[str]
    candidate_evidence: list[dict[str, Any]]
    reference_evidence: list[dict[str, Any]]
    registration_evidence: dict[str, Any]
    system_recommendation: str | None
    evidence_versions: dict[str, str]
    status: str
    version: int
    assigned_to: str | None
    patient_name: str | None = None

    @classmethod
    def from_domain(
        cls,
        task: ReviewTask,
        crop_signed_url: str | None,
        page_context_signed_url: str | None,
        patient_name: str | None = None,
    ) -> ReviewTaskDetail:
        return cls(
            task_id=task.task_id,
            claim_id=task.claim_id,
            document_id=task.document_id,
            field_name=task.field_name,
            page_number=task.page_number,
            crop_signed_url=crop_signed_url,
            page_context_signed_url=page_context_signed_url,
            ocr_candidates=task.ocr_candidates,
            vlm_candidate=task.vlm_candidate,
            validation_errors=task.validation_errors,
            review_reason_codes=list(task.review_reason_codes),
            candidate_evidence=task.candidate_evidence,
            reference_evidence=task.reference_evidence,
            registration_evidence=task.registration_evidence,
            system_recommendation=task.system_recommendation,
            evidence_versions=task.evidence_versions,
            status=task.status.value,
            version=task.version,
            assigned_to=task.assigned_to,
            patient_name=patient_name,
        )


class CorrectionRequest(BaseModel):
    new_value: str
    reason: str
    expected_version: int | None = Field(default=None, ge=0)


class RejectionRequest(BaseModel):
    reason: str
    expected_version: int | None = Field(default=None, ge=0)


class ClaimRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=0)


class ReviewAuditSummary(BaseModel):
    event_type: str
    actor: str
    task_version: int
    decision_hash: str | None
    reason_code: str
    occurred_at: datetime


class CorrectionPromotionCandidate(BaseModel):
    field_name: str
    observed: str
    corrected: str
    occurrences: int
    distinct_documents: int
    distinct_reviewers: int
    agreement_ratio: float
    promotion_eligible: bool
