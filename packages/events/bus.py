"""Kafka-compatible event bus abstraction.

Workers and apps depend only on `EventBus` (a `Protocol`). Two
implementations are provided:

- `InMemoryEventBus`: synchronous, in-process, used in unit/integration
  tests and local dev without Docker running.
- `AIOKafkaEventBus`: talks to any Kafka-protocol broker (Redpanda locally,
  Kafka/MSK/Confluent in higher environments) via `aiokafka`, chosen
  because it is a pure-Python client with no `librdkafka` build
  dependency.

Neither implementation is imported directly by worker code outside this
package — construct the bus once (e.g. in each service's `main.py`) and pass
the `EventBus` interface down.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from packages.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, topic: str, envelope: EventEnvelope, key: str | None = None) -> None:
        """Publish one event. Must validate no raw bytes are in the payload."""
        ...

    def subscribe(
        self, topics: list[str], group_id: str
    ) -> AsyncIterator[tuple[str, EventEnvelope]]:
        """Yield (topic, envelope) pairs for the given consumer group."""
        ...

    async def close(self) -> None: ...


class InMemoryEventBus:
    """Fan-out, in-process event bus. Each (topic, group_id) pair gets its
    own queue so multiple consumer groups can each see every message,
    matching Kafka consumer-group semantics closely enough for tests."""

    def __init__(self) -> None:
        self._queues: dict[tuple[str, str], asyncio.Queue] = {}
        self._known_groups: dict[str, set[str]] = {}
        self.published: list[tuple[str, EventEnvelope]] = []

    def _register_group(self, topic: str, group_id: str) -> asyncio.Queue:
        key = (topic, group_id)
        if key not in self._queues:
            self._queues[key] = asyncio.Queue()
            self._known_groups.setdefault(topic, set()).add(group_id)
        return self._queues[key]

    async def publish(self, topic: str, envelope: EventEnvelope, key: str | None = None) -> None:
        envelope.assert_no_bytes_payload()
        self.published.append((topic, envelope))
        for group_id in self._known_groups.get(topic, set()):
            await self._queues[(topic, group_id)].put(envelope)

    async def subscribe(
        self, topics: list[str], group_id: str
    ) -> AsyncIterator[tuple[str, EventEnvelope]]:
        queues = {topic: self._register_group(topic, group_id) for topic in topics}
        while True:
            get_tasks = {asyncio.create_task(q.get()): topic for topic, q in queues.items()}
            done, pending = await asyncio.wait(
                get_tasks.keys(), return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                topic = get_tasks[task]
                yield topic, task.result()

    async def close(self) -> None:
        return None


class AIOKafkaEventBus:
    """Real Kafka-protocol implementation, backed by `aiokafka`."""

    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._producer = None
        self._consumers: list = []

    async def _ensure_producer(self):
        if self._producer is None:
            from aiokafka import AIOKafkaProducer

            self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
            await self._producer.start()
        return self._producer

    async def publish(self, topic: str, envelope: EventEnvelope, key: str | None = None) -> None:
        envelope.assert_no_bytes_payload()
        producer = await self._ensure_producer()
        value = envelope.model_dump_json().encode("utf-8")
        key_bytes = key.encode("utf-8") if key else None
        await producer.send_and_wait(topic, value=value, key=key_bytes)

    async def subscribe(
        self, topics: list[str], group_id: str
    ) -> AsyncIterator[tuple[str, EventEnvelope]]:
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=self._bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=False,
            # Generous headroom for slow/CPU-heavy handlers (e.g. multipage
            # image decode+preprocess) on top of offloading that work to a
            # thread (see workers/document_preparation/consumer.py) -- belt
            # and suspenders against a consumer-group kick mid-processing.
            max_poll_interval_ms=15 * 60 * 1000,
        )
        await consumer.start()
        self._consumers.append(consumer)
        try:
            async for msg in consumer:
                envelope = EventEnvelope.model_validate_json(msg.value)
                yield msg.topic, envelope
                await consumer.commit()
        finally:
            await consumer.stop()

    async def close(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
        for consumer in self._consumers:
            await consumer.stop()
