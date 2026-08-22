"""Runtime wiring for the standard-form-extraction worker: consume
`extraction.standard.requested` (published by workers.page_detection once
a page is confidently matched to a template), run template-region OCR for
that one page, persist the resulting fields/service-line cells, then
outbox `extraction.completed`.

Alignment: `StandardFormExtractionService` expects an image aligned to the
template's reference coordinate frame. Real geometric alignment
(`workers.page_detection.template_alignment.align_to_reference`) needs a
reference *image* of a blank/representative form; no such asset ships in
this repository (the only real scans available are the sample dataset
under `dataset_raw/`, which is gitignored PHI and never committed). An
operator can supply their own clean reference scan per template (see
`Template.reference_image_path` / `packages.templates.registry.
TemplateRegistry.load_reference_image`) -- when one is configured, this
worker warps the incoming page into true alignment before OCR. When none
is configured (the default), it falls back to rescaling the page to the
template's `reference_dimensions` and OCRing it as-is; `document_preparation`
already corrects orientation and skew, so the residual difference between
a real scan and the reference frame is mostly scale (DPI) -- a real,
working approximation, just not full geometric alignment. Both paths are
documented in README.md.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from datetime import UTC, datetime

from PIL import Image
from sqlalchemy.orm import sessionmaker

from apps.ingestion_api.db.repository import (
    DocumentRepository,
    ExtractedFieldRepository,
    PageRepository,
    SqlAlchemyOutboxRepository,
)
from packages.criticality import DEFAULT_CRITICALITY_PATH, CriticalityLevel, CriticalityPolicy
from packages.domain.enums import ClaimFormType, DocumentStatus, ExtractionMethod, ValidationStatus
from packages.domain.registration import RegistrationEvidence
from packages.events.bus import EventBus
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord
from packages.events.topics import Topic
from packages.observability.metrics import ocr_latency_seconds
from packages.storage.object_store import ObjectStore
from packages.templates.models import Template
from packages.templates.registry import TemplateRegistry
from workers.page_detection.crop_safety import CropSafetyEvidence, validate_field_crop
from workers.page_detection.template_alignment import align_to_reference
from workers.standard_form_extraction.extractor import StandardFormExtractionService

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "standard-form-extraction-worker"


def _load_and_rescale(object_store: ObjectStore, ref, width: int, height: int) -> Image.Image:
    data = object_store.get_bytes(ref)
    image = Image.open(io.BytesIO(data))
    image.load()
    return image.resize((width, height))


def _align_or_rescale(
    image: Image.Image, template: Template, reference_image: Image.Image | None
) -> tuple[Image.Image, str, RegistrationEvidence | None]:
    """Returns (image ready for regional OCR, method used for observability).
    `image` is already rescaled to `template.reference_dimensions` by the
    caller. Only attempted when an operator has supplied a reference image;
    falls back to the rescaled image whenever alignment isn't configured or
    doesn't succeed (never blocks extraction on alignment failure)."""
    if reference_image is None:
        return image, "rescale_only", None
    width, height = template.reference_dimensions.width_px, template.reference_dimensions.height_px
    if reference_image.size != (width, height):
        reference_image = reference_image.resize((width, height))
    result = align_to_reference(image, reference_image)
    if result.success and result.warped is not None:
        return result.warped, result.method, result.evidence
    return image, "rescale_only_alignment_failed", result.evidence


