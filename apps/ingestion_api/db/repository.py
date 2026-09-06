"""Repositories over the documents/pages/outbox/audit tables.

`SqlAlchemyOutboxRepository` implements `packages.events.outbox.
OutboxRepository` (an async Protocol) over a synchronous SQLAlchemy
`Session` — acceptable for Phase 1 (SQLite/local Postgres, low volume);
moving to SQLAlchemy's async engine (asyncpg) is a drop-in swap later and
does not change the Protocol.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.ingestion_api.db.mappers import (
    audit_event_to_orm,
    document_to_orm,
    extracted_field_to_orm,
    orm_to_document,
    orm_to_extracted_field,
    orm_to_outbox,
    orm_to_page,
    orm_to_page_classification,
    outbox_to_orm,
    page_classification_to_orm,
    page_to_orm,
)
from apps.ingestion_api.db.models import (
    DocumentORM,
    ExtractedFieldORM,
    OutboxORM,
    PageClassificationORM,
    PageORM,
)
from packages.domain.audit import AuditEvent
from packages.domain.classification import PageClassification
from packages.domain.document import Document, Page
from packages.domain.extraction import ExtractedField
from packages.events.outbox import OutboxRecord


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_idempotency_key(
        self, sha256: str, pipeline_version: str, schema_version: str
    ) -> Document | None:
        stmt = select(DocumentORM).where(
            DocumentORM.sha256 == sha256,
            DocumentORM.pipeline_version == pipeline_version,
            DocumentORM.schema_version == schema_version,
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        return orm_to_document(row) if row else None

    def get(self, document_id: UUID) -> Document | None:
        row = self._session.get(DocumentORM, document_id)
        return orm_to_document(row) if row else None

    def list_all(
        self, tenant_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[Document]:
        stmt = select(DocumentORM)
        if tenant_id:
            stmt = stmt.where(DocumentORM.tenant_id == tenant_id)
        stmt = stmt.order_by(DocumentORM.received_at.desc()).limit(limit).offset(offset)
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_document(r) for r in rows]

    def add(self, document: Document) -> None:
        self._session.add(document_to_orm(document))
        self._session.flush()

    def update(self, document: Document) -> None:
        row = self._session.get(DocumentORM, document.document_id)
        if row is None:
            raise ValueError(f"document {document.document_id} not found")
        row.status = document.status.value
        row.page_count = document.page_count
        row.bundle_type = document.bundle_type.value if document.bundle_type else None
        row.updated_at = document.updated_at
        row.claim_id = document.claim_id
        self._session.flush()

    def find_received_before(self, tenant_id: str, cutoff: datetime) -> list[Document]:
        """Implements `packages.security.retention.DocumentRetentionRepository`."""
        stmt = select(DocumentORM).where(
            DocumentORM.tenant_id == tenant_id, DocumentORM.received_at < cutoff
        )
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_document(r) for r in rows]

    def delete(self, document_id: UUID) -> None:
        """Implements `packages.security.retention.DocumentRetentionRepository`.
        Deletes dependent pages first -- there's no cascade configured on
        the `pages.document_id` foreign key."""
        page_rows = self._session.execute(
            select(PageORM).where(PageORM.document_id == document_id)
        ).scalars()
        for page_row in page_rows:
            self._session.delete(page_row)
        row = self._session.get(DocumentORM, document_id)
        if row is not None:
            self._session.delete(row)
        self._session.flush()


class PageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_all(self, pages: list[Page]) -> None:
        for page in pages:
            self._session.add(page_to_orm(page))
        self._session.flush()

    def list_for_document(self, document_id: UUID) -> list[Page]:
        stmt = (
            select(PageORM).where(PageORM.document_id == document_id).order_by(PageORM.page_number)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_page(r) for r in rows]

    def update_roles(self, roles_by_page_id: dict[UUID, str]) -> None:
        for page_id, role in roles_by_page_id.items():
            row = self._session.get(PageORM, page_id)
            if row is not None:
                row.role = role
        self._session.flush()


class PageClassificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_all(self, classifications: list[PageClassification]) -> None:
        for classification in classifications:
            self._session.add(page_classification_to_orm(classification))
        self._session.flush()

    def list_for_document(self, document_id: UUID) -> list[PageClassification]:
        stmt = (
            select(PageClassificationORM)
            .where(PageClassificationORM.document_id == document_id)
            .order_by(PageClassificationORM.classified_at)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_page_classification(r) for r in rows]


class ExtractedFieldRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_all(
        self,
        document_id: UUID,
        fields: list[ExtractedField],
        service_line_number: int | None = None,
    ) -> None:
        for field in fields:
            self._session.add(extracted_field_to_orm(field, document_id, service_line_number))
        self._session.flush()

    def list_for_document(self, document_id: UUID) -> list[ExtractedField]:
        stmt = (
            select(ExtractedFieldORM)
            .where(ExtractedFieldORM.document_id == document_id)
            .order_by(ExtractedFieldORM.page_number)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_extracted_field(r) for r in rows]


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: AuditEvent) -> None:
        self._session.add(audit_event_to_orm(event))
        self._session.flush()


class SqlAlchemyOutboxRepository:
    """Implements `packages.events.outbox.OutboxRepository`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def add(self, record: OutboxRecord) -> None:
        self._session.add(outbox_to_orm(record))
        self._session.flush()

    def add_sync(self, record: OutboxRecord) -> None:
        """Add an outbox record from a synchronous request transaction."""
        self._session.add(outbox_to_orm(record))
        self._session.flush()

    async def get_unpublished(self, limit: int = 100) -> list[OutboxRecord]:
        stmt = (
            select(OutboxORM)
            .where(OutboxORM.published_at.is_(None))
            .order_by(OutboxORM.created_at)
            .limit(limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [orm_to_outbox(r) for r in rows]

    async def mark_published(self, outbox_id: UUID) -> None:
        from packages.domain.common import utcnow

        row = self._session.get(OutboxORM, outbox_id)
        if row is not None:
            row.published_at = utcnow()
            self._session.flush()

    async def mark_failed(self, outbox_id: UUID, error: str) -> None:
        row = self._session.get(OutboxORM, outbox_id)
        if row is not None:
            row.publish_attempts += 1
            row.last_error = error[:2048]
            self._session.flush()


class PollingOutboxRepository:
    """Implements `packages.events.outbox.OutboxRepository` for the
    standalone `OutboxRelay` background task: unlike
    `SqlAlchemyOutboxRepository` (which shares one session/transaction with
    a request so a domain write and its outbox row commit atomically),
    this opens and commits its own short-lived session per call, since the
    relay polls independently of any request transaction."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def add(self, record: OutboxRecord) -> None:
        with self._session_factory() as session:
            session.add(outbox_to_orm(record))
            session.commit()

    async def get_unpublished(self, limit: int = 100) -> list[OutboxRecord]:
        with self._session_factory() as session:
            stmt = (
                select(OutboxORM)
                .where(OutboxORM.published_at.is_(None))
                .order_by(OutboxORM.created_at)
                .limit(limit)
            )
            rows = session.execute(stmt).scalars().all()
            return [orm_to_outbox(r) for r in rows]

    async def mark_published(self, outbox_id: UUID) -> None:
        from packages.domain.common import utcnow

        with self._session_factory() as session:
            row = session.get(OutboxORM, outbox_id)
            if row is not None:
                row.published_at = utcnow()
                session.commit()

    async def mark_failed(self, outbox_id: UUID, error: str) -> None:
        with self._session_factory() as session:
            row = session.get(OutboxORM, outbox_id)
            if row is not None:
                row.publish_attempts += 1
                row.last_error = error[:2048]
                session.commit()
