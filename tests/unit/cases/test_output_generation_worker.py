"""Unit tests for Output Generation Worker: consumes claim.validated, renders
output files (Canonical JSON, Evidence Manifest, Reconciliation Report, NSF),
uploads them to ObjectStore, and outboxes output.generated.
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
from workers.output_generation.consumer import OutputGenerationWorker


def _document() -> Document:
    return Document(
        tenant_id="tenant-1",
        source_filename="claim.tiff",
        detected_format=SourceFormat.TIFF,
        sha256="e" * 64,
        original_object=ObjectRef(bucket="idp-documents", key="documents/aa/bb/x.tiff"),
        pipeline_version="0.1.0",
        schema_version="1.0",
        status=DocumentStatus.COMPLETED,
    )


def _field(field_name: str, value: str, *, critical: bool = False, disposition: str | None = None) -> ExtractedField:
    return ExtractedField(
        field_name=field_name,
        raw_value=value,
        normalized_value=value,
        confidence=0.98,
        page_number=1,
        bounding_box=BoundingBox(x0=0.1, y0=0.1, x1=0.2, y1=0.2, image_width=1000, image_height=1000),
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
        is_critical=critical,
        disposition=disposition,
    )


def _stp_decision(claim_id, *, disposition: str = "STP_SAFE") -> dict:
    return {
        "claim_id": str(claim_id),
        "disposition": disposition,
        "blocking_unresolved_fields": [],
        "nonblocking_unresolved_fields": [],
        "critical_blockers": [],
        "contradictions": [],
        "reason_codes": ["ALL_BLOCKING_FIELDS_SAFELY_RESOLVED"],
        "stp_eligible": True,
        "policy_id": "claim-stp",
        "policy_version": "claim-decision-v1",
    }


@pytest.mark.asyncio
async def test_output_generation_worker_generates_all_outputs(fake_object_store):
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()

    with session_factory() as session:
        doc_repo = DocumentRepository(session)
        field_repo = ExtractedFieldRepository(session)
        doc_repo.add(doc)

        fields = [
            _field("patient_name", "DOE, JOHN", disposition="AUTO_ACCEPTED"),
            _field("npi", "1234567893", disposition="AUTO_ACCEPTED"),
        ]
        field_repo.add_all(doc.document_id, fields)
        session.commit()

    event_bus = InMemoryEventBus()
    worker = OutputGenerationWorker(
        event_bus=event_bus,
        object_store=fake_object_store,
        session_factory=session_factory,
        pipeline_version="0.1.0",
    )

    envelope = EventEnvelope(
        event_type=Topic.CLAIM_VALIDATED.value,
        document_id=doc.document_id,
        correlation_id=uuid4(),
        pipeline_version="0.1.0",
        payload={
            "document_id": str(doc.document_id),
            "form_type": "CMS1500",
            "claim_decision": _stp_decision(doc.document_id),
        },
    )

    await worker.handle_one(envelope)

    with session_factory() as session:
        doc_repo = DocumentRepository(session)
        outbox = SqlAlchemyOutboxRepository(session)

        updated_doc = doc_repo.get(doc.document_id)
        assert updated_doc is not None
        assert updated_doc.status == DocumentStatus.OUTPUT_GENERATED

        unpub = await outbox.get_unpublished()
        assert len(unpub) == 1
        assert unpub[0].topic == Topic.OUTPUT_COMPLETED.value

    prefix = f"outputs/{doc.tenant_id}/{doc.document_id}"
    assert fake_object_store.exists("idp-documents", f"{prefix}/canonical_claim.json")
    assert fake_object_store.exists("idp-documents", f"{prefix}/evidence_manifest.json")
    assert fake_object_store.exists("idp-documents", f"{prefix}/reconciliation_report.json")


@pytest.mark.asyncio
async def test_output_requires_canonical_terminal_disposition_for_critical_fields(fake_object_store):
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()
    with session_factory() as session:
        DocumentRepository(session).add(doc)
        ExtractedFieldRepository(session).add_all(doc.document_id, [
            _field("patient_name", "DOE, JOHN", critical=True, disposition="VALIDATED_AUTOMATICALLY")
        ])
        session.commit()
    worker = OutputGenerationWorker(InMemoryEventBus(), fake_object_store, session_factory, "0.1.0")
    envelope = EventEnvelope(
        event_type=Topic.CLAIM_VALIDATED.value, document_id=doc.document_id,
        correlation_id=uuid4(), pipeline_version="0.1.0",
        payload={"form_type": "CMS1500"},
    )
    with pytest.raises(ValueError, match="unresolved critical"):
        await worker.handle_one(envelope)


@pytest.mark.asyncio
async def test_output_accepts_canonical_reference_confirmed_disposition(fake_object_store):
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()
    with session_factory() as session:
        DocumentRepository(session).add(doc)
        ExtractedFieldRepository(session).add_all(doc.document_id, [
            _field("patient_name", "DOE, JOHN", critical=True, disposition="REFERENCE_CONFIRMED")
        ])
        session.commit()
    worker = OutputGenerationWorker(InMemoryEventBus(), fake_object_store, session_factory, "0.1.0")
    await worker.handle_one(EventEnvelope(
        event_type=Topic.CLAIM_VALIDATED.value, document_id=doc.document_id,
        correlation_id=uuid4(), pipeline_version="0.1.0",
        payload={"form_type": "CMS1500", "claim_decision": _stp_decision(doc.document_id)},
    ))
    with session_factory() as session:
        assert DocumentRepository(session).get(doc.document_id).status == DocumentStatus.OUTPUT_GENERATED


@pytest.mark.asyncio
async def test_output_rejects_stp_standard(fake_object_store):
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()
    with session_factory() as session:
        DocumentRepository(session).add(doc)
        ExtractedFieldRepository(session).add_all(doc.document_id, [
            _field("patient_name", "DOE, JOHN", critical=True, disposition="REFERENCE_CONFIRMED")
        ])
        session.commit()
    worker = OutputGenerationWorker(InMemoryEventBus(), fake_object_store, session_factory, "0.1.0")
    with pytest.raises(ValueError, match="canonical disposition is STP_STANDARD"):
        await worker.handle_one(EventEnvelope(
            event_type=Topic.CLAIM_VALIDATED.value, document_id=doc.document_id,
            correlation_id=uuid4(), pipeline_version="0.1.0",
            payload={
                "form_type": "CMS1500",
                "claim_decision": _stp_decision(doc.document_id, disposition="STP_STANDARD"),
            },
        ))
