"""End-to-end (in-process, fake object store, SQLite) of the page-detection
consumer: document.prepared -> classify every page -> persist
PageClassification rows + page roles -> outbox page.selected (and
extraction.standard.requested when a page was confidently selected).

Uses a fake `TextExtractor` (real OCR requires PaddleOCR -- see
workers/page_detection/text_extraction.py) keyed by pixel content rather
than object identity, since the worker decodes a *new* PIL Image from
object-store bytes rather than reusing the caller's image instance.
"""

import io
from uuid import uuid4

import pytest
from PIL import Image

from apps.ingestion_api.db.repository import (
    DocumentRepository,
    PageClassificationRepository,
    PageRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from packages.domain.common import ObjectRef
from packages.domain.document import Document, Page
from packages.domain.enums import (
    ClassificationMethod,
    CompressionType,
    DocumentStatus,
    PageRole,
    SourceFormat,
)
from packages.events.bus import InMemoryEventBus
from packages.events.envelope import EventEnvelope
from packages.events.topics import Topic
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from workers.page_detection.consumer import PageDetectionWorker
from workers.page_detection.router import PageRoutingService
from workers.page_detection.text_extraction import TextLine


class ContentKeyedFakeTextExtractor:
    """Like tests/unit/test_page_routing.py's FakeTextExtractor, but keyed
    by pixel bytes -- the worker under test decodes a fresh `Image.Image`
    from object-store bytes, so `id(image)` never matches the instance the
    test configured lines against."""

    def __init__(self) -> None:
        self._lines_by_content: dict[bytes, list[TextLine]] = {}

    def set_lines(self, image: Image.Image, lines: list[TextLine]) -> None:
        self._lines_by_content[image.convert("L").tobytes()] = lines

    def extract(self, image: Image.Image) -> list[TextLine]:
        return self._lines_by_content.get(image.convert("L").tobytes(), [])

    def extract_region(self, image, x0, y0, x1, y1) -> list[TextLine]:
        return [
            l for l in self.extract(image) if not (l.x1 < x0 or l.x0 > x1 or l.y1 < y0 or l.y0 > y1)
        ]


def _line(text: str) -> TextLine:
    return TextLine(text=text, x0=0, y0=0, x1=200, y1=30, confidence=0.95)


def _blank_page(size) -> Image.Image:
    return Image.new("L", size, color=255)


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _document() -> Document:
    return Document(
        tenant_id="tenant-1",
        source_filename="claim.tiff",
        detected_format=SourceFormat.TIFF,
        sha256="b" * 64,
        original_object=ObjectRef(bucket="idp-documents", key="documents/aa/bb/x.tiff"),
        pipeline_version="0.1.0",
        schema_version="1.0",
        status=DocumentStatus.PREPARED,
    )


def _seed_page(fake_object_store, document: Document, page_number: int, image: Image.Image) -> Page:
    ref = fake_object_store.put_immutable(
        "idp-documents", f"pages/{document.document_id}/{page_number}.png", _png_bytes(image)
    )
    return Page(
        document_id=document.document_id,
        page_number=page_number,
        width_px=image.width,
        height_px=image.height,
        compression=CompressionType.UNCOMPRESSED,
        original_object=ref,
        extraction_object=ref,
    )


def _registry() -> TemplateRegistry:
    return TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)


@pytest.mark.asyncio
async def test_single_page_bundle_a_nomination_without_verification_uses_layout_extraction(fake_object_store):
    session_factory = make_session_factory("sqlite:///:memory:")
    document = _document()
    page_image = _blank_page((210, 210))

    extractor = ContentKeyedFakeTextExtractor()
    extractor.set_lines(
        page_image,
        [
            _line("HEALTH INSURANCE CLAIM FORM"),
            _line("APPROVED BY NATIONAL UNIFORM CLAIM COMMITTEE"),
            _line("PICA"),
        ],
    )

    with session_factory() as session:
        DocumentRepository(session).add(document)
        page = _seed_page(fake_object_store, document, 1, page_image)
        PageRepository(session).add_all([page])
        session.commit()

    reg = _registry()
    router = PageRoutingService(
        cms_template=reg.get("cms1500", "02-12"),
        ub_template=reg.get("ub04", "2014"),
        text_extractor=extractor,
    )
    worker = PageDetectionWorker(
        event_bus=InMemoryEventBus(),
        object_store=fake_object_store,
        session_factory=session_factory,
        pipeline_version="0.1.0",
        router=router,
    )
    envelope = EventEnvelope(
        event_type=Topic.DOCUMENT_PREPARED.value,
        correlation_id=uuid4(),
        document_id=document.document_id,
        pipeline_version="0.1.0",
        payload={"document_id": str(document.document_id), "page_count": 1},
    )
    await worker.handle_one(envelope)

    with session_factory() as session:
        updated = DocumentRepository(session).get(document.document_id)
        pages = PageRepository(session).list_for_document(document.document_id)
        classifications = PageClassificationRepository(session).list_for_document(
            document.document_id
        )
        unpublished = await SqlAlchemyOutboxRepository(session).get_unpublished()

    assert updated.status == DocumentStatus.ROUTED
    assert updated.bundle_type.value == "A_CMS1500_SINGLE"
    assert pages[0].role == PageRole.CMS1500_CLAIM_PAGE.value
    assert len(classifications) == 1
    assert classifications[0].method == ClassificationMethod.TRUSTED_ANCHOR_SKIP
    assert classifications[0].template_id == "cms1500"

    topics = {r.topic for r in unpublished}
    assert topics == {"page.selected", "extraction.unstructured.requested"}
    request = next(r for r in unpublished if r.topic == "extraction.unstructured.requested")
    assert request.envelope.payload["processing_route"] == "LAYOUT_STRUCTURED_EXTRACTOR"


