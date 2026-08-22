import io
from uuid import uuid4

import pytest
from PIL import Image

from apps.ingestion_api.db.repository import (
    DocumentRepository,
    ExtractedFieldRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from packages.domain.common import BoundingBox, ObjectRef
from packages.domain.document import Document
from packages.domain.enums import DocumentStatus, ExtractionMethod, SourceFormat
from packages.domain.extraction import ExtractedField, FieldEvidence
from packages.events.bus import InMemoryEventBus
from packages.events.envelope import EventEnvelope
from packages.events.topics import Topic
from workers.retry.consumer import RetryWorker


class MockObjectStore:
    def get_bytes(self, object_ref: ObjectRef) -> bytes:
        img = Image.new("RGB", (100, 100), color="white")
        b = io.BytesIO()
        img.save(b, format="PNG")
        return b.getvalue()
    def put(self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        pass

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

def _field(field_name: str, value: str, confidence: float = 0.99, is_critical: bool = True) -> ExtractedField:
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
            FieldEvidence(source=ExtractionMethod.ALTERNATE_PREPROCESS_OCR, raw_text=value, confidence=confidence),
            FieldEvidence(source=ExtractionMethod.LAYOUTLMV3, raw_text=value, confidence=confidence),
            FieldEvidence(source=ExtractionMethod.VLM_FALLBACK, raw_text=value, confidence=confidence),
        ],
        is_critical=is_critical,
    )

@pytest.mark.asyncio
async def test_retry_worker_escalates_to_human_review_when_limit_reached():
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()
    
    with session_factory() as session:
        doc_repo = DocumentRepository(session)
        field_repo = ExtractedFieldRepository(session)
        doc_repo.add(doc)
        
        field = _field("npi", "INVALID_NPI", confidence=0.2)
        field.escalation_count = 3 # Simulate limit reached
        field_repo.add_all(doc.document_id, [field])
        session.commit()

    class MockRouter:
        def decide(self, input):
            from packages.domain.enums import ExtractionMethod
            from packages.domain.routing import ModelDecision
            return ModelDecision(
                field_name=input.field_name,
                selected_route=ExtractionMethod.HUMAN_REVIEW, 
                reason_codes=["escalated"],
                estimated_cost_usd=0.0,
                escalation_count=3,
            )

    event_bus = InMemoryEventBus()
    worker = RetryWorker(
        event_bus=event_bus,
        object_store=MockObjectStore(),
        session_factory=session_factory,
        pipeline_version="0.1.0",
    )
    worker._router = MockRouter()

    envelope = EventEnvelope(
        event_type=Topic.FIELD_RETRY_REQUESTED.value,
        document_id=doc.document_id,
        correlation_id=uuid4(),
        pipeline_version="0.1.0",
        payload={
            "document_id": str(doc.document_id),
            "field_id": str(field.field_id),
            "field_name": field.field_name,
        },
    )

    await worker.handle_one(envelope)

    with session_factory() as session:
        outbox = SqlAlchemyOutboxRepository(session)
        unpub = await outbox.get_unpublished()
        assert len(unpub) >= 1
        topics = [r.topic for r in unpub]
        assert Topic.HUMAN_REVIEW_REQUESTED.value in topics


@pytest.mark.asyncio
async def test_retry_appends_candidate_without_overwriting_canonical_value(monkeypatch):
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()
    with session_factory() as session:
        DocumentRepository(session).add(doc)
        field = _field("patient_name", "ORIGINAL", confidence=.2)
        initial_candidates = len(field.candidates)
        ExtractedFieldRepository(session).add_all(doc.document_id, [field])
        session.commit()

    class MockRouter:
        def decide(self, input):
            from packages.domain.routing import ModelDecision
            return ModelDecision(
                field_name=input.field_name, selected_route=ExtractionMethod.LAYOUTLMV3,
                reason_codes=["retry"], estimated_cost_usd=0, escalation_count=1,
            )

    class Result:
        value = "RETRY VALUE"
        confidence = .99

    class FakeLayout:
        def extract(self, image, fields):
            return [Result()]

    monkeypatch.setattr("workers.retry.consumer.LayoutLMv3Adapter", FakeLayout)
    worker = RetryWorker(InMemoryEventBus(), MockObjectStore(), session_factory, "0.1.0")
    worker._router = MockRouter()
    await worker.handle_one(EventEnvelope(
        event_type=Topic.FIELD_RETRY_REQUESTED.value, document_id=doc.document_id,
        correlation_id=uuid4(), pipeline_version="0.1.0",
        payload={"field_id": str(field.field_id), "field_name": field.field_name,
                 "hard_validation_passed": False},
    ))
    from sqlalchemy import select
    from apps.ingestion_api.db.models import ExtractedFieldORM
    with session_factory() as session:
        row = session.execute(select(ExtractedFieldORM)).scalar_one()
        assert row.raw_value == "ORIGINAL"
        assert len(row.candidates) == initial_candidates + 1
        assert row.candidates[-1]["raw_text"] == "RETRY VALUE"
