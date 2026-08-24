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
from packages.evidence_decision import DecisionContext, EvidenceDecisionService
from packages.evidence_decision.contracts import FieldDisposition
from packages.events.bus import EventBus
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord
from packages.events.topics import Topic
from packages.storage.object_store import ObjectStore
from packages.layout_intelligence import BundleDLayoutEngine
from packages.extraction_routing import ExtractionTarget, extraction_target
from packages.ocr.contracts import OCRCandidate
from packages.runtime_profile import DecisionServiceFactory
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
                 text_extractor, family_config: Path = DEFAULT_FAMILY_CONFIG,
                 layout_engine: BundleDLayoutEngine | None = None,
                 decision_service: EvidenceDecisionService | None = None) -> None:
        self._event_bus = event_bus
        self._object_store = object_store
        self._session_factory = session_factory
        self._pipeline_version = pipeline_version
        self._text_extractor = text_extractor
        self._config = yaml.safe_load(family_config.read_text(encoding="utf-8"))
        self._family_router = DocumentFamilyRouter(self._config)
        self._layout_engine = layout_engine or BundleDLayoutEngine()
        decision_bundle = DecisionServiceFactory.from_profile()
        self._decisions = decision_service or decision_bundle.evidence_decision
        self._criticality = decision_bundle.criticality

    async def handle_one(self, envelope: EventEnvelope) -> None:
        if envelope.document_id is None:
            return
        document_id = envelope.document_id
        processing_route=envelope.payload.get("processing_route")
        force_layout_graph=False
        if processing_route is not None:
            target=extraction_target(processing_route)
            if target not in {ExtractionTarget.UNKNOWN_STRUCTURED_LAYOUT,
                              ExtractionTarget.UNKNOWN_UNSTRUCTURED_LAYOUT}:
                raise ValueError(f"PROCESSING_ROUTE_TARGET_MISMATCH:{processing_route}:{target.value}")
            force_layout_graph=target is ExtractionTarget.UNKNOWN_STRUCTURED_LAYOUT
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
            if family.family and family.page_number and not force_layout_graph:
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
            layout_results = []
            if not extracted:
                # Generic extraction is a fallback only. Known recurring Bundle-D
                # families retain their current behavior and standard CMS/UB never
                # enter this worker.
                for page_number, image in images.items():
                    result = self._layout_engine.extract(
                        page_lines[page_number], page_number=page_number,
                        width=image.width, height=image.height,
                        engine=getattr(self._text_extractor, "engine_name", "full_page_ocr"),
                    )
                    layout_results.append(result)
                    for field_name, candidates in result.candidates.items():
                        best = candidates[0]
                        ocr_candidates = [OCRCandidate(
                            value=item.value, raw_value=item.value,
                            engine=result.engine, model_name=getattr(self._text_extractor, "model_name", result.engine),
                            model_version=getattr(self._text_extractor, "model_version", "unknown"),
                            preprocessing_variant="prepared_full_page",
                            raw_confidence=item.confidence, calibrated_confidence=None,
                            bounding_box=item.bbox, latency_ms=0,
                            validation_results=(
                                "DATATYPE_VALID", item.relationship_evidence.relationship,
                            ) if item.datatype_valid else (item.relationship_evidence.relationship,),
                            evidence_reference=f"layout:{item.relationship_evidence.relationship}",
                        ) for item in candidates]
                        decision = self._decisions.decide(DecisionContext(
                            field_name=field_name,
                            document_family=result.schema_evidence.schema_family,
                            criticality=self._criticality.for_field(field_name),
                            candidates=ocr_candidates,
                            deterministic_evidence={"DATATYPE_VALID"} if best.datatype_valid else set(),
                            hard_validation_passed=best.datatype_valid,
                            structural_evidence_source=best.relationship_evidence.relationship,
                        ))
                        evidence = [FieldEvidence(
                            source=ExtractionMethod.ALTERNATE_PREPROCESS_OCR,
                            raw_text=item.value, confidence=item.confidence,
                            bounding_box=item.bbox,
                            model_name=getattr(self._text_extractor, "model_name", result.engine),
                            model_version=getattr(self._text_extractor, "model_version", "unknown"),
                        ) for item in candidates]
                        accepted = decision.disposition in {
                            FieldDisposition.AUTO_ACCEPTED,
                            FieldDisposition.REFERENCE_CONFIRMED,
                        }
                        extracted.append(ExtractedField(
                            field_name=field_name, raw_value=best.value,
                            normalized_value=best.value, confidence=best.confidence,
                            page_number=page_number, bounding_box=best.bbox,
                            extraction_method=ExtractionMethod.ALTERNATE_PREPROCESS_OCR,
                            validation_status=(ValidationStatus.VALID if accepted else ValidationStatus.NEEDS_REVIEW),
                            validation_reasons=list(dict.fromkeys([
                                f"E3:{best.relationship_evidence.relationship}",
                                f"LABEL_ALIAS:{best.matched_alias}", *decision.reason_codes,
                            ])), candidates=evidence,
                            disposition=decision.disposition.value,
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
                             "document_family": family.family or (
                                 layout_results[0].schema_evidence.schema_family if layout_results else "unknown_unstructured"
                             ),
                             "family_confidence": family.score or (
                                 layout_results[0].schema_evidence.confidence if layout_results else 0.0
                             ),
                             "generic_route": layout_results[0].route.value if layout_results else None,
                             "route_reason_codes": layout_results[0].route_reason_codes if layout_results else [],
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
    from workers.page_detection.text_extraction import PaddleOCRTextExtractor
    from workers.cascade.instrumented_text_extractor import (
        CachedInstrumentedTextExtractor, JsonlOCRAuditSink,
    )
    configure_logging("unstructured-extraction-worker")
    settings = get_settings()
    worker = UnstructuredExtractionWorker(
        AIOKafkaEventBus(settings.kafka_bootstrap_servers),
        ObjectStore(ObjectStoreSettings(endpoint_url=settings.object_store_endpoint,
                    access_key=settings.object_store_access_key, secret_key=settings.object_store_secret_key,
                    use_ssl=settings.object_store_use_ssl)),
        make_session_factory(settings.database_url), settings.pipeline_version,
        # Full-page geometry is intentional only for Bundle D. The Phase-5
        # development benchmark promoted Paddle over RapidOCR; known forms
        # retain their regional OCR path.
        CachedInstrumentedTextExtractor(
            PaddleOCRTextExtractor(), audit_sink=JsonlOCRAuditSink(settings.ocr_audit_path)
        ),
    )
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()