class StandardFormExtractionWorker:
    def __init__(
        self,
        event_bus: EventBus,
        object_store: ObjectStore,
        session_factory: sessionmaker,
        pipeline_version: str,
        templates: TemplateRegistry,
        extraction_service: StandardFormExtractionService,
    ) -> None:
        self._event_bus = event_bus
        self._object_store = object_store
        self._session_factory = session_factory
        self._pipeline_version = pipeline_version
        self._templates = templates
        self._extraction_service = extraction_service

    async def handle_one(self, envelope: EventEnvelope) -> None:
        document_id = envelope.document_id
        if document_id is None:
            logger.warning("extraction.standard.requested event missing document_id, skipping")
            return

        page_number = envelope.payload.get("page_number")
        template_id = envelope.payload.get("template_id")
        template_version = envelope.payload.get("template_version")
        if page_number is None or template_id is None or template_version is None:
            logger.warning("extraction.standard.requested event missing required fields, skipping")
            return

        with self._session_factory() as session:
            documents = DocumentRepository(session)
            pages_repo = PageRepository(session)
            fields_repo = ExtractedFieldRepository(session)
            outbox = SqlAlchemyOutboxRepository(session)

            document = documents.get(document_id)
            if document is None:
                logger.warning("document %s not found, skipping", document_id)
                return

            page = next(
                (
                    p
                    for p in pages_repo.list_for_document(document_id)
                    if p.page_number == page_number
                ),
                None,
            )
            if page is None:
                logger.warning("document %s has no page %s, skipping", document_id, page_number)
                return

            template = self._templates.get(template_id, template_version)

            image = await asyncio.to_thread(
                _load_and_rescale,
                self._object_store,
                page.extraction_object,
                template.reference_dimensions.width_px,
                template.reference_dimensions.height_px,
            )

            reference_image = self._templates.load_reference_image(template)
            image, alignment_method, registration_evidence = await asyncio.to_thread(
                _align_or_rescale, image, template, reference_image
            )
            logger.info(
                "document %s page %s aligned via %s",
                document_id,
                page_number,
                alignment_method,
            )

            started = time.monotonic()
            instrumented_extractor = getattr(self._extraction_service, "_text_extractor", None)
            if hasattr(instrumented_extractor, "set_context"):
                instrumented_extractor.set_context(
                    document_id=str(document_id), page_id=str(page.page_id),
                    route=template.form_type.value, attempt_number=envelope.attempt,
                )
            crop_safety: dict[str, CropSafetyEvidence] = {}
            crop_boxes: dict[str, tuple[tuple[int, int, int, int], ...]] = {}
            criticality = CriticalityPolicy.load(DEFAULT_CRITICALITY_PATH)
            if reference_image is not None:
                for region in template.field_regions:
                    level = criticality.for_field(region.field_name)
                    if level not in {CriticalityLevel.C2, CriticalityLevel.C3}:
                        continue
                    safety = validate_field_crop(
                        image,
                        reference_image,
                        region,
                        registration_evidence,
                        critical=True,
                    )
                    crop_safety[region.field_name] = safety
                    crop_boxes[region.field_name] = safety.variant_boxes
            fields = await asyncio.to_thread(
                self._extraction_service.extract_fields,
                image,
                template,
                page_number,
                crop_boxes,
            )
            alignment_accepted = alignment_method in {
                "edge_phase_correlation",
                "sift_flann_ransac_homography",
            }
            if not alignment_accepted:
                for field in fields:
                    field.validation_status = ValidationStatus.NEEDS_REVIEW
                    field.validation_reasons.append("alignment_quality_not_verified")
            for field in fields:
                safety = crop_safety.get(field.field_name)
                if safety is not None and not safety.accepted:
                    field.validation_status = ValidationStatus.NEEDS_REVIEW
                    for reason in safety.reason_codes:
                        if reason not in field.validation_reasons:
                            field.validation_reasons.append(reason)
            ub04_result = None
            if template.form_type == ClaimFormType.UB04:
                total_field = next(
                    (f for f in fields if f.field_name in {"total_charge", "total_charges"}), None
                )
                try:
                    from decimal import Decimal
                    claim_total = Decimal(total_field.normalized_value) if total_field and total_field.normalized_value else None
                except Exception:
                    claim_total = None
                service_lines, ub04_result = await asyncio.to_thread(
                    self._extraction_service.extract_ub04_service_lines,
                    image, template, page_number,
                    registration_confidence=(registration_evidence.alignment_confidence if registration_evidence else 0.0),
                    claim_total=claim_total,
                )
                # Preserve extraction coverage when registration cannot safely support
                # structural reconstruction; these fallback cells remain review-bound.
                if not service_lines:
                    service_lines = await asyncio.to_thread(
                        self._extraction_service.extract_service_lines, image, template, page_number
                    )
                    for line in service_lines:
                        for field in line.fields:
                            field.validation_status = ValidationStatus.NEEDS_REVIEW
                            field.validation_reasons.extend(
                                ub04_result.reason_codes if ub04_result else ["UB04_RECONSTRUCTION_UNAVAILABLE"]
                            )
            else:
                service_lines = await asyncio.to_thread(
                    self._extraction_service.extract_service_lines, image, template, page_number
                )
            if not alignment_accepted:
                for line in service_lines:
                    for field in line.fields:
                        field.validation_status = ValidationStatus.NEEDS_REVIEW
                        field.validation_reasons.append("alignment_quality_not_verified")
            duration = time.monotonic() - started

            fields_repo.add_all(document_id, fields, service_line_number=None)
            for line in service_lines:
                fields_repo.add_all(document_id, line.fields, service_line_number=line.line_number)

            review_fields = [
                field
                for field in fields
                if field.validation_status == ValidationStatus.NEEDS_REVIEW
            ]
            review_fields.extend(
                field
                for line in service_lines
                for field in line.fields
                if field.validation_status == ValidationStatus.NEEDS_REVIEW
            )
            for field in review_fields:
                review_envelope = EventEnvelope(
                    event_type=Topic.HUMAN_REVIEW_REQUESTED.value,
                    correlation_id=envelope.correlation_id,
                    document_id=document_id,
                    claim_id=document.claim_id,
                    pipeline_version=self._pipeline_version,
                    payload={
                        "field_id": str(field.field_id),
                        "field_name": field.field_name,
                        "page_number": field.page_number,
                        "ocr_candidates": [candidate.raw_text for candidate in field.candidates]
                        or [field.raw_value],
                        "validation_errors": field.validation_reasons,
                    },
                )
                await outbox.add(
                    OutboxRecord(
                        topic=Topic.HUMAN_REVIEW_REQUESTED.value,
                        envelope=review_envelope,
                        partition_key=str(document_id),
                    )
                )

            document.status = DocumentStatus.VALIDATING
            document.updated_at = datetime.now(UTC)
            documents.update(document)

            extraction_method = (
                fields[0].extraction_method.value
                if fields
                else ExtractionMethod.REGIONAL_RAPIDOCR.value
            )
            ocr_latency_seconds.labels(extraction_method=extraction_method).observe(duration)

            field_count = len(fields) + sum(len(line.fields) for line in service_lines)
            envelope_out = EventEnvelope(
                event_type=Topic.EXTRACTION_COMPLETED.value,
                correlation_id=envelope.correlation_id,
                document_id=document_id,
                pipeline_version=self._pipeline_version,
                payload={
                    "document_id": str(document_id),
                    "page_number": page_number,
                    "field_count": field_count,
                    "service_line_count": len(service_lines),
                    "ub04_reconstruction": (
                        ub04_result.model_dump(mode="json") if ub04_result else None
                    ),
                    "alignment_method": alignment_method,
                    "alignment_accepted": alignment_accepted,
                    "registration_evidence": (
                        registration_evidence.model_dump(mode="json")
                        if registration_evidence
                        else None
                    ),
                    "review_task_count": len(review_fields),
                },
            )
            await outbox.add(
                OutboxRecord(
                    topic=Topic.EXTRACTION_COMPLETED.value,
                    envelope=envelope_out,
                    partition_key=str(document_id),
                )
            )
            session.commit()

    async def run_forever(self) -> None:
        async for _topic, envelope in self._event_bus.subscribe(
            [Topic.EXTRACTION_STANDARD_REQUESTED.value], group_id=CONSUMER_GROUP
        ):
            try:
                await self.handle_one(envelope)
            except Exception:
                logger.exception(
                    "failed to extract fields for document_id=%s", envelope.document_id
                )


