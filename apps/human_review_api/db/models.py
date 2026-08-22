"""SQLAlchemy ORM models for review tasks -- a separate table/bounded
context from `apps.ingestion_api.db` (review tasks reference claim/field
IDs by value, not by foreign key, since they may be created by a
different service than the one that owns the claim)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ReviewTaskORM(Base):
    __tablename__ = "review_tasks"

    task_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(index=True)
    field_id: Mapped[uuid.UUID]
    field_name: Mapped[str] = mapped_column(String(128))
    page_number: Mapped[int]
    crop_object: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    page_context_object: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ocr_candidates: Mapped[list] = mapped_column(JSON, default=list)
    vlm_candidate: Mapped[str | None] = mapped_column(String(512), nullable=True)
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    review_reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    candidate_evidence: Mapped[list] = mapped_column(JSON, default=list)
    reference_evidence: Mapped[list] = mapped_column(JSON, default=list)
    registration_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    system_recommendation: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    evidence_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # correction, denormalized onto the task row (one correction per task)
    correction_reviewer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correction_corrected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    correction_previous_value: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    correction_new_value: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class ReviewAuditORM(Base):
    """Append-only review event; values are represented only by hashes."""

    __tablename__ = "review_audit_events"

    audit_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(index=True)
    field_name: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(128))
    task_version: Mapped[int] = mapped_column(Integer)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
