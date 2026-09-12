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


def _field(
    field_name: str, value: str, *, critical: bool = False, disposition: str | None = None
) -> ExtractedField:
    return ExtractedField(
        field_name=field_name,
        raw_value=value,
        normalized_value=value,
        confidence=0.98,
        page_number=1,
        bounding_box=BoundingBox(
            x0=0.1, y0=0.1, x1=0.2, y1=0.2, image_width=1000, image_height=1000
        ),
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


def _complete_output_payload(doc, factory):
    """Synthetic complete canonical evidence; never used as qualification inputs."""
    from packages.runtime_profile import DecisionServiceFactory
    from tests.unit.cases.test_claim_decision_service import _context, _decision

    service = DecisionServiceFactory.from_profile().claim_decision
    context = _context(service)
    context.claim_id = str(doc.document_id)
    values = {"insured_id_number": "SYNTHETIC001", "patient_dob": "2000-01-02",
              "patient_name": "DOE, JOHN", "total_charge": "10.00"}
    with factory() as session:
        repository = ExtractedFieldRepository(session)
        existing = {r.field_name:r for r in repository.list_for_document(doc.document_id)}
        additions = []
        required_names = {d.field_name for d in context.field_decisions}
        context.field_decisions.extend(_decision(service, "CMS1500", name)
                                       for name in existing if name not in required_names)
        for decision in context.field_decisions:
            row = existing.get(decision.field_name)
            value = (row.normalized_value or row.raw_value) if row else values[decision.field_name]
            decision.selected_value = value
            if row:
                decision.disposition = type(decision.disposition)(row.disposition)
            else:
                additions.append(_field(decision.field_name, value, disposition="AUTO_ACCEPTED"))
        repository.add_all(doc.document_id, additions)
        session.commit()
    return {
        "form_type": "CMS1500",
        "claim_decision": service.decide(context).model_dump(mode="json"),
        "field_decisions": [d.model_dump(mode="json") for d in context.field_decisions],
        "claim_membership": {
            "governed": True, "complete_claim_membership_confirmed": True,
            "boundary_provenance": {"owner_approval_receipt_sha256": "a"*64,
                                    "approved_csv_sha256": "b"*64},
            "claims": {str(doc.document_id): {
                "page_ids": ["synthetic-page"], "claim_form_page_ids": ["synthetic-page"],
                "attachment_page_ids": [], "documents": {"synthetic-document": {
                    "page_ids": ["synthetic-page"], "boundary": "CONFIRMED",
                    "boundary_provenance": "synthetic-only"}},
            }},
        },
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
        payload=_complete_output_payload(doc, session_factory),
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
async def test_output_requires_canonical_terminal_disposition_for_critical_fields(
    fake_object_store,
):
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()
    with session_factory() as session:
        DocumentRepository(session).add(doc)
        ExtractedFieldRepository(session).add_all(
            doc.document_id,
            [
                _field(
                    "patient_name",
                    "DOE, JOHN",
                    critical=True,
                    disposition="VALIDATED_AUTOMATICALLY",
                )
            ],
        )
        session.commit()
    worker = OutputGenerationWorker(InMemoryEventBus(), fake_object_store, session_factory, "0.1.0")
    envelope = EventEnvelope(
        event_type=Topic.CLAIM_VALIDATED.value,
        document_id=doc.document_id,
        correlation_id=uuid4(),
        pipeline_version="0.1.0",
        payload={"form_type": "CMS1500"},
    )
    await worker.handle_one(envelope)
    with session_factory() as session:
        assert (
            DocumentRepository(session).get(doc.document_id).status == DocumentStatus.NEEDS_REVIEW
        )
        records = await SqlAlchemyOutboxRepository(session).get_unpublished()
        assert [r.topic for r in records] == [Topic.OUTPUT_REVIEW_REQUIRED.value]


@pytest.mark.asyncio
async def test_output_accepts_canonical_reference_confirmed_disposition(fake_object_store):
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()
    with session_factory() as session:
        DocumentRepository(session).add(doc)
        ExtractedFieldRepository(session).add_all(
            doc.document_id,
            [_field("patient_name", "DOE, JOHN", critical=True, disposition="REFERENCE_CONFIRMED")],
        )
        session.commit()
    worker = OutputGenerationWorker(InMemoryEventBus(), fake_object_store, session_factory, "0.1.0")
    await worker.handle_one(
        EventEnvelope(
            event_type=Topic.CLAIM_VALIDATED.value,
            document_id=doc.document_id,
            correlation_id=uuid4(),
            pipeline_version="0.1.0",
            payload=_complete_output_payload(doc, session_factory),
        )
    )
    with session_factory() as session:
        assert (
            DocumentRepository(session).get(doc.document_id).status
            == DocumentStatus.OUTPUT_GENERATED
        )


@pytest.mark.asyncio
async def test_output_rejects_stp_standard(fake_object_store):
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()
    with session_factory() as session:
        DocumentRepository(session).add(doc)
        ExtractedFieldRepository(session).add_all(
            doc.document_id,
            [_field("patient_name", "DOE, JOHN", critical=True, disposition="REFERENCE_CONFIRMED")],
        )
        session.commit()
    worker = OutputGenerationWorker(InMemoryEventBus(), fake_object_store, session_factory, "0.1.0")
    await worker.handle_one(
        EventEnvelope(
            event_type=Topic.CLAIM_VALIDATED.value,
            document_id=doc.document_id,
            correlation_id=uuid4(),
            pipeline_version="0.1.0",
            payload={
                "form_type": "CMS1500",
                "claim_decision": _stp_decision(doc.document_id, disposition="STP_STANDARD"),
            },
        )
    )

    with session_factory() as session:
        assert (
            DocumentRepository(session).get(doc.document_id).status == DocumentStatus.NEEDS_REVIEW
        )
        records = await SqlAlchemyOutboxRepository(session).get_unpublished()
        assert [r.topic for r in records] == [Topic.OUTPUT_REVIEW_REQUIRED.value]


@pytest.mark.asyncio
async def test_generic_hold_is_durable_and_never_serializes(fake_object_store):
    from packages.domain.enums import BundleType

    factory = make_session_factory("sqlite:///:memory:")
    doc = _document()
    doc.bundle_type = BundleType.D_UNSTRUCTURED
    with factory() as session:
        DocumentRepository(session).add(doc)
        session.commit()
    event = EventEnvelope(
        event_type=Topic.CLAIM_VALIDATED.value,
        document_id=doc.document_id,
        correlation_id=uuid4(),
        pipeline_version="0.1.0",
        payload={"form_type": "UNSTRUCTURED", "claim_decision": _stp_decision(doc.document_id)},
    )
    for _ in range(2):
        await OutputGenerationWorker(
            InMemoryEventBus(), fake_object_store, factory, "0.1.0"
        ).handle_one(event)
    with factory() as session:
        records = await SqlAlchemyOutboxRepository(session).get_unpublished()
        assert len(records) == 1
        assert records[0].topic == Topic.OUTPUT_REVIEW_REQUIRED.value
        assert "GOVERNED_GENERIC_REVIEW_REQUIRED" in records[0].envelope.payload["reason_codes"]
        assert (
            DocumentRepository(session).get(doc.document_id).status == DocumentStatus.NEEDS_REVIEW
        )
    assert not fake_object_store.exists(
        "idp-documents", f"outputs/{doc.tenant_id}/{doc.document_id}/canonical_claim.json"
    )


@pytest.mark.asyncio
async def test_unknown_explicit_form_still_fails_closed(fake_object_store):
    factory = make_session_factory("sqlite:///:memory:")
    doc = _document()
    with factory() as session:
        DocumentRepository(session).add(doc)
        session.commit()
    worker = OutputGenerationWorker(InMemoryEventBus(), fake_object_store, factory, "0.1.0")
    with pytest.raises(ValueError):
        await worker.handle_one(
            EventEnvelope(
                event_type=Topic.CLAIM_VALIDATED.value,
                document_id=doc.document_id,
                correlation_id=uuid4(),
                pipeline_version="0.1.0",
                payload={"form_type": "UNKNOWN", "claim_decision": _stp_decision(doc.document_id)},
            )
        )
    with factory() as session:
        assert not await SqlAlchemyOutboxRepository(session).get_unpublished()


@pytest.mark.asyncio
async def test_output_rejects_event_value_that_differs_from_persisted_field(fake_object_store):
    factory = make_session_factory("sqlite:///:memory:")
    doc = _document()
    with factory() as session:
        DocumentRepository(session).add(doc)
        session.commit()
    payload = _complete_output_payload(doc, factory)
    payload["field_decisions"][0]["selected_value"] = "UNAUTHORIZED_REPLACEMENT"
    event = EventEnvelope(event_type=Topic.CLAIM_VALIDATED.value, document_id=doc.document_id,
                          correlation_id=uuid4(), pipeline_version="0.1.0", payload=payload)
    with pytest.raises(ValueError, match="persisted field decision mismatch"):
        await OutputGenerationWorker(InMemoryEventBus(), fake_object_store, factory, "0.1.0").handle_one(event)
    assert not fake_object_store.exists("idp-documents", f"outputs/{doc.tenant_id}/{doc.document_id}/canonical_claim.json")