def main() -> None:
    from apps.ingestion_api.db.session import make_session_factory
    from packages.events.bus import AIOKafkaEventBus
    from packages.observability import configure_logging
    from packages.settings import get_settings
    from packages.storage.object_store import ObjectStoreSettings
    from packages.templates.registry import DEFAULT_TEMPLATE_DIR
    from workers.page_detection.text_extraction import RapidOCRTextExtractor
    from workers.cascade.instrumented_text_extractor import (
        CachedInstrumentedTextExtractor, JsonlOCRAuditSink,
    )

    configure_logging("standard-form-extraction-worker")
    settings = get_settings()
    templates = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    extraction_service = StandardFormExtractionService(text_extractor=CachedInstrumentedTextExtractor(
        RapidOCRTextExtractor(), audit_sink=JsonlOCRAuditSink(settings.ocr_audit_path)
    ))
    event_bus = AIOKafkaEventBus(settings.kafka_bootstrap_servers)
    object_store = ObjectStore(
        ObjectStoreSettings(
            endpoint_url=settings.object_store_endpoint,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
            use_ssl=settings.object_store_use_ssl,
        )
    )
    worker = StandardFormExtractionWorker(
        event_bus=event_bus,
        object_store=object_store,
        session_factory=make_session_factory(settings.database_url),
        pipeline_version=settings.pipeline_version,
        templates=templates,
        extraction_service=extraction_service,
    )
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()
