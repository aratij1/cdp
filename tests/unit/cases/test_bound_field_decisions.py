"""Synthetic persisted-state invalidation; no production truth or approvals."""
from uuid import uuid4

import pytest

from packages.evidence_decision import FieldDecision, FieldDisposition, NextAction
from packages.field_decision_binding import STALE_REASON, bind_decision, decision_matches
from tests.unit.cases.test_validation_worker import _document, _field


def bound():
    field = _field("patient_name", "SYNTHETIC PERSON")
    field.disposition = "HUMAN_REVIEW_REQUIRED"
    decision = FieldDecision(field_id=str(field.field_id),field_name=field.field_name,
        disposition=FieldDisposition.HUMAN_REVIEW_REQUIRED,calibrated_probability=0,
        next_action=NextAction.HUMAN_REVIEW,policy_version="test")
    context = {"runtime":"a"*64,"policy":{"hash":"b"*64},"identity":{"form":"CMS1500"}}
    decision.input_binding = bind_decision(field,decision,**context)
    return field,decision,context


def test_unresolved_null_selection_binds_without_replacing_ocr_value():
    field,decision,context=bound()
    assert decision_matches(field,decision,**context)
    assert field.raw_value == "SYNTHETIC PERSON" and decision.selected_value is None


@pytest.mark.parametrize("change",["raw","normalized","evidence","runtime","policy","identity","selection","disposition"])
def test_changed_input_invalidates_old_decision(change):
    field,decision,context=bound()
    if change=="raw":field.raw_value="SYNTHETIC OTHER"
    elif change=="normalized":field.normalized_value="OTHER"
    elif change=="evidence":field.candidates[0].confidence=.2
    elif change=="runtime":context["runtime"]="c"*64
    elif change=="policy":context["policy"]={"hash":"c"*64}
    elif change=="identity":context["identity"]={"form":"UB04"}
    elif change=="selection":decision.selected_value="UNAUTHORIZED"
    else:field.disposition="AUTO_ACCEPTED"
    assert not decision_matches(field,decision,**context)


@pytest.mark.asyncio
async def test_stale_output_revalidates_current_state_and_still_holds_incomplete_evidence(fake_object_store):
    from apps.ingestion_api.db.models import ExtractedFieldORM
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
    from workers.output_generation.consumer import OutputGenerationWorker
    from workers.validation.consumer import ValidationWorker
    factory=make_session_factory("sqlite:///:memory:");doc=_document();field=_field("patient_name","SYNTHETIC")
    with factory() as session:
        DocumentRepository(session).add(doc);ExtractedFieldRepository(session).add_all(doc.document_id,[field]);session.commit()
    bus=InMemoryEventBus()
    validation=ValidationWorker(bus,factory,"test",TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR))
    output=OutputGenerationWorker(bus,fake_object_store,factory,"test")
    event=EventEnvelope(event_type=Topic.EXTRACTION_COMPLETED.value,document_id=doc.document_id,
        correlation_id=uuid4(),pipeline_version="test",payload={"form_type":"CMS1500"})
    await validation.handle_one(event)
    with factory() as session:
        records=await SqlAlchemyOutboxRepository(session).get_unpublished()
        validated=next(r.envelope for r in records if r.topic==Topic.CLAIM_VALIDATED.value)
        row=session.get(ExtractedFieldORM,field.field_id);row.raw_value="CHANGED SYNTHETIC";session.commit()
    await output.handle_one(validated)
    await output.handle_one(validated)  # stale request is durable/idempotent
    with factory() as session:
        records=await SqlAlchemyOutboxRepository(session).get_unpublished()
        requests=[r.envelope for r in records if r.topic==Topic.CLAIM_REVALIDATION_REQUESTED.value]
    assert len(requests)==1 and requests[0].payload["decision_recompute_reason"]==STALE_REASON
    await validation.handle_one(requests[0])
    with factory() as session:
        records=await SqlAlchemyOutboxRepository(session).get_unpublished()
        fresh=next(r.envelope for r in records if r.topic==Topic.CLAIM_VALIDATED.value and r.envelope.event_id!=validated.event_id)
    from apps.ingestion_api.db.mappers import orm_to_extracted_field
    from packages.evidence_decision import FieldDecision
    from packages.field_decision_binding import bind_decision
    with factory() as session:
        saved = orm_to_extracted_field(session.get(ExtractedFieldORM,field.field_id))
    d = FieldDecision.model_validate(fresh.payload["field_decisions"][0])
    binding = bind_decision(saved,d,runtime=output._runtime_digest,
        policy=output._field_decision_service.configuration_identity,
        identity=fresh.payload["decision_binding_identity"])
    assert d.input_binding == binding, [k for k in binding if d.input_binding.get(k)!=binding[k]]
    await output.handle_one(fresh)
    with factory() as session:
        records=await SqlAlchemyOutboxRepository(session).get_unpublished()
    assert sum(r.topic==Topic.CLAIM_REVALIDATION_REQUESTED.value for r in records)==1
    assert any(r.topic==Topic.OUTPUT_REVIEW_REQUIRED.value for r in records)
    assert not any(r.topic==Topic.OUTPUT_COMPLETED.value for r in records)


@pytest.mark.asyncio
async def test_complete_bound_decisions_can_progress_to_output(fake_object_store):
    from apps.ingestion_api.db.repository import (
        DocumentRepository,
        ExtractedFieldRepository,
        SqlAlchemyOutboxRepository,
    )
    from apps.ingestion_api.db.session import make_session_factory
    from packages.events.bus import InMemoryEventBus
    from packages.events.envelope import EventEnvelope
    from packages.events.topics import Topic
    from packages.runtime_profile import DecisionServiceFactory
    from tests.unit.cases.test_output_generation_worker import _complete_output_payload
    from workers.output_generation.consumer import OutputGenerationWorker
    factory=make_session_factory("sqlite:///:memory:");doc=_document()
    with factory() as session:
        DocumentRepository(session).add(doc);session.commit()
    payload=_complete_output_payload(doc,factory)
    worker=OutputGenerationWorker(InMemoryEventBus(),fake_object_store,factory,"test")
    identity={"document_id":str(doc.document_id),"claim_id":str(doc.document_id),
        "form_type":"CMS1500","claim_membership":payload["claim_membership"],"form_identity_authority":{}}
    with factory() as session: fields=ExtractedFieldRepository(session).list_for_document(doc.document_id)
    for item in payload["field_decisions"]:
        field=next(f for f in fields if f.field_name==item["field_name"])
        decision=FieldDecision.model_validate(item);decision.field_id=str(field.field_id)
        decision.input_binding=bind_decision(field,decision,runtime=worker._runtime_digest,
            policy=DecisionServiceFactory.from_profile().evidence_decision.configuration_identity,identity=identity)
        item.update(decision.model_dump(mode="json"))
    event=EventEnvelope(event_type=Topic.CLAIM_VALIDATED.value,document_id=doc.document_id,
        correlation_id=uuid4(),pipeline_version="test",payload=payload)
    await worker.handle_one(event)
    with factory() as session: records=await SqlAlchemyOutboxRepository(session).get_unpublished()
    assert any(r.topic==Topic.OUTPUT_COMPLETED.value for r in records), [r.topic for r in records]


def test_binding_hash_preserves_set_semantics_across_serialization():
    from packages.field_decision_binding import digest
    assert digest({"evidence":{"E3","E1","E2"}})==digest({"evidence":{"E2","E3","E1"}})
    assert digest({"ordered":["E1","E2"]})!=digest({"ordered":["E2","E1"]})
