"""End-to-end (in-process, fake object store, SQLite) of the
standard-form-extraction consumer: extraction.standard.requested -> template
region OCR for the requested page -> persisted ExtractedField rows ->
outbox extraction.completed.

Reuses the region-scripted fake extractor from
tests/unit/test_standard_form_extraction.py's pattern (scripted by field
region, not image identity) since `StandardFormExtractionService` never
calls whole-page OCR -- only `extract_region`, keyed by coordinates.
"""

import io
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from apps.ingestion_api.db.repository import (
    DocumentRepository,
    ExtractedFieldRepository,
    PageRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from packages.domain.common import ObjectRef
from packages.domain.document import Document, Page
from packages.domain.enums import CompressionType, DocumentStatus, SourceFormat
from packages.events.bus import InMemoryEventBus
from packages.events.envelope import EventEnvelope
from packages.events.topics import Topic
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from workers.page_detection.text_extraction import TextLine
from workers.standard_form_extraction.consumer import StandardFormExtractionWorker
from workers.standard_form_extraction.extractor import StandardFormExtractionService


class RegionScriptedTextExtractor:
    def __init__(self, scripted: dict[tuple[int, int, int, int], str]) -> None:
        self._scripted = scripted

    def extract(self, image):  # pragma: no cover - must not be called
        raise AssertionError("whole-page OCR must never be called for standard-form extraction")

    def extract_region(self, image, x0, y0, x1, y1) -> list[TextLine]:
        for (rx0, ry0, rx1, ry1), text in self._scripted.items():
            if x0 <= rx0 and y0 <= ry0 and x1 >= rx1 and y1 >= ry1:
                return [TextLine(text=text, x0=rx0, y0=ry0, x1=rx1, y1=ry1, confidence=0.9)]
        return []


def _registry() -> TemplateRegistry:
    return TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)


class _RegistryWithReferenceImage:
    """Wraps the real registry but returns a fixed reference image, without
    needing an actual file on disk -- `StandardFormExtractionWorker` only
    ever calls `.get(...)` and `.load_reference_image(...)`."""

    def __init__(self, registry: TemplateRegistry, reference_image: Image.Image | None) -> None:
        self._registry = registry
        self._reference_image = reference_image

    def get(self, template_id: str, version: str):
        return self._registry.get(template_id, version)

    def load_reference_image(self, template) -> Image.Image | None:
        return self._reference_image


def _textured_image(size: tuple[int, int]) -> Image.Image:
    """Same technique as test_template_alignment.py's `_textured_image` --
    ORB needs real corners/texture, not a blank page, to match reliably."""
    img = Image.new("L", size, color=255)
    draw = ImageDraw.Draw(img)
    for i, y in enumerate(range(20, size[1] - 20, 40)):
        draw.text((20, y), f"ABCDEFG 1234567890 line {i}", fill=0)
    for x in range(0, size[0], 60):
        draw.line([(x, 0), (x, size[1])], fill=0, width=1)
    for y in range(0, size[1], 60):
        draw.line([(0, y), (size[0], y)], fill=0, width=1)
    return img


def _document() -> Document:
    return Document(
        tenant_id="tenant-1",
        source_filename="claim.tiff",
        detected_format=SourceFormat.TIFF,
        sha256="c" * 64,
        original_object=ObjectRef(bucket="idp-documents", key="documents/aa/bb/x.tiff"),
        pipeline_version="0.1.0",
        schema_version="1.0",
        status=DocumentStatus.ROUTED,
    )


