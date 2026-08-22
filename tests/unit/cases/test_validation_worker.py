"""Unit tests for Validation Worker: consumes extraction.completed, runs
ValidationEngine, updates Document status to VALIDATED or NEEDS_REVIEW, and
outboxes claim.validated or human.review.requested.
"""

from uuid import uuid4

import pytest

from apps.ingestion_api.db.repository import (
    DocumentRepository,
    ExtractedFieldRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from packages.domain.common import BoundingBox, ObjectRef
from packages.domain.document import Document
from packages.domain.enums import DocumentStatus, ExtractionMethod, SourceFormat
from packages.domain.extraction import ExtractedField
from packages.events.bus import InMemoryEventBus
from packages.events.envelope import EventEnvelope
from packages.events.topics import Topic
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from workers.validation.consumer import ValidationWorker, registration_confidence_from_evidence


def test_registration_confidence_uses_measured_accepted_evidence_and_fails_closed():
    assert registration_confidence_from_evidence(None) == 0
    assert registration_confidence_from_evidence({"accepted": False, "alignment_confidence": .99}) == 0
    assert registration_confidence_from_evidence({"accepted": True, "alignment_confidence": .83}) == .83


def _document() -> Document:
    return Document(
        tenant_id="tenant-1",
        source_filename="claim.tiff",
        detected_format=SourceFormat.TIFF,
        sha256="d" * 64,
        original_object=ObjectRef(bucket="idp-documents", key="documents/aa/bb/x.tiff"),
        pipeline_version="0.1.0",
        schema_version="1.0",
        status=DocumentStatus.VALIDATING,
    )


def _field(field_name: str, value: str, confidence: float = 0.99) -> ExtractedField:
    from packages.domain.extraction import FieldEvidence
    return ExtractedField(
        field_name=field_name,
        raw_value=value,
        normalized_value=value,
        confidence=confidence,
        page_number=1,
        bounding_box=BoundingBox(x0=0.1, y0=0.1, x1=0.2, y1=0.2, image_width=1000, image_height=1000),
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
        candidates=[
            FieldEvidence(source=ExtractionMethod.REGIONAL_PADDLEOCR, raw_text=value, confidence=confidence),
            FieldEvidence(source=ExtractionMethod.TEMPLATE_RULES, raw_text=value, confidence=confidence),
        ]
    )


@pytest.mark.asyncio
async def test_validation_worker_does_not_bypass_critical_evidence_policy():
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()

    with session_factory() as session:
        doc_repo = DocumentRepository(session)
        field_repo = ExtractedFieldRepository(session)
        doc_repo.add(doc)

        fields = [
            _field("insured_id_number", "ID1234567"),
            _field("patient_name", "DOE, JOHN"),
            _field("insured_name", "DOE, JOHN"),
            _field("diagnosis_codes", "A00.0"),
            _field("federal_tax_id", "123456789"),
            _field("total_charge", "100.00"),
            _field("npi", "1234567893"),
        ]
        field_repo.add_all(doc.document_id, fields)
        session.commit()

    event_bus = InMemoryEventBus()
    templates = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    worker = ValidationWorker(
        event_bus=event_bus,
        session_factory=session_factory,
        pipeline_version="0.1.0",
        templates=templates,
    )

    envelope = EventEnvelope(
        event_type=Topic.EXTRACTION_COMPLETED.value,
        document_id=doc.document_id,
        correlation_id=uuid4(),
        pipeline_version="0.1.0",
        payload={"document_id": str(doc.document_id)},
    )

    await worker.handle_one(envelope)

    with session_factory() as session:
        doc_repo = DocumentRepository(session)
        outbox = SqlAlchemyOutboxRepository(session)

        updated_doc = doc_repo.get(doc.document_id)
        assert updated_doc is not None
        assert updated_doc.status == DocumentStatus.VALIDATING

        unpub = await outbox.get_unpublished()
        assert len(unpub) >= 1
        topics = [record.topic for record in unpub]
        assert Topic.FIELD_RETRY_REQUESTED.value in topics


@pytest.mark.asyncio
async def test_validation_worker_flags_invalid_fields():
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()

    with session_factory() as session:
        doc_repo = DocumentRepository(session)
        field_repo = ExtractedFieldRepository(session)
        doc_repo.add(doc)

        fields = [
            _field("npi", "INVALID_NPI", confidence=0.2),  # fails NPI & confidence
        ]
        field_repo.add_all(doc.document_id, fields)
        session.commit()

    event_bus = InMemoryEventBus()
    templates = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    worker = ValidationWorker(
        event_bus=event_bus,
        session_factory=session_factory,
        pipeline_version="0.1.0",
        templates=templates,
    )

    envelope = EventEnvelope(
        event_type=Topic.EXTRACTION_COMPLETED.value,
        document_id=doc.document_id,
        correlation_id=uuid4(),
        pipeline_version="0.1.0",
        payload={"document_id": str(doc.document_id)},
    )

    await worker.handle_one(envelope)

    with session_factory() as session:
        doc_repo = DocumentRepository(session)
        outbox = SqlAlchemyOutboxRepository(session)

        updated_doc = doc_repo.get(doc.document_id)
        assert updated_doc is not None
        assert updated_doc.status == DocumentStatus.VALIDATING

        unpub = await outbox.get_unpublished()
        assert len(unpub) >= 1
        topics = [r.topic for r in unpub]
        assert Topic.FIELD_RETRY_REQUESTED.value in topics
