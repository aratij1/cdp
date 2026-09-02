"""Repository over the review_tasks table."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.human_review_api.db.mappers import orm_to_task, task_to_orm
from apps.human_review_api.db.models import ReviewAuditORM, ReviewTaskORM
from packages.domain.enums import ReviewTaskStatus
from packages.domain.review import ReviewTask


class ReviewTaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, task: ReviewTask) -> None:
        self._session.add(task_to_orm(task))
        self._session.flush()

    def get(self, task_id: UUID) -> ReviewTask | None:
        row = self._session.get(ReviewTaskORM, task_id)
        return orm_to_task(row) if row else None

    def get_for_field(self, document_id: UUID, field_id: UUID) -> ReviewTask | None:
        stmt = select(ReviewTaskORM).where(
            ReviewTaskORM.document_id == document_id,
            ReviewTaskORM.field_id == field_id,
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        return orm_to_task(row) if row else None

    def list_open(self, limit: int = 100) -> list[ReviewTask]:
        stmt = (
            select(ReviewTaskORM)
            .where(
                ReviewTaskORM.status.in_(
                    [
                        ReviewTaskStatus.OPEN.value,
                        ReviewTaskStatus.IN_PROGRESS.value,
                    ]
                )
            )
            .order_by(ReviewTaskORM.created_at.desc())
            .limit(limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_task(r) for r in rows]

    def list_all(self, limit: int = 100) -> list[ReviewTask]:
        stmt = (
            select(ReviewTaskORM)
            .order_by(ReviewTaskORM.created_at.desc())
            .limit(limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_task(r) for r in rows]

    def list_by_status(self, statuses: list[str], limit: int = 100) -> list[ReviewTask]:
        stmt = (
            select(ReviewTaskORM)
            .where(ReviewTaskORM.status.in_(statuses))
            .order_by(ReviewTaskORM.created_at.desc())
            .limit(limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_task(r) for r in rows]

    def list_for_claim(self, claim_id: UUID) -> list[ReviewTask]:
        stmt = select(ReviewTaskORM).where(ReviewTaskORM.claim_id == claim_id)
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_task(r) for r in rows]

    def claim(self, task_id: UUID, reviewer: str, expected_version: int) -> ReviewTask | None:
        claimed_at = datetime.now(UTC)
        result = self._session.execute(
            update(ReviewTaskORM)
            .where(ReviewTaskORM.task_id == task_id)
            .where(ReviewTaskORM.status == ReviewTaskStatus.OPEN.value)
            .where(ReviewTaskORM.version == expected_version)
            .values(
                status=ReviewTaskStatus.IN_PROGRESS.value,
                assigned_to=reviewer,
                claimed_at=claimed_at,
                version=expected_version + 1,
            )
        )
        if result.rowcount != 1:
            return None
        self._session.flush()
        return self.get(task_id)

    def save(self, task: ReviewTask, expected_version: int | None = None) -> ReviewTask:
        expected = task.version if expected_version is None else expected_version
        values = {
            "status": task.status.value,
            "assigned_to": task.assigned_to,
            "claimed_at": task.claimed_at,
            "version": expected + 1,
        }
        if task.correction is not None:
            values.update(
                {
                    "correction_reviewer": task.correction.reviewer,
                    "correction_corrected_at": task.correction.corrected_at,
                    "correction_previous_value": task.correction.previous_value,
                    "correction_new_value": task.correction.new_value,
                    "correction_reason": task.correction.reason,
                }
            )
        result = self._session.execute(
            update(ReviewTaskORM)
            .where(ReviewTaskORM.task_id == task.task_id)
            .where(ReviewTaskORM.version == expected)
            .values(**values)
        )
        if result.rowcount != 1:
            raise ConcurrentReviewUpdateError(f"review task {task.task_id} version conflict")
        self._session.flush()
        saved = self.get(task.task_id)
        if saved is None:  # pragma: no cover - guarded by successful update
            raise ValueError(f"review task {task.task_id} not found")
        return saved

    def append_audit(
        self,
        task: ReviewTask,
        event_type: str,
        actor: str,
        reason_code: str,
        decision_value: str | None = None,
    ) -> None:
        self._session.add(
            ReviewAuditORM(
                task_id=task.task_id,
                document_id=task.document_id,
                field_name=task.field_name,
                event_type=event_type,
                actor=actor,
                task_version=task.version,
                decision_hash=(
                    sha256(decision_value.encode()).hexdigest()
                    if decision_value is not None
                    else None
                ),
                reason_code=reason_code,
                occurred_at=datetime.now(UTC),
            )
        )
        self._session.flush()

    def audit_count(self, task_id: UUID) -> int:
        return len(
            self._session.execute(select(ReviewAuditORM).where(ReviewAuditORM.task_id == task_id))
            .scalars()
            .all()
        )

    def list_audit(self, task_id: UUID) -> list[ReviewAuditORM]:
        return list(
            self._session.execute(
                select(ReviewAuditORM)
                .where(ReviewAuditORM.task_id == task_id)
                .order_by(ReviewAuditORM.occurred_at)
            )
            .scalars()
            .all()
        )


class ConcurrentReviewUpdateError(RuntimeError):
    pass
