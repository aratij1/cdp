"""Domain (Pydantic) <-> ORM mapping for review tasks."""

from __future__ import annotations

from apps.human_review_api.db.models import ReviewTaskORM
from packages.domain.enums import ReviewTaskStatus
from packages.domain.review import FieldCorrection, ReviewTask


def task_to_orm(task: ReviewTask) -> ReviewTaskORM:
    return ReviewTaskORM(
        task_id=task.task_id,
        claim_id=task.claim_id,
        document_id=task.document_id,
        field_id=task.field_id,
        field_name=task.field_name,
        page_number=task.page_number,
        crop_object=task.crop_object.model_dump(mode="json") if task.crop_object else None,
        page_context_object=(
            task.page_context_object.model_dump(mode="json") if task.page_context_object else None
        ),
        ocr_candidates=task.ocr_candidates,
        vlm_candidate=task.vlm_candidate,
        validation_errors=task.validation_errors,
        review_reason_codes=[item.value for item in task.review_reason_codes],
        candidate_evidence=task.candidate_evidence,
        reference_evidence=task.reference_evidence,
        registration_evidence=task.registration_evidence,
        system_recommendation=task.system_recommendation,
        evidence_versions=task.evidence_versions,
        claim_impact=task.claim_impact,
        blocks_stp=task.blocks_stp,
        single_blocker_claim=task.single_blocker_claim,
        blocking_field_count=task.blocking_field_count,
        claim_unlock_value=task.claim_unlock_value,
        status=task.status.value,
        assigned_to=task.assigned_to,
        created_at=task.created_at,
        correction_reviewer=task.correction.reviewer if task.correction else None,
        correction_corrected_at=task.correction.corrected_at if task.correction else None,
        correction_previous_value=task.correction.previous_value if task.correction else None,
        correction_new_value=task.correction.new_value if task.correction else None,
        correction_reason=task.correction.reason if task.correction else None,
        version=task.version,
        claimed_at=task.claimed_at,
    )


def orm_to_task(row: ReviewTaskORM) -> ReviewTask:
    correction = None
    if row.correction_reviewer is not None:
        correction = FieldCorrection(
            reviewer=row.correction_reviewer,
            corrected_at=row.correction_corrected_at,
            previous_value=row.correction_previous_value,
            new_value=row.correction_new_value,
            reason=row.correction_reason,
        )
    return ReviewTask(
        task_id=row.task_id,
        claim_id=row.claim_id,
        document_id=row.document_id,
        field_id=row.field_id,
        field_name=row.field_name,
        page_number=row.page_number,
        crop_object=row.crop_object,
        page_context_object=row.page_context_object,
        ocr_candidates=row.ocr_candidates,
        vlm_candidate=row.vlm_candidate,
        validation_errors=row.validation_errors,
        review_reason_codes=row.review_reason_codes or [],
        candidate_evidence=row.candidate_evidence or [],
        reference_evidence=row.reference_evidence or [],
        registration_evidence=row.registration_evidence or {},
        system_recommendation=row.system_recommendation,
        evidence_versions=row.evidence_versions or {},
        claim_impact=row.claim_impact,
        blocks_stp=row.blocks_stp,
        single_blocker_claim=row.single_blocker_claim,
        blocking_field_count=row.blocking_field_count,
        claim_unlock_value=row.claim_unlock_value,
        status=ReviewTaskStatus(row.status),
        assigned_to=row.assigned_to,
        correction=correction,
        created_at=row.created_at,
        version=row.version,
        claimed_at=row.claimed_at,
    )
