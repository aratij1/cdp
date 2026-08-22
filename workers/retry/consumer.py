"""Retry/escalation worker: consumes `field.retry.requested`, uses `ModelRouter`
to pick the next stage, and executes it. Outboxes either another `field.retry.requested`
(if still unresolved but attempts remain) or `human.review.requested` (if exhausted).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from apps.ingestion_api.db.mappers import orm_to_extracted_field
from apps.ingestion_api.db.models import ExtractedFieldORM
from apps.ingestion_api.db.repository import (
    DocumentRepository,
    SqlAlchemyOutboxRepository,
)
from packages.criticality import DEFAULT_CRITICALITY_PATH, CriticalityLevel, CriticalityPolicy
from packages.domain.enums import ExtractionMethod, FieldCriticality
from packages.domain.extraction import FieldEvidence
from packages.evidence_decision import (
    DecisionContext, EvidenceDecisionService, FieldDisposition, NextAction,
)
from packages.evidence_decision.adapters import ocr_candidates_from_field
from packages.events.bus import EventBus
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord
from packages.events.topics import Topic
from packages.model_router.inputs import RouterInput
from packages.model_router.router import ModelRouter
from packages.storage.object_store import ObjectStore, ObjectStoreSettings
from workers.page_detection.text_extraction import PaddleOCRTextExtractor
from workers.retry.retry_service import retry_field
from workers.retry.alternate_preprocessing import PreprocessingContext
from workers.unstructured_extraction.layoutlmv3_adapter import (
    LayoutLMv3Adapter,
)
from workers.unstructured_extraction.table_transformer_adapter import TableTransformerAdapter
from workers.vlm_fallback.adapter import VLMAdapter

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "retry-worker"


def _field_type(field_name: str) -> str:
    name = field_name.casefold()
    if "date" in name:
        return "date"
    if any(token in name for token in ("charge", "amount", "total", "units")):
        return "currency" if "units" not in name else "number"
    if any(token in name for token in ("code", "npi", "id", "number")):
        return "code"
    return "text"


class RetryWorker:
    def __init__(
        self,
        event_bus: EventBus,
        object_store: ObjectStore,
        session_factory: sessionmaker,
        pipeline_version: str,
        vlm_enabled: bool = False,
        decision_service: EvidenceDecisionService | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._object_store = object_store
        self._session_factory = session_factory
        self._pipeline_version = pipeline_version
        self._router = ModelRouter(vlm_enabled=vlm_enabled)
        self._vlm_enabled = vlm_enabled
        self._decision_service = decision_service or EvidenceDecisionService()
        self._criticality = CriticalityPolicy.load(DEFAULT_CRITICALITY_PATH)

    async def handle_one(self, envelope: EventEnvelope) -> None:
        document_id = envelope.document_id
        field_id_str = envelope.payload.get("field_id")
        if not document_id or not field_id_str:
            logger.warning("field.retry.requested event missing document_id or field_id, skipping")
            return

        with self._session_factory() as session:
            documents = DocumentRepository(session)
            outbox = SqlAlchemyOutboxRepository(session)

            document = documents.get(document_id)
            if document is None:
                logger.warning("document %s not found, skipping", document_id)
                return

            from sqlalchemy import select
            stmt = select(ExtractedFieldORM).where(ExtractedFieldORM.field_id == UUID(field_id_str))
            field_orm = session.execute(stmt).scalar_one_or_none()
            if not field_orm:
                logger.warning("field %s not found, skipping", field_id_str)
                return

            field = orm_to_extracted_field(field_orm)

            # Build attempted methods from candidates
            attempted = set()
            for cand in field.candidates:
                attempted.add(cand.source)
            attempted.add(field.extraction_method)
            
            router_input = RouterInput(
                field_name=field.field_name,
                field_criticality=FieldCriticality.CRITICAL if field.is_critical else FieldCriticality.NON_CRITICAL,
                ocr_confidence=field.confidence,
                validation_failed=bool(field.validation_reasons),
                ocr_disagreement=False,
                cache_hit=False,
                is_table_field=(field_orm.service_line_number is not None),
                is_unstructured_document=(document.bundle_type == "D_UNSTRUCTURED"),
                vlm_enabled=self._vlm_enabled,
                attempted_methods=frozenset(attempted)
            )

            decision = self._router.decide(router_input)
            next_stage = decision.selected_route
            
            if next_stage in (
                ExtractionMethod.ALTERNATE_PREPROCESS_OCR,
                ExtractionMethod.LAYOUTLMV3,
                ExtractionMethod.TABLE_TRANSFORMER,
                ExtractionMethod.VLM_FALLBACK,
            ):
                import io

                from workers.document_preparation.codecs import decode_pdf_pages
                from PIL import Image
                
                raw_bytes = await asyncio.to_thread(self._object_store.get_bytes, document.original_object)
                if "pdf" in document.detected_format.value.lower():
                    pages = decode_pdf_pages(raw_bytes)
                    page_image = pages[field.page_number - 1].image
                else:
                    page_image = Image.open(io.BytesIO(raw_bytes))
                
                bbox = field.bounding_box
                if bbox:
                    region = (int(bbox.x0), int(bbox.y0), int(bbox.x1), int(bbox.y1))
                else:
                    region = (0, 0, page_image.width, page_image.height)

                new_confidence = 0.0
                new_text = ""
                new_source = next_stage

                try:
                    if next_stage == ExtractionMethod.ALTERNATE_PREPROCESS_OCR:
                        extractor = PaddleOCRTextExtractor()
                        quality = envelope.payload.get("image_quality") or {}
                        registration = envelope.payload.get("registration_evidence") or {}
                        reasons = field.validation_reasons or envelope.payload.get("reason_codes", [])
                        context = PreprocessingContext(
                            field_type=_field_type(field.field_name),
                            quality_score=quality.get("overall_score") if isinstance(quality, dict) else None,
                            failure_reason=reasons[0] if reasons else None,
                            registration_confidence=(
                                registration.get("confidence")
                                if isinstance(registration, dict) else None
                            ),
                        )
                        res = await asyncio.to_thread(
                            retry_field, page_image, region, extractor, field.confidence,
                            context,
                        )
                        if res.improved:
                            new_text = res.text
                            new_confidence = res.confidence
                    elif next_stage == ExtractionMethod.LAYOUTLMV3:
                        adapter = LayoutLMv3Adapter()
                        res = await asyncio.to_thread(adapter.extract, page_image, [field.field_name])
                        if res:
                            new_text = res[0].value
                            new_confidence = res[0].confidence
                    elif next_stage == ExtractionMethod.TABLE_TRANSFORMER:
                        adapter = TableTransformerAdapter()
                    elif next_stage == ExtractionMethod.VLM_FALLBACK:
                        crop = page_image.crop(region)
                        adapter = VLMAdapter()
                        from workers.vlm_fallback.schema import VLMFieldSchema
                        schema = VLMFieldSchema(field_name=field.field_name, type="string", description="")
                        res = await asyncio.to_thread(adapter.extract_fields, crop, [schema], "")
                        if field.field_name in res:
                            new_text = str(res[field.field_name])
                            new_confidence = 1.0
                except Exception:
                    logger.exception("Failed to run adapter %s", next_stage)

                # Retry providers only append evidence. They never overwrite the
                # canonical value before the common decision service authorizes it.
                retry_evidence = FieldEvidence(
                    source=new_source,
                    raw_text=new_text,
                    confidence=new_confidence,
                    bounding_box=field.bounding_box,
                )
                field.candidates.append(retry_evidence)
                field_orm.candidates = [
                    *(field_orm.candidates or []), retry_evidence.model_dump(mode="json")
                ]
                
                if next_stage == ExtractionMethod.ALTERNATE_PREPROCESS_OCR:
                    from packages.observability.metrics import retry_total
                    retry_total.labels(improved=str(bool(new_text))).inc()
                elif next_stage == ExtractionMethod.VLM_FALLBACK:
                    from packages.observability.metrics import vlm_invocation_total
                    vlm_invocation_total.labels(insufficient_evidence="false").inc()

            level = self._criticality.for_field(field.field_name)
            hard_validation_passed = bool(envelope.payload.get("hard_validation_passed", False))
            decision = self._decision_service.decide(DecisionContext(
                field_name=field.field_name,
                document_family="UNSTRUCTURED" if document.bundle_type == "D_UNSTRUCTURED" else "*",
                criticality=level,
                blocks_stp=level in {CriticalityLevel.C2, CriticalityLevel.C3},
                candidates=ocr_candidates_from_field(field),
                deterministic_evidence={"HARD_VALIDATION_PASSED"} if hard_validation_passed else set(),
                hard_validation_passed=hard_validation_passed,
                wrong_crop_suspected="WRONG_CROP_SUSPECTED" in set(field.validation_reasons),
            ))
            accepted = decision.disposition in {
                FieldDisposition.AUTO_ACCEPTED, FieldDisposition.REFERENCE_CONFIRMED,
            }
            if accepted and decision.selected_value is not None:
                field_orm.raw_value = decision.selected_value
                field_orm.normalized_value = decision.selected_value
                field_orm.confidence = decision.calibrated_probability
                field_orm.disposition = decision.disposition.value
                field_orm.validation_status = "VALID"
                field_orm.validation_reasons = decision.reason_codes
                env_out = EventEnvelope(
                    event_type=Topic.EXTRACTION_COMPLETED.value,
                    correlation_id=envelope.correlation_id,
                    document_id=document_id,
                    claim_id=document.claim_id,
                    pipeline_version=self._pipeline_version,
                    payload={"field_id": str(field.field_id), "decision_policy": decision.policy_version},
                )
                await outbox.add(OutboxRecord(
                    topic=Topic.EXTRACTION_COMPLETED.value, envelope=env_out,
                    partition_key=str(document_id),
                ))
            elif next_stage == ExtractionMethod.HUMAN_REVIEW or decision.next_action is NextAction.HUMAN_REVIEW:
                from packages.observability.metrics import human_review_total
                reason_str = decision.reason_codes[0] if decision.reason_codes else "unknown"
                human_review_total.labels(reason=reason_str).inc()
                
                env_out = EventEnvelope(
                    event_type=Topic.HUMAN_REVIEW_REQUESTED.value,
                    correlation_id=envelope.correlation_id,
                    document_id=document_id,
                    claim_id=document.claim_id,
                    pipeline_version=self._pipeline_version,
                    payload={
                        "field_id": str(field.field_id),
                        "field_name": field.field_name,
                        "page_number": field.page_number,
                        "review_reason_codes": decision.reason_codes,
                        "validation_errors": field.validation_reasons,
                        "ocr_candidates": [candidate.raw_text for candidate in field.candidates],
                        "candidate_evidence": [candidate.model_dump(mode="json") for candidate in field.candidates],
                        "system_recommendation": decision.selected_value,
                        "available_evidence": decision.available_evidence,
                        "missing_evidence": decision.missing_evidence,
                        "evidence_bundle": (
                            decision.evidence_bundle.model_dump(mode="json")
                            if decision.evidence_bundle else None
                        ),
                        "required_policy": self._decision_service.evidence_policy.version,
                        "evidence_versions": {"decision_policy": decision.policy_version},
                    },
                )
                await outbox.add(OutboxRecord(topic=Topic.HUMAN_REVIEW_REQUESTED.value, envelope=env_out, partition_key=str(document_id)))
            else:
                env_out = EventEnvelope(
                    event_type=Topic.FIELD_RETRY_REQUESTED.value,
                    correlation_id=envelope.correlation_id,
                    document_id=document_id,
                    claim_id=document.claim_id,
                    pipeline_version=self._pipeline_version,
                    payload={
                        "field_id": str(field.field_id),
                        "field_name": field.field_name,
                        "hard_validation_passed": hard_validation_passed,
                        "reason_codes": decision.reason_codes,
                        "policy_version": decision.policy_version,
                    },
                )
                await outbox.add(OutboxRecord(topic=Topic.FIELD_RETRY_REQUESTED.value, envelope=env_out, partition_key=str(document_id)))

            document.updated_at = datetime.now(UTC)
            documents.update(document)
            session.commit()

    async def run_forever(self) -> None:
        async for _topic, envelope in self._event_bus.subscribe(
            [Topic.FIELD_RETRY_REQUESTED.value], group_id=CONSUMER_GROUP
        ):
            try:
                await self.handle_one(envelope)
            except Exception:
                logger.exception("failed to retry field")

def main() -> None:
    from apps.ingestion_api.db.session import make_session_factory
    from packages.events.bus import AIOKafkaEventBus
    from packages.observability import configure_logging
    from packages.settings import get_settings

    configure_logging("retry-worker")
    settings = get_settings()
    
    import os
    vlm_enabled = os.environ.get("VLM_ENABLED", "false").lower() == "true"
    
    object_store = ObjectStore(
        ObjectStoreSettings(
            endpoint_url=settings.object_store_endpoint,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
            use_ssl=settings.object_store_use_ssl,
        )
    )

    worker = RetryWorker(
        event_bus=AIOKafkaEventBus(settings.kafka_bootstrap_servers),
        object_store=object_store,
        session_factory=make_session_factory(settings.database_url),
        pipeline_version=settings.pipeline_version,
        vlm_enabled=vlm_enabled,
    )
    asyncio.run(worker.run_forever())

if __name__ == "__main__":
    main()
