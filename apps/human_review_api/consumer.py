"""Persist field-scoped HITL tasks from fail-closed extraction events."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid5

from apps.human_review_api.db.repository import ReviewTaskRepository
from packages.domain.review import ReviewTask
from packages.events.bus import EventBus
from packages.events.envelope import EventEnvelope
from packages.events.topics import Topic

logger = logging.getLogger(__name__)
CONSUMER_GROUP = "human-review-task-worker"
TASK_NAMESPACE = UUID("4a76425e-5dc7-4bd2-9fc5-2e3c72273be4")


class HumanReviewTaskWorker:
    def __init__(self, event_bus: EventBus, session_factory) -> None:
        self._event_bus = event_bus
        self._session_factory = session_factory

    async def handle_one(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        document_id = envelope.document_id
        if document_id is None:
            raise ValueError("human review event requires document_id")
        field_id = UUID(str(payload["field_id"]))
        claim_id = envelope.claim_id or envelope.correlation_id
        task_id = uuid5(TASK_NAMESPACE, f"{document_id}:{field_id}")
        with self._session_factory() as session:
            repository = ReviewTaskRepository(session)
            if repository.get_for_field(document_id, field_id) is not None:
                return
            repository.add(
                ReviewTask(
                    task_id=task_id,
                    claim_id=claim_id,
                    document_id=document_id,
                    field_id=field_id,
                    field_name=str(payload["field_name"]),
                    page_number=int(payload["page_number"]),
                    ocr_candidates=[str(value) for value in payload.get("ocr_candidates", [])],
                    validation_errors=[
                        str(value) for value in payload.get("validation_errors", [])
                    ],
                    review_reason_codes=payload.get("review_reason_codes", []),
                    candidate_evidence=list(payload.get("candidate_evidence", [])),
                    reference_evidence=list(payload.get("reference_evidence", [])),
                    registration_evidence=dict(payload.get("registration_evidence", {})),
                    system_recommendation=payload.get("system_recommendation"),
                    evidence_versions={
                        str(key): str(value)
                        for key, value in payload.get("evidence_versions", {}).items()
                    },
                )
            )
            session.commit()

    async def run_forever(self) -> None:
        async for _topic, envelope in self._event_bus.subscribe(
            [Topic.HUMAN_REVIEW_REQUESTED.value], group_id=CONSUMER_GROUP
        ):
            try:
                await self.handle_one(envelope)
            except Exception:
                logger.exception("failed to persist human review task")


def main() -> None:
    from apps.human_review_api.db.session import make_session_factory
    from packages.events.bus import AIOKafkaEventBus
    from packages.observability import configure_logging
    from packages.settings import get_settings

    configure_logging("human-review-task-worker")
    settings = get_settings()
    worker = HumanReviewTaskWorker(
        AIOKafkaEventBus(settings.kafka_bootstrap_servers),
        make_session_factory(settings.database_url),
    )
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()
