"""Runtime wiring for the standard-form-extraction worker: consume
`extraction.standard.requested` (published by workers.page_detection once
a page is confidently matched to a template), run template-region OCR for
that one page, persist the resulting fields/service-line cells, then
outbox `extraction.completed`.

Fixed regions are fail-closed: form identity, compatible template lineage,
accepted registration and valid transformed corners must all be present.
Registration failure is diverted to the layout extractor before field OCR;
rescale-only template extraction is forbidden.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from PIL import Image
from sqlalchemy.orm import sessionmaker

from apps.ingestion_api.db.repository import (
    DocumentRepository,
    ExtractedFieldRepository,
    PageRepository,
    SqlAlchemyOutboxRepository,
)
from packages.criticality import DEFAULT_CRITICALITY_PATH, CriticalityLevel, CriticalityPolicy
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.domain.enums import ClaimFormType, DocumentStatus, ExtractionMethod, ValidationStatus
from packages.events.bus import EventBus
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord
from packages.events.topics import Topic
from packages.extraction_geometry import (
    ExtractionGeometryDecision,
    ExtractionGeometryMode,
    FormIdentityDecision,
    FormIdentityStatus,
)
from packages.extraction_routing import ExtractionTarget, extraction_target
from packages.observability.metrics import ocr_latency_seconds
from packages.page_observation import PageObservationService
from packages.processing_routes.contracts import ProcessingRoute
from packages.roi_resolution import (
    AnchorRelativeContract,
    ObservedAnchor,
    ROIResolutionRequest,
    ROIResolver,
)
from packages.standard_form_verification.contracts import (
    StandardFormStatus,
    StandardFormVerification,
)
from packages.storage.object_store import ObjectStore
from packages.templates.models import Template
from packages.templates.registry import TemplateRegistry
from workers.page_detection.crop_safety import CropSafetyEvidence, validate_field_crop
from workers.page_detection.template_alignment import align_to_reference
from workers.page_detection.template_compatibility import (
    TemplateCompatibilityStatus,
    assess_template_compatibility,
)
from workers.standard_form_extraction.extractor import StandardFormExtractionService
from workers.standard_form_extraction.processing import StandardFormProcessingService

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "standard-form-extraction-worker"


def _load_image(object_store: ObjectStore, ref) -> Image.Image:
    data = object_store.get_bytes(ref)
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def _resolve_geometry(
    image: Image.Image,
    template: Template,
    reference_image: Image.Image | None,
    identity: FormIdentityDecision,
    anchor_relative_available: bool = False,
) -> tuple[Image.Image | None, ExtractionGeometryDecision]:
    """Resolve geometry once and never turn a failed registration into fixed ROI."""
    common = {
        "form_identity": identity,
        "template_id": template.template_id,
        "template_version": template.version,
    }
    if identity.status != FormIdentityStatus.VERIFIED:
        return None, ExtractionGeometryDecision(
            mode=ExtractionGeometryMode.SAFE_FALLBACK,
            reason_codes=("FORM_IDENTITY_NOT_VERIFIED",),
            **common,
        )
    if reference_image is None:
        return (image if anchor_relative_available else None), ExtractionGeometryDecision(
            mode=(ExtractionGeometryMode.ANCHOR_RELATIVE if anchor_relative_available
                  else ExtractionGeometryMode.STRUCTURAL_LAYOUT),
            reason_codes=(("FIELD_ANCHOR_CONTRACTS_AVAILABLE",)
                          if anchor_relative_available else
                          ("REFERENCE_TEMPLATE_IMAGE_UNAVAILABLE",)),
            **common,
        )
    width, height = template.reference_dimensions.width_px, template.reference_dimensions.height_px
    if reference_image.size != (width, height):
        reference_image = reference_image.resize((width, height))
    compatibility = assess_template_compatibility(
        image, reference_image, family=identity.family.value
    )
    if compatibility.status == TemplateCompatibilityStatus.INCOMPATIBLE:
        return None, ExtractionGeometryDecision(
            mode=ExtractionGeometryMode.STRUCTURAL_LAYOUT,
            compatibility=compatibility,
            reason_codes=("TEMPLATE_COMPATIBILITY_REJECTED", *compatibility.reason_codes),
            **common,
        )
    result = align_to_reference(
        image,
        reference_image,
        family=identity.family.value,
        enforce_compatibility_precheck=True,
        compatibility_evidence=compatibility,
    )
    evidence = result.evidence
    if evidence is not None:
        evidence = evidence.model_copy(update={
            "template_id": template.template_id,
            "template_version": template.version,
            "candidate_family": identity.family.value,
            "compatibility_policy_version": compatibility.policy_version,
            "compatibility_status": compatibility.status.value,
            "compatibility_score": compatibility.compatibility_score,
        })
    if (
        result.success
        and result.warped is not None
        and evidence is not None
        and evidence.accepted
        and evidence.corner_validity is True
    ):
        return result.warped, ExtractionGeometryDecision(
            mode=ExtractionGeometryMode.REGISTERED_FIXED,
            compatibility=compatibility,
            registration=evidence,
            transformed_geometry_valid=True,
            reason_codes=("FIXED_GEOMETRY_AUTHORIZED",),
            **common,
        )
    decision = ExtractionGeometryDecision(
        mode=(ExtractionGeometryMode.ANCHOR_RELATIVE if anchor_relative_available
              else ExtractionGeometryMode.STRUCTURAL_LAYOUT),
        compatibility=compatibility,
        registration=evidence,
        reason_codes=(("REGISTRATION_NOT_ACCEPTED", "FIELD_ANCHOR_CONTRACTS_AVAILABLE")
                      if anchor_relative_available else ("REGISTRATION_NOT_ACCEPTED",)),
        **common,
    )
    return (image if anchor_relative_available else None), decision


class StandardFormExtractionWorker:
    def __init__(
        self,
        event_bus: EventBus,
        object_store: ObjectStore,
        session_factory: sessionmaker,
        pipeline_version: str,
        templates: TemplateRegistry,
        extraction_service: StandardFormExtractionService,
        observation_service: PageObservationService | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._object_store = object_store
        self._session_factory = session_factory
        self._pipeline_version = pipeline_version
        self._templates = templates
        self._extraction_service = extraction_service
        self._observation_service = observation_service
        self._processing_service = (
            StandardFormProcessingService(observation_service, extraction_service)
            if observation_service is not None else None
        )

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
        processing_route=envelope.payload.get("processing_route")
        if processing_route is None:
            raise ValueError("MISSING_CANONICAL_PROCESSING_ROUTE")
        requested_geometry_mode = envelope.payload.get("extraction_geometry_mode")
        if requested_geometry_mode is None:
            raise ValueError("MISSING_EXTRACTION_GEOMETRY_MODE")
        ExtractionGeometryMode(requested_geometry_mode)
        if template_id not in {"cms1500", "ub04"}:
            raise ValueError(f"UNSUPPORTED_STANDARD_TEMPLATE:{template_id}")
        target=extraction_target(processing_route)
        expected=(ExtractionTarget.CMS1500_STANDARD if template_id=="cms1500"
                  else ExtractionTarget.UB04_STANDARD)
        if target is not expected:
            raise ValueError(f"PROCESSING_ROUTE_TARGET_MISMATCH:{processing_route}:{template_id}")
        verification=StandardFormVerification.model_validate(
            envelope.payload.get("standard_form_verification") or {})
        expected_family=(DocumentClass.CMS1500 if template_id=="cms1500" else DocumentClass.UB04)
        if (verification.status != StandardFormStatus.VERIFIED or
                (not verification.eligible_for_fixed_extractor and self._observation_service is None) or
                verification.candidate_family != expected_family):
            raise ValueError("FIXED_EXTRACTOR_REQUIRES_VERIFIED_STANDARD_FORM")
        identity = FormIdentityDecision.model_validate(
            envelope.payload.get("form_identity") or {}
        )
        if identity.family != expected_family or identity.status != FormIdentityStatus.VERIFIED:
            raise ValueError("STANDARD_EXTRACTION_REQUIRES_VERIFIED_FORM_IDENTITY")
        anchor_contracts = tuple(
            AnchorRelativeContract.model_validate(item)
            for item in envelope.payload.get("anchor_relative_contracts", [])
        )
        observed_anchors = tuple(
            ObservedAnchor.model_validate(item)
            for item in envelope.payload.get("observed_anchors", [])
        )
        contract_by_field = {item.field_name: item for item in anchor_contracts}
        observed_ids = {
            item.anchor_id for item in observed_anchors
            if item.confidence >= .85
        }
        anchor_relative_available = (
            expected_family == DocumentClass.CMS1500
            and any(item.anchor_id in observed_ids for item in anchor_contracts)
        )

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
                _load_image, self._object_store, page.extraction_object
            )

            processing_result = None
            observation = None
            dynamic_roi_results = None
            ub_structure = None
            if self._observation_service is not None:
                instrumented_extractor = getattr(self._extraction_service, "_text_extractor", None)
                if hasattr(instrumented_extractor, "set_context"):
                    instrumented_extractor.set_context(
                        document_id=str(document_id), page_id=str(page.page_id),
                        route=template.form_type.value, attempt_number=envelope.attempt,
                    )
                processing_result = await asyncio.to_thread(
                    self._processing_service.process,
                    image, template, page_number, identity, page_id=str(page.page_id),
                )
                observation = processing_result.observation
                dynamic_roi_results = processing_result.roi_results
                ub_structure = processing_result.ub_structure
                geometry = processing_result.geometry
                unresolved_dynamic = [
                    name for name, result in dynamic_roi_results.items() if result.bbox is None
                ]
                if not unresolved_dynamic:
                    registered_image = image
                else:
                    # Template registration is the third-priority fast path,
                    # attempted only for a page with unresolved dynamic fields.
                    fallback_image, fallback_geometry = await asyncio.to_thread(
                        _resolve_geometry, image, template,
                        self._templates.load_reference_image(template), identity, False,
                    )
                    if (
                        fallback_image is not None
                        and fallback_geometry.authorizes_fixed_roi
                    ):
                        processing_result = await asyncio.to_thread(
                            self._processing_service.process,
                            fallback_image, template, page_number, identity,
                            page_id=f"{page.page_id}:registered-fallback",
                            registered_geometry=fallback_geometry,
                        )
                        observation = processing_result.observation
                        dynamic_roi_results = processing_result.roi_results
                        ub_structure = processing_result.ub_structure
                        geometry = fallback_geometry
                        registered_image = fallback_image
                    elif any(result.bbox for result in dynamic_roi_results.values()):
                        # Registration failure cannot discard valid dynamic ROIs.
                        registered_image = image
                    else:
                        registered_image = None
                        geometry = fallback_geometry
                        dynamic_roi_results = None
                        processing_result = None
            else:
                registered_image = None

            reference_image = self._templates.load_reference_image(template)
            if self._observation_service is None:
                registered_image, geometry = await asyncio.to_thread(
                    _resolve_geometry, image, template, reference_image, identity,
                    anchor_relative_available,
                )
            if (
                geometry.mode not in ({
                    ExtractionGeometryMode.REGISTERED_FIXED,
                    ExtractionGeometryMode.ANCHOR_RELATIVE,
                } | ({ExtractionGeometryMode.STRUCTURAL_LAYOUT}
                     if observation is not None and dynamic_roi_results is not None else set()))
                or registered_image is None
            ):
                fallback = EventEnvelope(
                    event_type=Topic.EXTRACTION_UNSTRUCTURED_REQUESTED.value,
                    correlation_id=envelope.correlation_id,
                    document_id=document_id,
                    claim_id=document.claim_id,
                    pipeline_version=self._pipeline_version,
                    payload={
                        "document_id": str(document_id),
                        "page_numbers": [page_number],
                        "processing_route": ProcessingRoute.LAYOUT_STRUCTURED_EXTRACTOR.value,
                        "extraction_target": ExtractionTarget.UNKNOWN_STRUCTURED_LAYOUT.value,
                        "form_identity": identity.model_dump(mode="json"),
                        "extraction_geometry": geometry.model_dump(mode="json"),
                        "reason_codes": list(geometry.reason_codes),
                    },
                )
                await outbox.add(OutboxRecord(
                    topic=Topic.EXTRACTION_UNSTRUCTURED_REQUESTED.value,
                    envelope=fallback,
                    partition_key=str(document_id),
                ))
                session.commit()
                return
            image = registered_image
            registration_evidence = geometry.registration
            alignment_method = (
                registration_evidence.algorithm
                if registration_evidence is not None
                else geometry.mode.value.lower()
            )
            logger.info(
                "document %s page %s selected extraction geometry via %s",
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
            criticality = CriticalityPolicy.load(DEFAULT_CRITICALITY_PATH)
            roi_resolver = ROIResolver()
            roi_results = dynamic_roi_results or {
                region.field_name: roi_resolver.resolve(ROIResolutionRequest(
                    field_name=region.field_name,
                    page_width=image.width,
                    page_height=image.height,
                    geometry=geometry,
                    fixed_region=(region.x0, region.y0, region.x1, region.y1),
                    anchor_contract=contract_by_field.get(region.field_name),
                    observed_anchors=observed_anchors,
                ))
                for region in template.field_regions
            }
            for region in template.field_regions if geometry.authorizes_fixed_roi else ():
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
            if processing_result is not None and dynamic_roi_results is not None:
                fields = processing_result.fields
            else:
                fields = await asyncio.to_thread(
                    self._extraction_service.extract_fields_from_resolved_rois,
                    image, template, page_number, geometry, roi_results,
                )
            alignment_accepted = geometry.authorizes_fixed_roi
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
                    claim_total = Decimal(total_field.normalized_value) if total_field and total_field.normalized_value else None
                except (InvalidOperation, ValueError):
                    claim_total = None
                if processing_result is not None and ub_structure is not None:
                    ub04_result = processing_result.ub_reconstruction
                    service_lines = processing_result.service_lines
                else:
                    service_lines, ub04_result = await asyncio.to_thread(
                        self._extraction_service.extract_ub04_service_lines,
                        image, template, page_number,
                        registration_confidence=registration_evidence.alignment_confidence,
                        claim_total=claim_total,
                    )
            elif geometry.authorizes_fixed_roi:
                service_lines = await asyncio.to_thread(
                    self._extraction_service.extract_service_lines, image, template, page_number
                )
            else:
                # CMS service-table coordinates are also fixed-template
                # geometry and therefore unavailable in anchor-relative mode.
                service_lines = []
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
                    "field_regional_ocr_cost": self._extraction_service.last_field_ocr_cost,
                    "ub04_reconstruction": (
                        ub04_result.model_dump(mode="json") if ub04_result else None
                    ),
                    "alignment_method": alignment_method,
                    "alignment_accepted": alignment_accepted,
                    "extraction_geometry": geometry.model_dump(mode="json"),
                    "roi_resolution": {
                        name: result.model_dump(mode="json")
                        for name, result in roi_results.items()
                    },
                    "field_localization": {
                        name: evidence.model_dump(mode="json")
                        for name, evidence in (
                            processing_result.field_locations.items()
                            if processing_result is not None else ()
                        )
                    },
                    "registration_evidence": (
                        registration_evidence.model_dump(mode="json")
                        if registration_evidence
                        else None
                    ),
                    # Evidence gaps are suggestions only.  The retry-stage
                    # EvidenceDecisionService is the sole HITL event authority.
                    "review_suggested_count": len(review_fields),
                    "review_task_count": 0,
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
    from workers.cascade.instrumented_text_extractor import (
        CachedInstrumentedTextExtractor,
        JsonlOCRAuditSink,
    )
    from workers.page_detection.text_extraction import (
        RapidOCRFullPageTextExtractor,
        RapidOCRTextExtractor,
    )

    configure_logging("standard-form-extraction-worker")
    settings = get_settings()
    templates = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    audit_sink = JsonlOCRAuditSink(settings.ocr_audit_path)
    extraction_service = StandardFormExtractionService(text_extractor=CachedInstrumentedTextExtractor(
        RapidOCRTextExtractor(), audit_sink=audit_sink
    ))
    observation_service = PageObservationService(
        CachedInstrumentedTextExtractor(RapidOCRFullPageTextExtractor(), audit_sink=audit_sink),
        preprocessing_version="document-preparation-v1",
    )
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
        observation_service=observation_service,
    )
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()
