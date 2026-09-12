"""Synthetic end-to-end regressions for fail-closed pipeline completion."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

from apps.ingestion_api.db.repository import (
    DocumentRepository,
    ExtractedFieldRepository,
    PageRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from packages.domain.common import BoundingBox
from packages.domain.enums import DocumentStatus
from packages.events.bus import InMemoryEventBus
from packages.events.envelope import EventEnvelope
from packages.events.topics import Topic
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from tests.unit.cases.test_validation_worker import _document, _field
from workers.output_generation.consumer import OutputGenerationWorker
from workers.validation.consumer import ValidationWorker


@pytest.mark.asyncio
async def test_empty_extraction_completes_once_and_routes_to_output_review():
    factory = make_session_factory("sqlite:///:memory:")
    document = _document()
    with factory() as session:
        DocumentRepository(session).add(document)
        session.commit()
    bus = InMemoryEventBus()
    templates = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    worker = ValidationWorker(bus, factory, "test", templates)
    envelope = EventEnvelope(
        event_type=Topic.EXTRACTION_COMPLETED.value,
        document_id=document.document_id,
        correlation_id=uuid4(),
        pipeline_version="test",
        payload={"field_count": 0},
    )
    await worker.handle_one(envelope)
    await worker.handle_one(envelope)
    with factory() as session:
        events = await SqlAlchemyOutboxRepository(session).get_unpublished()
    validated = [e for e in events if e.topic == Topic.CLAIM_VALIDATED.value]
    assert len(validated) == 1
    assert validated[0].envelope.payload["field_decisions"] == []
    decision = validated[0].envelope.payload["claim_decision"]
    assert decision["disposition"] == "CLAIM_REVIEW_REQUIRED"
    assert decision["stp_eligible"] is False
    output = OutputGenerationWorker(bus, object(), factory, "test", templates=templates)
    await output.handle_one(validated[0].envelope)
    await output.handle_one(validated[0].envelope)
    with factory() as session:
        events = await SqlAlchemyOutboxRepository(session).get_unpublished()
        assert (
            DocumentRepository(session).get(document.document_id).status
            is DocumentStatus.NEEDS_REVIEW
        )
    assert sum(e.topic == Topic.OUTPUT_REVIEW_REQUIRED.value for e in events) == 1
    assert not any(e.topic == Topic.OUTPUT_COMPLETED.value for e in events)


@pytest.mark.asyncio
async def test_printed_total_does_not_invent_service_line_charge():
    factory = make_session_factory("sqlite:///:memory:")
    document = _document()
    with factory() as session:
        DocumentRepository(session).add(document)
        ExtractedFieldRepository(session).add_all(
            document.document_id, [_field("total_charge", "100.00")]
        )
        session.commit()
    observed = []
    engine = SimpleNamespace(validate_claim=lambda claim, template: observed.append(claim) or [])
    worker = ValidationWorker(
        InMemoryEventBus(),
        factory,
        "test",
        TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR),
        validation_engine=engine,
    )
    await worker.handle_one(
        EventEnvelope(
            event_type=Topic.EXTRACTION_COMPLETED.value,
            document_id=document.document_id,
            correlation_id=uuid4(),
            pipeline_version="test",
            payload={},
        )
    )
    assert len(observed) == 1
    assert observed[0].total_charge_amount == 100
    assert observed[0].service_lines == []


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [("100.00", "BAD"), ("BAD", "100.00")])
async def test_layout_datatype_evidence_belongs_to_each_candidate(monkeypatch, values):
    from packages.evidence_decision import FieldDisposition
    from workers.unstructured_extraction import consumer as module

    factory = make_session_factory("sqlite:///:memory:")
    document = _document()
    with factory() as session:
        DocumentRepository(session).add(document)
        session.commit()
    monkeypatch.setattr(
        PageRepository,
        "list_for_document",
        lambda self, document_id: [SimpleNamespace(page_number=1, extraction_object=None)],
    )
    monkeypatch.setattr(module, "_load_image", lambda *args: Image.new("RGB", (100, 100), "white"))
    box = BoundingBox(x0=0.1, y0=0.1, x1=0.5, y1=0.5, image_width=100, image_height=100)
    candidates = [
        SimpleNamespace(
            value=value,
            confidence=0.9,
            bbox=box,
            datatype_valid=False,
            matched_alias="total",
            relationship_evidence=SimpleNamespace(relationship="SAME_ROW"),
        )
        for value in values
    ]
    result = SimpleNamespace(
        candidates={"total_charge": candidates},
        engine="synthetic",
        schema_evidence=SimpleNamespace(schema_family="UNKNOWN", confidence=0),
        route=SimpleNamespace(value="UNKNOWN_UNSTRUCTURED"),
        route_reason_codes=[],
    )
    observed = []

    def decide(context):
        observed.append(context)
        return SimpleNamespace(disposition=FieldDisposition.HUMAN_REVIEW_REQUIRED, reason_codes=[])

    worker = module.UnstructuredExtractionWorker(
        InMemoryEventBus(),
        object(),
        factory,
        "test",
        SimpleNamespace(extract=lambda image: [], engine_name="synthetic"),
        layout_engine=SimpleNamespace(extract=lambda *args, **kwargs: result),
        decision_service=SimpleNamespace(decide=decide),
    )
    await worker.handle_one(
        EventEnvelope(
            event_type=Topic.EXTRACTION_UNSTRUCTURED_REQUESTED.value,
            document_id=document.document_id,
            correlation_id=uuid4(),
            pipeline_version="test",
            payload={},
        )
    )
    assert len(observed) == 1
    assert ["DATATYPE_VALID" in c.validation_results for c in observed[0].candidates] == [
        value == "100.00" for value in values
    ]


@pytest.mark.parametrize("wrong_stage", ["raw", "final"])
def test_false_accepted_value_never_counts_as_post_hitl_true_stp(wrong_stage):
    from tests.unit.cases.test_qualification_closure_inputs import snapshots
    from tests.unit.cases.test_release_scoring_cost_closure import seal

    truth, raw, final, membership, score = snapshots()
    for snapshot in (raw, final):
        for field in snapshot["fields"]:
            field.update(value="SYNTHETIC", accepted=True, review_required=False)
        snapshot["claims"]["claim"].update(
            output_completed=True,
            required_fields_pass=True,
            required_evidence_pass=True,
            automatic_output_safely_generated=True,
            human_corrected=False,
            human_reviewed=False,
            review_required=False,
        )
    target = raw if wrong_stage == "raw" else final
    target["fields"][0]["value"] = "INCORRECT"
    seal(raw)
    seal(final)
    result = score(truth, raw, final, membership)
    assert result["post_hitl"]["true_stp_claims"] == 0
    if wrong_stage == "raw":
        assert result["raw"]["declared_stp"] == 1
        assert result["raw"]["false_stp_claims"] == 1


def test_declared_stp_with_human_work_is_counted_as_false_stp():
    from tests.unit.cases.test_qualification_closure_inputs import snapshots
    from tests.unit.cases.test_release_scoring_cost_closure import seal

    truth, raw, _, membership, score = snapshots()
    raw["claims"]["claim"]["human_reviewed"] = True
    seal(raw)
    metrics = score(truth, raw, None, membership)["raw"]
    assert metrics["declared_stp"] == 1
    assert metrics["stp_safe"] == 0
    assert metrics["false_stp_claims"] == 1


def test_missing_source_inventory_fails_explicitly_without_fabricated_scores(tmp_path):
    from evaluation.real_evaluation_program import build_real_evaluation_program

    with pytest.raises(ValueError, match="SOURCE_CLOSURE_INPUTS_REQUIRED"):
        build_real_evaluation_program(closure_dir=tmp_path / "missing", output_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()
