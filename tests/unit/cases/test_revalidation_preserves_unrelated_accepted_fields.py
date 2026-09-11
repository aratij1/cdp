"""Regression test: proving that correcting one field and triggering
claim.revalidation.requested preserves existing valid evidence/provenance on
unrelated accepted fields and does not cause them to be re-escalated or emit retries.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from apps.ingestion_api.db.models import OutboxORM
from apps.ingestion_api.db.repository import (
    DocumentRepository,
    ExtractedFieldRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from packages.domain.common import BoundingBox, ObjectRef
from packages.domain.document import Document
from packages.domain.enums import DocumentStatus, ExtractionMethod, SourceFormat, ValidationStatus
from packages.domain.extraction import ExtractedField, FieldEvidence
from packages.events.bus import InMemoryEventBus
from packages.events.envelope import EventEnvelope
from packages.events.topics import Topic
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from workers.validation.consumer import ValidationWorker


def _field(field_name: str, value: str, confidence: float = 0.99, disposition: str | None = None) -> ExtractedField:
    return ExtractedField(
        field_name=field_name,
        raw_value=value,
        normalized_value=value,
        confidence=confidence,
        page_number=1,
        bounding_box=BoundingBox(x0=0.1, y0=0.1, x1=0.2, y1=0.2, image_width=1000, image_height=1000),
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
        template_version="cms1500@02-12",
        disposition=disposition,
        validation_status=ValidationStatus.VALID if disposition in ("AUTO_ACCEPTED", "HUMAN_CONFIRMED") else ValidationStatus.PENDING,
        candidates=[
            FieldEvidence(source=ExtractionMethod.REGIONAL_PADDLEOCR, raw_text=value, confidence=confidence),
            FieldEvidence(source=ExtractionMethod.TEMPLATE_RULES, raw_text=value, confidence=confidence),
        ],
    )


@pytest.mark.asyncio
async def test_revalidation_preserves_unrelated_accepted_fields() -> None:
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = Document(
        tenant_id="tenant-1",
        source_filename="claim.tiff",
        detected_format=SourceFormat.TIFF,
        sha256="d" * 64,
        original_object=ObjectRef(bucket="idp-documents", key="documents/aa/bb/x.tiff"),
        pipeline_version="0.1.0",
        schema_version="1.0",
        status=DocumentStatus.VALIDATING,
    )

    f_npi = _field("rendering_provider_npi", "1234567893", 0.99, disposition="AUTO_ACCEPTED")
    f_charge = _field("total_charge", "250.00", 0.95, disposition="AUTO_ACCEPTED")
    f_patient = _field("patient_name", "DOE, JOHN", 1.0, disposition="HUMAN_CONFIRMED")

    with session_factory() as session:
        doc_repo = DocumentRepository(session)
        field_repo = ExtractedFieldRepository(session)
        doc_repo.add(doc)
        field_repo.add_all(doc.document_id, [f_npi, f_charge, f_patient])
        session.commit()

    event_bus = InMemoryEventBus()
    templates = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    worker = ValidationWorker(
        event_bus=event_bus,
        session_factory=session_factory,
        pipeline_version="0.1.0",
        templates=templates,
    )

    revalidation_envelope = EventEnvelope(
        event_type=Topic.CLAIM_REVALIDATION_REQUESTED.value,
        correlation_id=uuid4(),
        document_id=doc.document_id,
        claim_id=doc.document_id,
        pipeline_version="0.1.0",
        payload={
            "document_id": str(doc.document_id),
            "claim_id": str(doc.document_id),
            "field_id": str(f_patient.field_id),
            "field_name": "patient_name",
            "correction_reviewer": "test_reviewer@company.com",
        },
    )

    # Execute revalidation
    await worker.handle_one(revalidation_envelope)

    # Verify that:
    # 1. Unrelated accepted fields preserve AUTO_ACCEPTED disposition and VALID status
    # 2. Corrected field retains HUMAN_CONFIRMED disposition and VALID status
    # 3. No FIELD_RETRY_REQUESTED event is emitted in outbox for accepted or confirmed fields
    with session_factory() as session:
        field_repo = ExtractedFieldRepository(session)
        fields = {f.field_name: f for f in field_repo.list_for_document(doc.document_id)}

        assert fields["rendering_provider_npi"].disposition == "AUTO_ACCEPTED"
        assert fields["rendering_provider_npi"].validation_status == ValidationStatus.VALID

        assert fields["total_charge"].disposition == "AUTO_ACCEPTED"
        assert fields["total_charge"].validation_status == ValidationStatus.VALID

        assert fields["patient_name"].disposition == "HUMAN_CONFIRMED"
        assert fields["patient_name"].validation_status == ValidationStatus.VALID

        outbox_records = session.query(OutboxORM).all()
        retry_events = [r for r in outbox_records if r.topic == Topic.FIELD_RETRY_REQUESTED.value]
        assert len(retry_events) == 0, f"Expected 0 retry requests on revalidation, found: {len(retry_events)}"