@pytest.mark.asyncio
async def test_extraction_worker_persists_fields_and_publishes_completion(fake_object_store):
    session_factory = make_session_factory("sqlite:///:memory:")
    template = _registry().get("cms1500", "02-12")
    document = _document()

    # image size deliberately differs from reference_dimensions so the
    # worker's rescale-to-reference-dimensions step is actually exercised.
    raw_image = Image.new("L", (400, 500), color=255)
    buf = io.BytesIO()
    raw_image.save(buf, format="PNG")
    ref = fake_object_store.put_immutable(
        "idp-documents", f"pages/{document.document_id}/1.png", buf.getvalue()
    )
    page = Page(
        document_id=document.document_id,
        page_number=1,
        width_px=raw_image.width,
        height_px=raw_image.height,
        compression=CompressionType.UNCOMPRESSED,
        original_object=ref,
        extraction_object=ref,
    )

    with session_factory() as session:
        DocumentRepository(session).add(document)
        PageRepository(session).add_all([page])
        session.commit()

    scripted = {
        (f.x0, f.y0, f.x1, f.y1): {"patient_name": "DOE, JOHN", "total_charge": "$1,675.00"}.get(
            f.field_name, ""
        )
        for f in template.field_regions
    }
    extraction_service = StandardFormExtractionService(RegionScriptedTextExtractor(scripted))
    worker = StandardFormExtractionWorker(
        event_bus=InMemoryEventBus(),
        object_store=fake_object_store,
        session_factory=session_factory,
        pipeline_version="0.1.0",
        templates=_registry(),
        extraction_service=extraction_service,
    )

    envelope = EventEnvelope(
        event_type=Topic.EXTRACTION_STANDARD_REQUESTED.value,
        correlation_id=uuid4(),
        document_id=document.document_id,
        pipeline_version="0.1.0",
        payload={
            "document_id": str(document.document_id),
            "page_number": 1,
            "template_id": "cms1500",
            "template_version": "02-12",
            "processing_route": "CMS_STANDARD_EXTRACTOR",
            "standard_form_verification": {"candidate_family": "CMS1500", "status": "VERIFIED",
                                           "verification_score": 1.0, "eligible_for_fixed_extractor": True},
        },
    )
    await worker.handle_one(envelope)

    with session_factory() as session:
        updated = DocumentRepository(session).get(document.document_id)
        fields = ExtractedFieldRepository(session).list_for_document(document.document_id)
        unpublished = await SqlAlchemyOutboxRepository(session).get_unpublished()

    assert updated.status == DocumentStatus.VALIDATING
    assert len(fields) == len(template.field_regions)
    by_name = {f.field_name: f for f in fields}
    assert by_name["patient_name"].raw_value == "DOE, JOHN"
    assert by_name["total_charge"].normalized_value == "1675.00"

    topics = {r.topic for r in unpublished}
    assert topics == {"extraction.completed", "human.review.requested"}
    review_records = [row for row in unpublished if row.topic == "human.review.requested"]
    assert review_records
    assert all(row.envelope.payload["validation_errors"] for row in review_records)
    # The canonical reference is discovered, but a blank page cannot be
    # registered; extraction remains fail-closed on the rescaled image.
    completed = next(row for row in unpublished if row.topic == "extraction.completed")
    assert completed.envelope.payload["alignment_method"] == "rescale_only_alignment_failed"


async def _run_worker_with_reference_image(
    fake_object_store, raw_image: Image.Image, reference_image: Image.Image | None
):
    session_factory = make_session_factory("sqlite:///:memory:")
    document = _document()

    buf = io.BytesIO()
    raw_image.save(buf, format="PNG")
    ref = fake_object_store.put_immutable(
        "idp-documents", f"pages/{document.document_id}/1.png", buf.getvalue()
    )
    page = Page(
        document_id=document.document_id,
        page_number=1,
        width_px=raw_image.width,
        height_px=raw_image.height,
        compression=CompressionType.UNCOMPRESSED,
        original_object=ref,
        extraction_object=ref,
    )

    with session_factory() as session:
        DocumentRepository(session).add(document)
        PageRepository(session).add_all([page])
        session.commit()

    extraction_service = StandardFormExtractionService(RegionScriptedTextExtractor({}))
    worker = StandardFormExtractionWorker(
        event_bus=InMemoryEventBus(),
        object_store=fake_object_store,
        session_factory=session_factory,
        pipeline_version="0.1.0",
        templates=_RegistryWithReferenceImage(_registry(), reference_image),
        extraction_service=extraction_service,
    )

    envelope = EventEnvelope(
        event_type=Topic.EXTRACTION_STANDARD_REQUESTED.value,
        correlation_id=uuid4(),
        document_id=document.document_id,
        pipeline_version="0.1.0",
        payload={
            "document_id": str(document.document_id),
            "page_number": 1,
            "template_id": "cms1500",
            "template_version": "02-12",
            "processing_route": "CMS_STANDARD_EXTRACTOR",
            "standard_form_verification": {"candidate_family": "CMS1500", "status": "VERIFIED",
                                           "verification_score": 1.0, "eligible_for_fixed_extractor": True},
        },
    )
    await worker.handle_one(envelope)

    with session_factory() as session:
        unpublished = await SqlAlchemyOutboxRepository(session).get_unpublished()
    completed = next(row for row in unpublished if row.topic == "extraction.completed")
    return completed.envelope.payload["alignment_method"]


@pytest.mark.asyncio
async def test_extraction_worker_uses_cheap_alignment_when_reference_image_configured(
    fake_object_store,
):
    template = _registry().get("cms1500", "02-12")
    size = (template.reference_dimensions.width_px, template.reference_dimensions.height_px)
    reference = _textured_image(size)

    alignment_method = await _run_worker_with_reference_image(
        fake_object_store, raw_image=reference.copy(), reference_image=reference
    )

    assert alignment_method == "edge_phase_correlation"


@pytest.mark.asyncio
async def test_extraction_worker_falls_back_when_alignment_fails(fake_object_store):
    template = _registry().get("cms1500", "02-12")
    size = (template.reference_dimensions.width_px, template.reference_dimensions.height_px)
    reference = _textured_image(size)
    blank_page = Image.new("L", size, color=255)

    alignment_method = await _run_worker_with_reference_image(
        fake_object_store, raw_image=blank_page, reference_image=reference
    )

    assert alignment_method == "rescale_only_alignment_failed"
