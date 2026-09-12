"""Runtime wiring for the document_preparation worker: consume
`document.received`, decode + preprocess every page, persist them, then
outbox `document.prepared`.

Deliberately shares the `apps.ingestion_api.db` persistence module with the
ingestion API for Phase 1 (documented simplification — see
docs/ARCHITECTURE.md §1). The EventBus/outbox boundary between intake and
preparation is real, though: this worker is a separate OS process reachable
only through Kafka, exactly as it would be in production.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from apps.ingestion_api.db.repository import (
    DocumentRepository,
    PageRepository,
    SqlAlchemyOutboxRepository,
)
from packages.domain.enums import DocumentStatus
from packages.events.bus import EventBus
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord
from packages.events.topics import Topic
from packages.storage.object_store import ObjectStore
from workers.document_preparation.pipeline import DocumentPreparationService

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "document-preparation-worker"


class DocumentPreparationWorker:
    def __init__(
        self,
        event_bus: EventBus,
        object_store: ObjectStore,
        bucket: str,
        session_factory: sessionmaker,
        pipeline_version: str,
    ) -> None:
        self._event_bus = event_bus
        self._object_store = object_store
        self._bucket = bucket
        self._session_factory = session_factory
        self._pipeline_version = pipeline_version
        self._preparation = DocumentPreparationService(object_store, bucket)

    async def handle_one(self, envelope: EventEnvelope) -> None:
        document_id = envelope.document_id
        if document_id is None:
            logger.warning("document.received event missing document_id, skipping")
            return

        with self._session_factory() as session:
            documents = DocumentRepository(session)
            pages_repo = PageRepository(session)
            outbox = SqlAlchemyOutboxRepository(session)

            document = documents.get(document_id)
            if document is None:
                logger.warning("document %s not found, skipping", document_id)
                return

            # Both calls are blocking (boto3 I/O, then CPU-bound PIL/OpenCV
            # decode+preprocess across every page) -- run them off the
            # event loop so aiokafka's heartbeat/poll background task isn't
            # starved. Doing this synchronously on the loop was observed to
            # exceed the consumer group's poll interval under a burst of
            # real multi-page documents, getting the worker kicked from its
            # consumer group mid-stream (CommitFailedError / rebalance).
            raw_bytes = await asyncio.to_thread(
                self._object_store.get_bytes, document.original_object
            )
            pages = await asyncio.to_thread(self._preparation.prepare, document, raw_bytes)
            pages_repo.add_all(pages)

            document.status = DocumentStatus.PREPARED
            document.page_count = len(pages)
            document.updated_at = datetime.now(UTC)
            documents.update(document)

            envelope_out = EventEnvelope(
                event_type=Topic.DOCUMENT_PREPARED.value,
                correlation_id=envelope.correlation_id,
                document_id=document.document_id,
                pipeline_version=self._pipeline_version,
                payload={
                    "document_id": str(document.document_id),
                    "page_count": len(pages),
                },
            )
            await outbox.add(
                OutboxRecord(
                    topic=Topic.DOCUMENT_PREPARED.value,
                    envelope=envelope_out,
                    partition_key=str(document.document_id),
                )
            )
            session.commit()

    async def run_forever(self) -> None:
        async for _topic, envelope in self._event_bus.subscribe(
            [Topic.DOCUMENT_RECEIVED.value], group_id=CONSUMER_GROUP
        ):
            try:
                await self.handle_one(envelope)
            except Exception:
                logger.exception("failed to prepare document_id=%s", envelope.document_id)
                raise


def main() -> None:
    from apps.ingestion_api.db.session import make_session_factory
    from packages.events.bus import AIOKafkaEventBus
    from packages.observability import configure_logging
    from packages.settings import get_settings
    from packages.storage.object_store import ObjectStoreSettings

    configure_logging("document-preparation-worker")
    settings = get_settings()
    event_bus = AIOKafkaEventBus(settings.kafka_bootstrap_servers)
    object_store = ObjectStore(
        ObjectStoreSettings(
            endpoint_url=settings.object_store_endpoint,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
            use_ssl=settings.object_store_use_ssl,
        )
    )
    worker = DocumentPreparationWorker(
        event_bus=event_bus,
        object_store=object_store,
        bucket=settings.object_store_bucket,
        session_factory=make_session_factory(settings.database_url),
        pipeline_version=settings.pipeline_version,
    )
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()
