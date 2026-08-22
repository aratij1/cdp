"""Eligibility gate that keeps Docling off the standard common path."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DoclingRouteInput:
    table_detected: bool
    template_extraction_failed: bool
    table_heavy_unstructured: bool
    regional_ocr_attempted: bool


def should_run_docling(value: DoclingRouteInput) -> bool:
    return value.table_heavy_unstructured or (
        value.table_detected and value.template_extraction_failed and value.regional_ocr_attempted
    )
