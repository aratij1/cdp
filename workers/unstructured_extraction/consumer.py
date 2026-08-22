"""Live Bundle D consumer using family anchors and crop-local OCR evidence."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy.orm import sessionmaker

from apps.ingestion_api.db.repository import (
    DocumentRepository, ExtractedFieldRepository, PageRepository, SqlAlchemyOutboxRepository,
)
from packages.domain.common import BoundingBox
from packages.domain.enums import DocumentStatus, ExtractionMethod, ValidationStatus
from packages.domain.extraction import ExtractedField, FieldEvidence
from packages.events.bus import EventBus
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord
from packages.events.topics import Topic
from packages.storage.object_store import ObjectStore
from workers.page_detection.consumer import _load_image
from workers.standard_form_extraction.field_processors import normalize
from workers.unstructured_extraction.anchor_cropper import extract_anchor_crops
from workers.unstructured_extraction.family_router import DocumentFamilyRouter

logger = logging.getLogger(__name__)
CONSUMER_GROUP = "unstructured-extraction-worker"
DEFAULT_FAMILY_CONFIG = Path("config/unstructured_document_families.yaml")


class UnstructuredExtractionWorker:
    def __init__(self, event_bus: EventBus, object_store: ObjectStore,
                 session_factory: sessionmaker, pipeline_version: str,
                 text_extractor, family_config: Path = DEFAULT_FAMILY_CONFIG) -> None:
        self._event_bus = event_bus
        self._object_store = object_store
        self._session_factory = session_factory
        self._pipeline_version = pipeline_version
        self._text_extractor = text_extractor
        self._config = yaml.safe_load(family_config.read_text(encoding="utf-8"))
        self._family_router = DocumentFamilyRouter(self._config)

    async def handle_one(self, envelope: EventEnvelope) -> None:
        if envelope.document_id is None:
            return
        document_id = envelope.document_id
        with self._session_factory() as session:
            documents = DocumentRepository(session)
            pages_repo = PageRepository(session)
            fields_repo = ExtractedFieldRepository(session)
            outbox = SqlAlchemyOutboxRepository(session)
            document = documents.get(document_id)
            if document is None:
                return
            requested = set(envelope.payload.get("page_numbers") or [])
            pages = [p for p in pages_repo.list_for_document(document_id)
                     if not requested or p.page_number in requested]
            images = {p.page_number: await asyncio.to_thread(
                _load_image, self._object_store, p.extraction_object
            ) for p in pages}
            page_lines = {number: await asyncio.to_thread(
                self._text_extractor.extract, image
            ) for number, image in images.items()}
            family = self._family_router.route(page_lines)
            extracted: list[ExtractedField] = []
            if family.family and family.page_number:
                specs = self._config["families"][family.family].get("fields", {})
                image = images[family.page_number]
                crops = extract_anchor_crops(image, page_lines[family.page_number], specs)
                for field_name, crop in crops.items():
                    lines = await asyncio.to_thread(self._text_extractor.extract, crop.crop)
                    value = " ".join(line.text for line in sorted(lines, key=lambda x: (x.y0, x.x0)))
                    confidence = sum(line.confidence for line in lines) / len(lines) if lines else 0.0
                    field_type = specs[field_name].get("field_type", "text")
                    normalized, valid = normalize(field_type, value)
                    box = BoundingBox(x0=crop.box[0], y0=crop.box[1], x1=crop.box[2], y1=crop.box[3],
                                      image_width=image.width, image_height=image.height)
                    evidence = FieldEvidence(source=ExtractionMethod.ALTERNATE_PREPROCESS_OCR,
                                             raw_text=value, confidence=confidence, bounding_box=box)
                    extracted.append(ExtractedField(
                        field_name=field_name, raw_value=value, normalized_value=normalized,
                        confidence=confidence, page_number=family.page_number, bounding_box=box,
                        extraction_method=ExtractionMethod.ALTERNATE_PREPROCESS_OCR,
                        validation_status=ValidationStatus.PENDING if valid and value else ValidationStatus.NEEDS_REVIEW,
                        validation_reasons=[] if valid and value else ["UNSTRUCTURED_FIELD_UNRESOLVED"],
                        candidates=[evidence],
                    ))
            fields_repo.add_all(document_id, extracted)
            document.status = DocumentStatus.VALIDATING
            document.updated_at = datetime.now(UTC)
            documents.update(document)
            await outbox.add(OutboxRecord(
                topic=Topic.EXTRACTION_COMPLETED.value,
                envelope=EventEnvelope(
                    event_type=Topic.EXTRACTION_COMPLETED.value,
                    correlation_id=envelope.correlation_id, document_id=document_id,
                    claim_id=document.claim_id, pipeline_version=self._pipeline_version,
                    payload={"document_id": str(document_id), "field_count": len(extracted),
                             "document_family": family.family or "unknown_unstructured",
                             "family_confidence": family.score,
                             "reason_codes": [] if extracted else ["UNSTRUCTURED_SCHEMA_OR_ANCHOR_UNRESOLVED"]},
                ), partition_key=str(document_id),
            ))
            session.commit()

    async def run_forever(self) -> None:
        async for _topic, envelope in self._event_bus.subscribe(
            [Topic.EXTRACTION_UNSTRUCTURED_REQUESTED.value], group_id=CONSUMER_GROUP
        ):
            try:
                await self.handle_one(envelope)
            except Exception:
                logger.exception("failed Bundle D extraction for document_id=%s", envelope.document_id)


def main() -> None:
    from apps.ingestion_api.db.session import make_session_factory
    from packages.events.bus import AIOKafkaEventBus
    from packages.observability import configure_logging
    from packages.settings import get_settings
    from packages.storage.object_store import ObjectStoreSettings
    from workers.cascade.tesseract_adapter import TesseractTextExtractor
    configure_logging("unstructured-extraction-worker")
    settings = get_settings()
    worker = UnstructuredExtractionWorker(
        AIOKafkaEventBus(settings.kafka_bootstrap_servers),
        ObjectStore(ObjectStoreSettings(endpoint_url=settings.object_store_endpoint,
                    access_key=settings.object_store_access_key, secret_key=settings.object_store_secret_key,
                    use_ssl=settings.object_store_use_ssl)),
        make_session_factory(settings.database_url), settings.pipeline_version,
        TesseractTextExtractor(psm=11),
    )
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()
