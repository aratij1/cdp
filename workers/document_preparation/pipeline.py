"""Document preparation: decode -> preserve original -> preprocess ->
render extraction image + thumbnail, for every page, with every transform
recorded. The original decoded page is never overwritten by any later
step — each transform writes a *new* object and the page keeps its own
`original_object` pointing at the untouched decode.
"""

from __future__ import annotations

import io

from PIL import Image

from packages.domain.common import ObjectRef
from packages.domain.document import Document, Page, PageTransform
from packages.domain.enums import SourceFormat
from packages.image_quality import assess_image_quality
from packages.storage.hashing import perceptual_hash, sha256_bytes
from packages.storage.object_store import ObjectStore, content_addressed_key
from workers.document_preparation.codecs import (
    DecodedPage,
    UnsupportedDocumentError,
    decode_pdf_pages,
    decode_tiff_pages,
)
from workers.document_preparation.preprocessing import (
    apply_orientation,
    denoise,
    deskew,
    detect_orientation,
    detect_skew_angle,
    enhance_contrast,
    make_thumbnail,
)

THUMBNAIL_MAX_DIMENSION = 300


def decode_document(fmt: SourceFormat, data: bytes) -> list[DecodedPage]:
    if fmt == SourceFormat.TIFF:
        return decode_tiff_pages(data)
    if fmt == SourceFormat.PDF:
        return decode_pdf_pages(data)
    if fmt in (SourceFormat.PNG, SourceFormat.JPEG):
        image = Image.open(io.BytesIO(data)).convert("L")
        from packages.domain.enums import CompressionType

        return [
            DecodedPage(
                page_number=1,
                image=image,
                width_px=image.width,
                height_px=image.height,
                compression=CompressionType.OTHER,
            )
        ]
    raise UnsupportedDocumentError(f"unsupported source format: {fmt}")


def _encode_png(image: Image.Image) -> bytes:
    # optimize=True runs an extra, slow compression-parameter search --
    # profiling against a real 9-page document (tests/performance/
    # test_throughput.py) showed PNG encoding at 72% of total pipeline
    # time with it on. Every page persists 3-5 of these (original,
    # denoised, thumbnail, +orientation/deskew when non-trivial), so this
    # runs many times per page -- the size/speed tradeoff clearly favors
    # speed here (storage is cheap; this pipeline's throughput is not).
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


class DocumentPreparationService:
    def __init__(
        self,
        object_store: ObjectStore,
        bucket: str,
        enhance_contrast_enabled: bool = False,
    ) -> None:
        self._object_store = object_store
        self._bucket = bucket
        self._enhance_contrast_enabled = enhance_contrast_enabled

    def _put(
        self, document_id: str, page_number: int, suffix: str, image: Image.Image
    ) -> ObjectRef:
        data = _encode_png(image)
        key = content_addressed_key(
            sha256_bytes(data), f"{document_id}/page-{page_number:03d}-{suffix}.png"
        )
        return self._object_store.put_immutable(self._bucket, key, data, content_type="image/png")

    def prepare(self, document: Document, raw_bytes: bytes) -> list[Page]:
        decoded_pages = decode_document(document.detected_format, raw_bytes)
        pages: list[Page] = []
        for decoded in decoded_pages:
            transforms: list[PageTransform] = []

            original_ref = self._put(
                str(document.document_id), decoded.page_number, "original", decoded.image
            )

            orientation = detect_orientation(decoded.image)
            oriented = apply_orientation(decoded.image, orientation)
            if orientation != 0:
                oriented_ref = self._put(
                    str(document.document_id), decoded.page_number, "oriented", oriented
                )
                transforms.append(
                    PageTransform(
                        step="orientation_correction",
                        parameters={"rotation_degrees": orientation},
                        output_object=oriented_ref,
                    )
                )

            skew_angle = detect_skew_angle(oriented)
            deskewed = deskew(oriented, skew_angle)
            if skew_angle != 0.0:
                deskewed_ref = self._put(
                    str(document.document_id), decoded.page_number, "deskewed", deskewed
                )
                transforms.append(
                    PageTransform(
                        step="deskew",
                        parameters={"angle_degrees": skew_angle},
                        output_object=deskewed_ref,
                    )
                )

            denoised = denoise(deskewed)
            denoised_ref = self._put(
                str(document.document_id), decoded.page_number, "denoised", denoised
            )
            transforms.append(
                PageTransform(
                    step="denoise",
                    parameters={"method": "median_blur", "ksize": 3},
                    output_object=denoised_ref,
                )
            )

            extraction_image = denoised
            if self._enhance_contrast_enabled:
                extraction_image = enhance_contrast(denoised)
                contrast_ref = self._put(
                    str(document.document_id), decoded.page_number, "extraction", extraction_image
                )
                transforms.append(
                    PageTransform(
                        step="contrast_enhancement",
                        parameters={"method": "CLAHE", "clip_limit": 2.0},
                        output_object=contrast_ref,
                    )
                )
                extraction_ref = contrast_ref
            else:
                extraction_ref = denoised_ref

            thumbnail = make_thumbnail(extraction_image, THUMBNAIL_MAX_DIMENSION)
            thumbnail_ref = self._put(
                str(document.document_id), decoded.page_number, "thumb", thumbnail
            )

            page = Page(
                document_id=document.document_id,
                page_number=decoded.page_number,
                width_px=decoded.width_px,
                height_px=decoded.height_px,
                compression=decoded.compression,
                original_object=original_ref,
                extraction_object=extraction_ref,
                thumbnail_object=thumbnail_ref,
                perceptual_hash=perceptual_hash(decoded.image),
                transforms=transforms,
                image_quality=assess_image_quality(extraction_image),
            )
            pages.append(page)
        return pages