@pytest.mark.asyncio
async def test_ambiguous_multipage_bundle_needs_review_and_skips_extraction_request(
    fake_object_store,
):
    session_factory = make_session_factory("sqlite:///:memory:")
    document = _document()
    page_a = _blank_page((211, 211))
    page_b = _blank_page((212, 212))

    extractor = ContentKeyedFakeTextExtractor()
    extractor.set_lines(page_a, [_line("PICA")])
    extractor.set_lines(page_b, [_line("PICA")])

    with session_factory() as session:
        DocumentRepository(session).add(document)
        pages = [
            _seed_page(fake_object_store, document, 1, page_a),
            _seed_page(fake_object_store, document, 2, page_b),
        ]
        PageRepository(session).add_all(pages)
        session.commit()

    reg = _registry()
    router = PageRoutingService(
        cms_template=reg.get("cms1500", "02-12"),
        ub_template=reg.get("ub04", "2014"),
        text_extractor=extractor,
    )
    worker = PageDetectionWorker(
        event_bus=InMemoryEventBus(),
        object_store=fake_object_store,
        session_factory=session_factory,
        pipeline_version="0.1.0",
        router=router,
    )
    envelope = EventEnvelope(
        event_type=Topic.DOCUMENT_PREPARED.value,
        correlation_id=uuid4(),
        document_id=document.document_id,
        pipeline_version="0.1.0",
        payload={"document_id": str(document.document_id), "page_count": 2},
    )
    await worker.handle_one(envelope)

    with session_factory() as session:
        updated = DocumentRepository(session).get(document.document_id)
        unpublished = await SqlAlchemyOutboxRepository(session).get_unpublished()

    assert updated.status == DocumentStatus.NEEDS_REVIEW
    topics = {r.topic for r in unpublished}
    assert topics == {"page.selected"}


@pytest.mark.asyncio
async def test_unstructured_document_routes_to_bundle_d_consumer(
    fake_object_store,
):
    session_factory = make_session_factory("sqlite:///:memory:")
    document = _document()
    page_image = _blank_page((213, 213))
    extractor = ContentKeyedFakeTextExtractor()
    extractor.set_lines(page_image, [_line("UNRELATED CLINICAL NOTE")])

    with session_factory() as session:
        DocumentRepository(session).add(document)
        PageRepository(session).add_all([
            _seed_page(fake_object_store, document, 1, page_image),
        ])
        session.commit()

    reg = _registry()
    worker = PageDetectionWorker(
        event_bus=InMemoryEventBus(),
        object_store=fake_object_store,
        session_factory=session_factory,
        pipeline_version="0.1.0",
        router=PageRoutingService(
            cms_template=reg.get("cms1500", "02-12"),
            ub_template=reg.get("ub04", "2014"),
            text_extractor=extractor,
        ),
    )
    await worker.handle_one(EventEnvelope(
        event_type=Topic.DOCUMENT_PREPARED.value,
        correlation_id=uuid4(),
        document_id=document.document_id,
        pipeline_version="0.1.0",
        payload={"document_id": str(document.document_id), "page_count": 1},
    ))

    with session_factory() as session:
        updated = DocumentRepository(session).get(document.document_id)
        classifications = PageClassificationRepository(session).list_for_document(
            document.document_id
        )
        unpublished = await SqlAlchemyOutboxRepository(session).get_unpublished()

    assert updated.status == DocumentStatus.ROUTED
    assert not classifications[0].needs_review
    assert {record.topic for record in unpublished} == {
        "page.selected", "extraction.unstructured.requested",
    }
    page_event = next(record for record in unpublished if record.topic == "page.selected")
    assert "NO_AUTOMATED_EXTRACTION_ROUTE" not in page_event.envelope.payload["reason_codes"]
