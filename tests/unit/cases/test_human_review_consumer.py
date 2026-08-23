from uuid import uuid4

import pytest

from apps.human_review_api.consumer import HumanReviewTaskWorker
from apps.human_review_api.db.repository import ReviewTaskRepository
from apps.human_review_api.db.session import make_session_factory
from packages.events.bus import InMemoryEventBus
from packages.events.envelope import EventEnvelope
from packages.events.topics import Topic


@pytest.mark.asyncio
async def test_review_event_creates_one_idempotent_field_task() -> None:
    session_factory = make_session_factory()
    worker = HumanReviewTaskWorker(InMemoryEventBus(), session_factory)
    document_id, correlation_id, field_id = uuid4(), uuid4(), uuid4()
    event = EventEnvelope(
        event_type=Topic.HUMAN_REVIEW_REQUESTED.value,
        correlation_id=correlation_id,
        document_id=document_id,
        pipeline_version="test",
        payload={
            "field_id": str(field_id),
            "field_name": "patient_first",
            "page_number": 1,
            "ocr_candidates": ["MATHFW", "MATHEW"],
            "validation_errors": ["consensus_gate_failed"],
            "blocks_stp": True,
            "claim_impact": "THIS FIELD BLOCKS CLAIM STP",
            "single_blocker_claim": True,
            "blocking_field_count": 1,
            "claim_unlock_value": 1.0,
        },
    )
    await worker.handle_one(event)
    await worker.handle_one(event)
    with session_factory() as session:
        tasks = ReviewTaskRepository(session).list_for_claim(correlation_id)
    assert len(tasks) == 1
    assert tasks[0].field_id == field_id
    assert tasks[0].ocr_candidates == ["MATHFW", "MATHEW"]
    assert tasks[0].blocks_stp is True
    assert tasks[0].claim_impact == "THIS FIELD BLOCKS CLAIM STP"
    assert tasks[0].single_blocker_claim is True
    assert tasks[0].blocking_field_count == 1
    assert tasks[0].claim_unlock_value == 1.0
