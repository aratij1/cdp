"""Explicit domain (Pydantic) <-> ORM mapping. Keeps `packages.domain` free
of any SQLAlchemy dependency."""

from __future__ import annotations

from apps.ingestion_api.db.models import (
    AuditEventORM,
    DocumentORM,
    ExtractedFieldORM,
    OutboxORM,
    PageClassificationORM,
    PageORM,
)
from packages.domain.audit import AuditEvent
from packages.domain.classification import PageClassification
from packages.domain.common import BoundingBox, utcnow
from packages.domain.document import Document, Page, PageTransform
from packages.domain.enums import (
    BundleType,
    ClassificationMethod,
    CompressionType,
    DocumentStatus,
    ExtractionMethod,
    PageRole,
    SourceFormat,
    ValidationStatus,
)
from packages.domain.extraction import ExtractedField, FieldEvidence
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord


def document_to_orm(doc: Document) -> DocumentORM:
    return DocumentORM(
        document_id=doc.document_id,
        tenant_id=doc.tenant_id,
        correlation_id=doc.correlation_id,
        source_filename=doc.source_filename,
        detected_format=doc.detected_format.value,
        bundle_type=doc.bundle_type.value if doc.bundle_type else None,
        sha256=doc.sha256,
        page_count=doc.page_count,
        status=doc.status.value,
        original_object=doc.original_object.model_dump(mode="json"),
        pipeline_version=doc.pipeline_version,
        schema_version=doc.schema_version,
        received_at=doc.received_at,
        updated_at=doc.updated_at,
        claim_id=doc.claim_id,
    )


def orm_to_document(row: DocumentORM) -> Document:
    return Document(
        document_id=row.document_id,
        tenant_id=row.tenant_id,
        correlation_id=row.correlation_id,
        source_filename=row.source_filename,
        detected_format=SourceFormat(row.detected_format),
        bundle_type=BundleType(row.bundle_type) if row.bundle_type else None,
        sha256=row.sha256,
        page_count=row.page_count,
        status=DocumentStatus(row.status),
        original_object=row.original_object,
        pipeline_version=row.pipeline_version,
        schema_version=row.schema_version,
        received_at=row.received_at,
        updated_at=row.updated_at,
        claim_id=row.claim_id,
    )


def page_to_orm(page: Page) -> PageORM:
    return PageORM(
        page_id=page.page_id,
        document_id=page.document_id,
        page_number=page.page_number,
        width_px=page.width_px,
        height_px=page.height_px,
        compression=page.compression.value,
        original_object=page.original_object.model_dump(mode="json"),
        extraction_object=page.extraction_object.model_dump(mode="json")
        if page.extraction_object
        else None,
        thumbnail_object=page.thumbnail_object.model_dump(mode="json")
        if page.thumbnail_object
        else None,
        perceptual_hash=page.perceptual_hash,
        transforms=[t.model_dump(mode="json") for t in page.transforms],
        role=page.role,
        image_quality=page.image_quality.model_dump(mode="json") if page.image_quality else None,
    )


def orm_to_page(row: PageORM) -> Page:
    return Page(
        page_id=row.page_id,
        document_id=row.document_id,
        page_number=row.page_number,
        width_px=row.width_px,
        height_px=row.height_px,
        compression=CompressionType(row.compression),
        original_object=row.original_object,
        extraction_object=row.extraction_object,
        thumbnail_object=row.thumbnail_object,
        perceptual_hash=row.perceptual_hash,
        transforms=[PageTransform.model_validate(t) for t in row.transforms],
        role=row.role,
        image_quality=row.image_quality,
    )


def page_classification_to_orm(classification: PageClassification) -> PageClassificationORM:
    return PageClassificationORM(
        classification_id=classification.classification_id,
        page_id=classification.page_id,
        document_id=classification.document_id,
        role=classification.role.value,
        confidence=classification.confidence,
        method=classification.method.value,
        template_id=classification.template_id,
        template_version=classification.template_version,
        reason_codes=classification.reason_codes,
        classified_at=classification.classified_at,
        needs_review=classification.needs_review,
        registration_evidence=(
            classification.registration_evidence.model_dump(mode="json")
            if classification.registration_evidence
            else None
        ),
    )


def orm_to_page_classification(row: PageClassificationORM) -> PageClassification:
    return PageClassification(
        classification_id=row.classification_id,
        page_id=row.page_id,
        document_id=row.document_id,
        role=PageRole(row.role),
        confidence=row.confidence,
        method=ClassificationMethod(row.method),
        template_id=row.template_id,
        template_version=row.template_version,
        reason_codes=row.reason_codes,
        classified_at=row.classified_at,
        needs_review=row.needs_review,
        registration_evidence=row.registration_evidence,
    )


def extracted_field_to_orm(
    field: ExtractedField, document_id, service_line_number: int | None = None
) -> ExtractedFieldORM:
    return ExtractedFieldORM(
        field_id=field.field_id,
        document_id=document_id,
        service_line_number=service_line_number,
        field_name=field.field_name,
        raw_value=field.raw_value,
        normalized_value=field.normalized_value,
        confidence=field.confidence,
        page_number=field.page_number,
        bounding_box=field.bounding_box.model_dump(mode="json"),
        extraction_method=field.extraction_method.value,
        model_name=field.model_name,
        model_version=field.model_version,
        template_version=field.template_version,
        validation_status=field.validation_status.value,
        validation_reasons=field.validation_reasons,
        candidates=[candidate.model_dump(mode="json") for candidate in field.candidates],
        is_critical=field.is_critical,
        disposition=field.disposition,
        created_at=utcnow(),
    )


def orm_to_extracted_field(row: ExtractedFieldORM) -> ExtractedField:
    return ExtractedField(
        field_id=row.field_id,
        field_name=row.field_name,
        raw_value=row.raw_value,
        normalized_value=row.normalized_value,
        confidence=row.confidence,
        page_number=row.page_number,
        bounding_box=BoundingBox.model_validate(row.bounding_box),
        extraction_method=ExtractionMethod(row.extraction_method),
        model_name=row.model_name,
        model_version=row.model_version,
        template_version=row.template_version,
        validation_status=ValidationStatus(row.validation_status),
        validation_reasons=row.validation_reasons,
        candidates=[FieldEvidence.model_validate(candidate) for candidate in (row.candidates or [])],
        is_critical=row.is_critical,
        disposition=row.disposition,
    )


def outbox_to_orm(record: OutboxRecord) -> OutboxORM:
    return OutboxORM(
        outbox_id=record.outbox_id,
        topic=record.topic,
        envelope=record.envelope.model_dump(mode="json"),
        partition_key=record.partition_key,
        created_at=record.created_at,
        published_at=record.published_at,
        publish_attempts=record.publish_attempts,
        last_error=record.last_error,
    )


def orm_to_outbox(row: OutboxORM) -> OutboxRecord:
    return OutboxRecord(
        outbox_id=row.outbox_id,
        topic=row.topic,
        envelope=EventEnvelope.model_validate(row.envelope),
        partition_key=row.partition_key,
        created_at=row.created_at,
        published_at=row.published_at,
        publish_attempts=row.publish_attempts,
        last_error=row.last_error,
    )


def audit_event_to_orm(event: AuditEvent) -> AuditEventORM:
    return AuditEventORM(
        audit_id=event.audit_id,
        event_type=event.event_type.value,
        tenant_id=event.tenant_id,
        correlation_id=event.correlation_id,
        document_id=event.document_id,
        claim_id=event.claim_id,
        actor=event.actor,
        occurred_at=event.occurred_at,
        details=event.details,
    )
