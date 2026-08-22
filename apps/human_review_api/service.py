"""Review workflow: approve (with a corrected value) or reject exactly one
failed field. Reviews only the failed field, never the whole claim -- the
caller supplies one `ReviewTask`, not a `Claim`.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.domain.audit import AuditEvent
from packages.domain.common import utcnow
from packages.domain.enums import AuditEventType, ReviewTaskStatus
from packages.domain.review import FieldCorrection, ReviewTask
from packages.retraining import CorrectionSink, correction_example


class ReviewTaskNotOpenError(ValueError):
    pass


class InvalidCorrectionError(ValueError):
    pass


@dataclass
class ReviewDecision:
    task: ReviewTask
    audit_event: AuditEvent


class ReviewService:
    def __init__(self, validator=None, correction_sink: CorrectionSink | None = None) -> None:
        self._validator = validator
        self._correction_sink = correction_sink

    def submit_correction(
        self, task: ReviewTask, reviewer: str, new_value: str, reason: str, tenant_id: str
    ) -> ReviewDecision:
        if task.status not in {ReviewTaskStatus.OPEN, ReviewTaskStatus.IN_PROGRESS}:
            raise ReviewTaskNotOpenError(
                f"task {task.task_id} is not reviewable (status={task.status})"
            )
        if task.status == ReviewTaskStatus.IN_PROGRESS and task.assigned_to != reviewer:
            raise ReviewTaskNotOpenError(f"task {task.task_id} is assigned to another reviewer")
        if self._validator is not None and not self._validator(task.field_name, new_value):
            raise InvalidCorrectionError(
                f"correction for {task.field_name} failed deterministic validation"
            )

        previous_value = task.ocr_candidates[0] if task.ocr_candidates else None
        correction = FieldCorrection(
            reviewer=reviewer,
            corrected_at=utcnow(),
            previous_value=previous_value,
            new_value=new_value,
            reason=reason,
        )
        updated = task.model_copy(
            update={
                "status": ReviewTaskStatus.APPROVED,
                "correction": correction,
                "assigned_to": reviewer,
            }
        )
        audit_event = AuditEvent(
            event_type=AuditEventType.FIELD_CORRECTED,
            tenant_id=tenant_id,
            correlation_id=task.claim_id,
            document_id=task.document_id,
            claim_id=task.claim_id,
            actor=f"user:{reviewer}",
            details={"field_name": task.field_name, "reason": reason},
        )
        if self._correction_sink is not None:
            self._correction_sink.append(
                correction_example(
                    str(task.document_id),
                    task.field_name,
                    previous_value,
                    new_value,
                    task.crop_object.uri if task.crop_object else None,
                    reviewer,
                    tenant_id,
                    reason,
                )
            )
        return ReviewDecision(task=updated, audit_event=audit_event)

    def submit_rejection(
        self, task: ReviewTask, reviewer: str, reason: str, tenant_id: str
    ) -> ReviewDecision:
        if task.status not in {ReviewTaskStatus.OPEN, ReviewTaskStatus.IN_PROGRESS}:
            raise ReviewTaskNotOpenError(
                f"task {task.task_id} is not reviewable (status={task.status})"
            )
        if task.status == ReviewTaskStatus.IN_PROGRESS and task.assigned_to != reviewer:
            raise ReviewTaskNotOpenError(f"task {task.task_id} is assigned to another reviewer")

        updated = task.model_copy(
            update={"status": ReviewTaskStatus.REJECTED, "assigned_to": reviewer}
        )
        audit_event = AuditEvent(
            event_type=AuditEventType.REVIEW_DECIDED,
            tenant_id=tenant_id,
            correlation_id=task.claim_id,
            document_id=task.document_id,
            claim_id=task.claim_id,
            actor=f"user:{reviewer}",
            details={"field_name": task.field_name, "decision": "rejected", "reason": reason},
        )
        return ReviewDecision(task=updated, audit_event=audit_event)
