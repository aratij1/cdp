"""A failed worker must not resume Kafka's generator and commit the message."""

import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.human_review_api.consumer import HumanReviewTaskWorker
from packages.events.bus import AIOKafkaEventBus
from packages.events.envelope import EventEnvelope
from workers.document_preparation.consumer import DocumentPreparationWorker
from workers.output_generation.consumer import OutputGenerationWorker
from workers.page_detection.consumer import PageDetectionWorker
from workers.retry.consumer import RetryWorker
from workers.standard_form_extraction.consumer import StandardFormExtractionWorker
from workers.unstructured_extraction.consumer import UnstructuredExtractionWorker
from workers.validation.consumer import ValidationWorker

WORKERS = [
    DocumentPreparationWorker,
    PageDetectionWorker,
    StandardFormExtractionWorker,
    UnstructuredExtractionWorker,
    ValidationWorker,
    RetryWorker,
    OutputGenerationWorker,
    HumanReviewTaskWorker,
]


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_class", WORKERS)
@pytest.mark.parametrize("fails", [True, False])
async def test_kafka_commits_only_successful_handlers(monkeypatch, worker_class, fails):
    envelope = EventEnvelope(
        event_type="synthetic",
        document_id=uuid4(),
        correlation_id=uuid4(),
        pipeline_version="test",
        payload={},
    )
    committed = []

    class Consumer:
        def __init__(self, *args, **kwargs):
            assert kwargs["enable_auto_commit"] is False

        async def start(self):
            pass

        async def stop(self):
            pass

        async def commit(self):
            committed.append(True)

        def __aiter__(self):
            async def messages():
                yield SimpleNamespace(topic="synthetic", value=envelope.model_dump_json().encode())

            return messages()

    monkeypatch.setitem(sys.modules, "aiokafka", SimpleNamespace(AIOKafkaConsumer=Consumer))
    worker = object.__new__(worker_class)
    worker._event_bus = AIOKafkaEventBus("synthetic:9092")

    async def handle(event):
        if fails:
            raise RuntimeError("SYNTHETIC_HANDLER_FAILURE")

    worker.handle_one = handle
    if fails:
        with pytest.raises(RuntimeError, match="SYNTHETIC_HANDLER_FAILURE"):
            await worker.run_forever()
        assert committed == []
    else:
        await worker.run_forever()
        assert committed == [True]
