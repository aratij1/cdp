"""Local SQLite/object-store-double failure tests; not production integration evidence."""

from uuid import uuid4

import pytest

from apps.ingestion_api.db.repository import (
    DocumentRepository,
    ExtractedFieldRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from packages.events.bus import InMemoryEventBus
from packages.events.envelope import EventEnvelope
from packages.events.topics import Topic
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from tests.unit.cases.test_output_generation_worker import _document, _field, _stp_decision
from workers.output_generation.consumer import OutputGenerationWorker
from workers.validation.consumer import ValidationWorker


@pytest.mark.asyncio
async def test_validation_redelivery_after_restart_does_not_duplicate_decisions(tmp_path):
    factory = make_session_factory("sqlite:///" + str(tmp_path / "validation.sqlite"))
    doc = _document()
    with factory() as session:
        DocumentRepository(session).add(doc)
        ExtractedFieldRepository(session).add_all(
            doc.document_id, [_field("patient_name", "SYNTHETIC", disposition="HUMAN_CONFIRMED")]
        )
        session.commit()
    event = EventEnvelope(
        event_type=Topic.CLAIM_REVALIDATION_REQUESTED.value,
        document_id=doc.document_id,
        correlation_id=uuid4(),
        pipeline_version="0.1.0",
        payload={"document_id": str(doc.document_id)},
    )
    await ValidationWorker(
        event_bus=InMemoryEventBus(),
        session_factory=factory,
        pipeline_version="0.1.0",
        templates=TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR),
    ).handle_one(event)
    with factory() as session:
        first = await SqlAlchemyOutboxRepository(session).get_unpublished()
        ids = {r.outbox_id for r in first}
        assert any(r.topic == Topic.CLAIM_VALIDATED.value for r in first)
        from apps.ingestion_api.db.models import ExtractedFieldORM

        field = session.query(ExtractedFieldORM).one()
        assert field.normalized_value == "SYNTHETIC"
        assert field.validation_status != "PENDING"
        # A marker alone is not acceptance evidence; unresolved authority stays blocked.
        assert field.disposition == "HUMAN_REVIEW_REQUIRED"

    await ValidationWorker(
        event_bus=InMemoryEventBus(),
        session_factory=factory,
        pipeline_version="0.1.0",
        templates=TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR),
    ).handle_one(event)
    with factory() as session:
        assert {
            r.outbox_id for r in await SqlAlchemyOutboxRepository(session).get_unpublished()
        } == ids


@pytest.mark.asyncio
async def test_partial_object_write_restart_is_byte_stable_and_output_event_unique(
    tmp_path, fake_object_store
):
    factory = make_session_factory("sqlite:///" + str(tmp_path / "output.sqlite"))
    doc = _document()
    with factory() as session:
        DocumentRepository(session).add(doc)
        ExtractedFieldRepository(session).add_all(
            doc.document_id,
            [
                _field("patient_name", "SYNTHETIC", disposition="AUTO_ACCEPTED"),
                _field("npi", "1234567893", disposition="AUTO_ACCEPTED"),
            ],
        )
        session.commit()
    event = EventEnvelope(
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

    class CrashOnce:
        def __init__(self):
            self.calls = 0
            self.written = {}

        def put_immutable(self, bucket, key, data, content_type):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("INJECTED_AFTER_FIRST_WRITE")
            if key in self.written:
                assert self.written[key] == data
            self.written[key] = data
            return fake_object_store.put_immutable(bucket, key, data, content_type)

    storage = CrashOnce()

    def worker():
        return OutputGenerationWorker(
            event_bus=InMemoryEventBus(),
            object_store=storage,
            session_factory=factory,
            pipeline_version="0.1.0",
        )

    with pytest.raises(RuntimeError, match="INJECTED"):
        await worker().handle_one(event)
    with factory() as session:
        assert not await SqlAlchemyOutboxRepository(session).get_unpublished()
    await worker().handle_one(event)
    writes = storage.calls
    await worker().handle_one(event)
    assert storage.calls == writes
    with factory() as session:
        records = await SqlAlchemyOutboxRepository(session).get_unpublished()
        assert len(records) == 1 and records[0].topic == Topic.OUTPUT_COMPLETED.value
