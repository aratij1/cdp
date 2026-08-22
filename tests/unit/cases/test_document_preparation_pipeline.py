"""End-to-end (in-process) document preparation: decode -> preserve
original -> preprocess -> extraction image + thumbnail, for every page."""

import io

from PIL import Image, ImageDraw

from packages.domain.document import Document
from packages.domain.enums import SourceFormat
from packages.storage.hashing import sha256_bytes
from packages.storage.object_store import content_addressed_key
from workers.document_preparation.pipeline import DocumentPreparationService


def _make_g4_tiff_bytes(n_pages: int, width=400, height=300) -> bytes:
    images = []
    for _ in range(n_pages):
        img = Image.new("1", (width, height), color=1)
        draw = ImageDraw.Draw(img)
        for y in range(20, height - 20, 20):
            draw.rectangle([20, y, width - 20, y + 4], fill=0)
        images.append(img)
    buf = io.BytesIO()
    images[0].save(
        buf, format="TIFF", compression="group4", save_all=True, append_images=images[1:]
    )
    return buf.getvalue()


def _make_document(data: bytes) -> Document:
    digest = sha256_bytes(data)
    key = content_addressed_key(digest, "bundle.tiff")
    from packages.domain.common import ObjectRef

    return Document(
        tenant_id="tenant-1",
        source_filename="bundle.tiff",
        detected_format=SourceFormat.TIFF,
        sha256=digest,
        original_object=ObjectRef(bucket="idp-documents", key=key, sha256=digest),
        pipeline_version="0.1.0",
        schema_version="1.0",
    )


def test_prepare_produces_one_page_per_tiff_frame(fake_object_store):
    data = _make_g4_tiff_bytes(3)
    document = _make_document(data)
    service = DocumentPreparationService(fake_object_store, bucket="idp-documents")

    pages = service.prepare(document, data)

    assert [p.page_number for p in pages] == [1, 2, 3]


def test_prepare_preserves_original_as_a_distinct_immutable_object(fake_object_store):
    data = _make_g4_tiff_bytes(1)
    document = _make_document(data)
    service = DocumentPreparationService(fake_object_store, bucket="idp-documents")

    [page] = service.prepare(document, data)

    assert page.original_object is not None
    assert page.extraction_object is not None
    # original and extraction (denoised) images are stored under different keys
    assert page.original_object.key != page.extraction_object.key
    # the original bytes are retrievable and are a valid, undistorted image
    original_bytes = fake_object_store.get_bytes(page.original_object)
    restored = Image.open(io.BytesIO(original_bytes))
    assert restored.size == (page.width_px, page.height_px)


def test_prepare_records_every_transform_applied(fake_object_store):
    data = _make_g4_tiff_bytes(1)
    document = _make_document(data)
    service = DocumentPreparationService(
        fake_object_store, bucket="idp-documents", enhance_contrast_enabled=True
    )

    [page] = service.prepare(document, data)

    steps = [t.step for t in page.transforms]
    assert "denoise" in steps
    assert "contrast_enhancement" in steps
    # each transform points at a real, retrievable object
    for transform in page.transforms:
        assert fake_object_store.exists(transform.output_object.bucket, transform.output_object.key)


def test_denoise_transform_records_the_algorithm_actually_applied(fake_object_store):
    # preprocessing.denoise() runs cv2.medianBlur, not fastNlMeansDenoising --
    # the audit record must describe what actually happened to the evidence.
    data = _make_g4_tiff_bytes(1)
    document = _make_document(data)
    service = DocumentPreparationService(fake_object_store, bucket="idp-documents")

    [page] = service.prepare(document, data)

    denoise_transform = next(t for t in page.transforms if t.step == "denoise")
    assert denoise_transform.parameters == {"method": "median_blur", "ksize": 3}


def test_prepare_generates_a_thumbnail_smaller_than_the_page(fake_object_store):
    data = _make_g4_tiff_bytes(1, width=800, height=600)
    document = _make_document(data)
    service = DocumentPreparationService(fake_object_store, bucket="idp-documents")

    [page] = service.prepare(document, data)

    assert page.thumbnail_object is not None
    thumb_bytes = fake_object_store.get_bytes(page.thumbnail_object)
    thumb = Image.open(io.BytesIO(thumb_bytes))
    assert max(thumb.size) <= 300
    assert max(thumb.size) < max(page.width_px, page.height_px)


def test_prepare_computes_a_perceptual_hash_per_page(fake_object_store):
    data = _make_g4_tiff_bytes(2)
    document = _make_document(data)
    service = DocumentPreparationService(fake_object_store, bucket="idp-documents")

    pages = service.prepare(document, data)

    assert all(p.perceptual_hash for p in pages)


def test_prepare_attaches_versioned_image_quality_evidence(fake_object_store):
    data = _make_g4_tiff_bytes(1)
    [page] = DocumentPreparationService(fake_object_store, bucket="idp-documents").prepare(
        _make_document(data), data
    )

    assert page.image_quality is not None
    assert page.image_quality.assessment_version == "iq-v1"
    assert page.image_quality.width_px == page.width_px
