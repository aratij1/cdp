"""Runtime wiring for the page-detection worker: consume
`document.prepared`, classify every page of the document (Bundle A/B/C/D +
CMS-1500/UB-04 page selection, docs/ARCHITECTURE.md §9), persist the
classification detail, then outbox `page.selected` and -- when a page was
confidently selected against a known template -- `extraction.standard.
requested` too.

Uses the lightweight `TesseractTextExtractor` (see `main()`); the routing
*decision logic* itself is unit-tested against a fake extractor in
tests/unit/test_page_routing.py, exactly as workers/document_preparation
separates its pure pipeline logic from this thin consumer shell.
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
    PageClassificationRepository,
    PageRepository,
    SqlAlchemyOutboxRepository,
)
from packages.domain.classification import PageClassification
from packages.domain.enums import BundleType, ClassificationMethod, DocumentStatus, PageRole
from packages.events.bus import EventBus
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord
from packages.events.topics import Topic
from packages.observability.metrics import (
    attachments_skipped_total,
    classification_latency_seconds,
    pages_processed_total,
)
from packages.storage.object_store import ObjectStore
from workers.page_detection.router import PageRoutingService

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "page-detection-worker"


def _load_image(object_store: ObjectStore, ref) -> Image.Image:
    data = object_store.get_bytes(ref)
    image = Image.open(io.BytesIO(data))
    image.load()  # force decode now -- the BytesIO buffer goes out of scope after this call
    return image


class PageDetectionWorker:
    def __init__(
        self,
        event_bus: EventBus,
        object_store: ObjectStore,
        session_factory: sessionmaker,
        pipeline_version: str,
        router: PageRoutingService,
    ) -> None:
        self._event_bus = event_bus
        self._object_store = object_store
        self._session_factory = session_factory
        self._pipeline_version = pipeline_version
        self._router = router

    async def handle_one(self, envelope: EventEnvelope) -> None:
        document_id = envelope.document_id
        if document_id is None:
            logger.warning("document.prepared event missing document_id, skipping")
            return

        with self._session_factory() as session:
            documents = DocumentRepository(session)
            pages_repo = PageRepository(session)
            classifications_repo = PageClassificationRepository(session)
            outbox = SqlAlchemyOutboxRepository(session)

            document = documents.get(document_id)
            if document is None:
                logger.warning("document %s not found, skipping", document_id)
                return

            pages = pages_repo.list_for_document(document_id)
            if not pages:
                logger.warning("document %s has no pages, skipping", document_id)
                return

            images = await asyncio.to_thread(
                lambda: [_load_image(self._object_store, p.extraction_object) for p in pages]
            )

            started = time.monotonic()
            result = await asyncio.to_thread(self._router.route, images)
            duration = time.monotonic() - started
            has_standard_route = (
                result.selected_page_number is not None
                and result.template is not None
                and not result.needs_review
            )
            has_unstructured_route = result.bundle_type in {
                BundleType.D_UNSTRUCTURED, BundleType.UNKNOWN_STRUCTURED,
                BundleType.UNKNOWN_UNSTRUCTURED,
            }
            has_nonclaim_route = result.bundle_type == BundleType.NON_CLAIM
            effective_needs_review = result.needs_review or not (
                has_standard_route or has_unstructured_route or has_nonclaim_route
            )
            effective_reason_codes = list(result.reason_codes)
            if (
                not has_standard_route and not has_unstructured_route
                and "NO_AUTOMATED_EXTRACTION_ROUTE" not in effective_reason_codes
            ):
                effective_reason_codes.append("NO_AUTOMATED_EXTRACTION_ROUTE")

            page_by_number = {p.page_number: p for p in pages}
            classifications: list[PageClassification] = []
            roles_by_page_id: dict = {}
            attachment_count = 0

            for page_number, role in result.page_roles.items():
                page = page_by_number.get(page_number)
                if page is None:
                    continue
                score = result.page_scores.get(page_number)
                is_claim_page = role in (PageRole.CMS1500_CLAIM_PAGE, PageRole.UB_CLAIM_PAGE)
                classifications.append(
                    PageClassification(
                        page_id=page.page_id,
                        document_id=document_id,
                        role=role,
                        confidence=score.confidence if score else 0.0,
                        method=score.method if score else ClassificationMethod.ANCHOR_PHRASE,
                        template_id=result.template.template_id
                        if (result.template and is_claim_page)
                        else None,
                        template_version=result.template.version
                        if (result.template and is_claim_page)
                        else None,
                        reason_codes=score.reason_codes if score else effective_reason_codes,
                        needs_review=effective_needs_review,
                        registration_evidence=(score.registration_evidence if score else None),
                    )
                )
                roles_by_page_id[page.page_id] = role.value
                if role == PageRole.ATTACHMENT:
                    attachment_count += 1

            classifications_repo.add_all(classifications)
            pages_repo.update_roles(roles_by_page_id)

            document.bundle_type = result.bundle_type
            document.status = (
                DocumentStatus.NEEDS_REVIEW if effective_needs_review else DocumentStatus.ROUTED
            )
            document.updated_at = datetime.now(UTC)
            documents.update(document)

            pages_processed_total.labels(bundle_type=result.bundle_type.value).inc(len(pages))
            if attachment_count:
                attachments_skipped_total.inc(attachment_count)
            primary_method = (
                result.page_scores[result.selected_page_number].method.value
                if result.selected_page_number is not None
                and result.selected_page_number in result.page_scores
                else "no_match"
            )
            classification_latency_seconds.labels(method=primary_method).observe(duration)

            envelope_out = EventEnvelope(
                event_type=Topic.PAGE_SELECTED.value,
                correlation_id=envelope.correlation_id,
                document_id=document_id,
                pipeline_version=self._pipeline_version,
                payload={
                    "document_id": str(document_id),
                    "bundle_type": result.bundle_type.value,
                    "canonical_route": (
                        result.canonical_route.value if result.canonical_route else None
                    ),
                    "route_decision": (
                        result.route_decision.model_dump(mode="json")
                        if result.route_decision else None
                    ),
                    "selected_page_number": result.selected_page_number,
                    "needs_review": effective_needs_review,
                    "reason_codes": effective_reason_codes,
                    "image_quality": {
                        str(p.page_number): p.image_quality.model_dump(mode="json")
                        for p in pages
                        if p.image_quality is not None
                    },
                    "registration_evidence": {
                        str(page_number): score.registration_evidence.model_dump(mode="json")
                        for page_number, score in result.page_scores.items()
                        if score.registration_evidence is not None
                    },
                },
            )
            await outbox.add(
                OutboxRecord(
                    topic=Topic.PAGE_SELECTED.value,
                    envelope=envelope_out,
                    partition_key=str(document_id),
                )
            )

            if has_standard_route:
                extraction_envelope = EventEnvelope(
                    event_type=Topic.EXTRACTION_STANDARD_REQUESTED.value,
                    correlation_id=envelope.correlation_id,
                    document_id=document_id,
                    pipeline_version=self._pipeline_version,
                    payload={
                        "document_id": str(document_id),
                        "page_number": result.selected_page_number,
                        "template_id": result.template.template_id,
                        "template_version": result.template.version,
                    },
                )
                await outbox.add(
                    OutboxRecord(
                        topic=Topic.EXTRACTION_STANDARD_REQUESTED.value,
                        envelope=extraction_envelope,
                        partition_key=str(document_id),
                    )
                )
            elif has_unstructured_route:
                extraction_envelope = EventEnvelope(
                    event_type=Topic.EXTRACTION_UNSTRUCTURED_REQUESTED.value,
                    correlation_id=envelope.correlation_id,
                    document_id=document_id,
                    pipeline_version=self._pipeline_version,
                    payload={
                        "document_id": str(document_id),
                        "page_numbers": [
                            page_number for page_number, role in result.page_roles.items()
                            if role == PageRole.UNSTRUCTURED_CLAIM_PAGE
                        ],
                        "reason_codes": result.reason_codes,
                    },
                )
                await outbox.add(OutboxRecord(
                    topic=Topic.EXTRACTION_UNSTRUCTURED_REQUESTED.value,
                    envelope=extraction_envelope,
                    partition_key=str(document_id),
                ))

            session.commit()

    async def run_forever(self) -> None:
        async for _topic, envelope in self._event_bus.subscribe(
            [Topic.DOCUMENT_PREPARED.value], group_id=CONSUMER_GROUP
        ):
            try:
                await self.handle_one(envelope)
            except Exception:
                logger.exception("failed to classify document_id=%s", envelope.document_id)


def main() -> None:
    from apps.ingestion_api.db.session import make_session_factory
    from packages.domain.enums import ClaimFormType
    from packages.events.bus import AIOKafkaEventBus
    from packages.observability import configure_logging
    from packages.settings import get_settings
    from packages.storage.object_store import ObjectStoreSettings
    from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
    from workers.cascade.tesseract_adapter import TesseractTextExtractor

    configure_logging("page-detection-worker")
    settings = get_settings()
    registry = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    cms_template = registry.latest_for_form_type(ClaimFormType.CMS1500)
    ub_template = registry.latest_for_form_type(ClaimFormType.UB04)
    router = PageRoutingService(
        cms_template=cms_template,
        ub_template=ub_template,
        # Printed page-level anchors do not justify loading Paddle's full
        # detector/recognizer stack. Paddle remains in the downstream
        # regional field worker, where its accuracy benefit is material.
        text_extractor=TesseractTextExtractor(psm=11),
        # Only populated when an operator has supplied a real reference scan
        # (see Template.reference_image_path) -- otherwise None, and routing
        # falls back to anchor-phrases only, exactly as before.
        cms_reference_image=registry.load_reference_image(cms_template),
        ub_reference_image=registry.load_reference_image(ub_template),
        enable_router_v3=settings.enable_router_v3,
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
    worker = PageDetectionWorker(
        event_bus=event_bus,
        object_store=object_store,
        session_factory=make_session_factory(settings.database_url),
        pipeline_version=settings.pipeline_version,
        router=router,
    )
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()
