"""SQLAlchemy 2.0 ORM models for the documents bounded context.

Shared by `apps.ingestion_api` (intake) and `workers.document_preparation`
(decode/preprocess) in Phase 1 — a deliberate simplification for a single
vertical slice; splitting into per-service schemas is a later-phase
concern, not a Phase 1 blocker.

Domain (Pydantic) <-> ORM mapping is explicit (see `mappers.py`), so the
canonical `packages.domain` models never depend on SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DocumentORM(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "sha256", "pipeline_version", "schema_version", name="uq_document_idempotency"
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    source_filename: Mapped[str] = mapped_column(String(512))
    detected_format: Mapped[str] = mapped_column(String(16))
    bundle_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="RECEIVED")
    original_object: Mapped[dict] = mapped_column(JSON)
    pipeline_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claim_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    pages: Mapped[list[PageORM]] = relationship(back_populates="document")


class PageORM(Base):
    __tablename__ = "pages"

    page_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.document_id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    width_px: Mapped[int] = mapped_column(Integer)
    height_px: Mapped[int] = mapped_column(Integer)
    compression: Mapped[str] = mapped_column(String(32))
    original_object: Mapped[dict] = mapped_column(JSON)
    extraction_object: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    thumbnail_object: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transforms: Mapped[list] = mapped_column(JSON, default=list)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    image_quality: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    document: Mapped[DocumentORM] = relationship(back_populates="pages")


class PageClassificationORM(Base):
    """Persists `packages.domain.classification.PageClassification` --
    the confidence/method/reason_codes detail behind `PageORM.role` that
    Phase 1's `PageORM.role` string alone can't carry."""

    __tablename__ = "page_classifications"

    classification_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.page_id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.document_id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column()
    method: Mapped[str] = mapped_column(String(32))
    template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    needs_review: Mapped[bool] = mapped_column(default=False)
    registration_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ExtractedFieldORM(Base):
    """Persists `packages.domain.extraction.ExtractedField`. Header fields
    have `service_line_number is None`; fields belonging to a service-line
    table row carry that row's 1-based `line_number` so the table structure
    survives without a separate `ServiceLine`/`Claim` persistence layer,
    which no worker assembles yet (see workers/standard_form_extraction/
    consumer.py)."""

    __tablename__ = "extracted_fields"

    field_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.document_id"), index=True)
    service_line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field_name: Mapped[str] = mapped_column(String(128))
    raw_value: Mapped[str] = mapped_column(String(2048))
    normalized_value: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    confidence: Mapped[float] = mapped_column()
    page_number: Mapped[int] = mapped_column(Integer)
    bounding_box: Mapped[dict] = mapped_column(JSON)
    extraction_method: Mapped[str] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    validation_reasons: Mapped[list] = mapped_column(JSON, default=list)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    is_critical: Mapped[bool] = mapped_column(default=False)
    disposition: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxORM(Base):
    __tablename__ = "outbox"

    outbox_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(128), index=True)
    envelope: Mapped[dict] = mapped_column(JSON)
    partition_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class AuditEventORM(Base):
    __tablename__ = "audit_events"

    audit_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor: Mapped[str] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
