"""Lossless canonical route-to-extractor dispatch contract."""

from __future__ import annotations

from enum import StrEnum

from packages.processing_routes.contracts import ProcessingRoute


class ExtractionTarget(StrEnum):
    CMS1500_STANDARD = "CMS1500_STANDARD"
    UB04_STANDARD = "UB04_STANDARD"
    UNKNOWN_STRUCTURED_LAYOUT = "UNKNOWN_STRUCTURED_LAYOUT"
    UNKNOWN_UNSTRUCTURED_LAYOUT = "UNKNOWN_UNSTRUCTURED_LAYOUT"
    STOP_NON_CLAIM = "STOP_NON_CLAIM"


TARGET_BY_ROUTE={
    ProcessingRoute.CMS_STANDARD_EXTRACTOR:ExtractionTarget.CMS1500_STANDARD,
    ProcessingRoute.UB_STANDARD_EXTRACTOR:ExtractionTarget.UB04_STANDARD,
    ProcessingRoute.LAYOUT_STRUCTURED_EXTRACTOR:ExtractionTarget.UNKNOWN_STRUCTURED_LAYOUT,
    ProcessingRoute.UNSTRUCTURED_EXTRACTOR:ExtractionTarget.UNKNOWN_UNSTRUCTURED_LAYOUT,
    ProcessingRoute.STOP_NON_CLAIM:ExtractionTarget.STOP_NON_CLAIM,
}


def extraction_target(route:ProcessingRoute|str)->ExtractionTarget:
    """Resolve only a canonical ProcessingRoute; classifier nominations are invalid."""
    return TARGET_BY_ROUTE[ProcessingRoute(route)]
