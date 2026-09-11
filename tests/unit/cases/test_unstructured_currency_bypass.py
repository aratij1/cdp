"""Regression test: proving that unparseable or dirty currency values in unstructured extraction
do NOT bypass normalization into normalized_value, preventing malformed strings from
entering downstream fixed-width NSF/UB92 pipelines, while preserving raw_value for HITL audit.
"""

from __future__ import annotations

from packages.domain.common import BoundingBox
from packages.domain.enums import ExtractionMethod, ValidationStatus
from packages.domain.extraction import ExtractedField
from workers.standard_form_extraction.field_processors import normalize


def test_currency_normalization_behavior() -> None:
    # 1. Valid formatted currency normalizes cleanly to standard decimal string representation
    norm_val, ok = normalize("currency", "$1,250.00")
    assert ok is True
    assert norm_val == "1250.00"

    norm_val2, ok2 = normalize("currency", "($450.50)")
    assert ok2 is True
    assert norm_val2 == "-450.50"

    # 2. Unparseable currency string fails normalization and returns None
    norm_val_bad, ok_bad = normalize("currency", "NOT_A_CURRENCY")
    assert ok_bad is False
    assert norm_val_bad is None

    norm_val_empty, ok_empty = normalize("currency", "$")
    assert ok_empty is False
    assert norm_val_empty is None


def test_extracted_field_unparseable_currency_retains_raw_but_nulls_normalized() -> None:
    # Simulate extraction handling: raw_value gets OCR text, normalized_value gets None when invalid
    raw_ocr = "BAD_CURRENCY_OCR"
    norm_val, norm_valid = normalize("currency", raw_ocr)

    field = ExtractedField(
        field_name="total_charge",
        raw_value=raw_ocr,
        normalized_value=norm_val if norm_valid else None,
        confidence=0.85,
        page_number=1,
        bounding_box=BoundingBox(x0=0.1, y0=0.1, x1=0.2, y1=0.2, image_width=1000, image_height=1000),
        extraction_method=ExtractionMethod.ALTERNATE_PREPROCESS_OCR,
        validation_status=ValidationStatus.NEEDS_REVIEW,
    )

    # Raw value is preserved for HITL review
    assert field.raw_value == "BAD_CURRENCY_OCR"
    # Normalized value is strictly None, never raw string bypass
    assert field.normalized_value is None
