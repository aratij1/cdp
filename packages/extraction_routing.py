"""Lossless canonical route-to-extractor dispatch contract."""

from __future__ import annotations

from enum import StrEnum

from packages.document_routing import MultiSignalRoute


class ExtractionTarget(StrEnum):
    CMS1500_STANDARD = "CMS1500_STANDARD"
    UB04_STANDARD = "UB04_STANDARD"
    UNKNOWN_STRUCTURED_LAYOUT = "UNKNOWN_STRUCTURED_LAYOUT"
    UNKNOWN_UNSTRUCTURED_LAYOUT = "UNKNOWN_UNSTRUCTURED_LAYOUT"
    STOP_NON_CLAIM = "STOP_NON_CLAIM"


TARGET_BY_ROUTE={
    MultiSignalRoute.CMS1500:ExtractionTarget.CMS1500_STANDARD,
    MultiSignalRoute.UB04:ExtractionTarget.UB04_STANDARD,
    MultiSignalRoute.UNKNOWN_STRUCTURED:ExtractionTarget.UNKNOWN_STRUCTURED_LAYOUT,
    MultiSignalRoute.UNKNOWN_UNSTRUCTURED:ExtractionTarget.UNKNOWN_UNSTRUCTURED_LAYOUT,
    MultiSignalRoute.NON_CLAIM:ExtractionTarget.STOP_NON_CLAIM,
}


def extraction_target(route:MultiSignalRoute|str)->ExtractionTarget:
    return TARGET_BY_ROUTE[MultiSignalRoute(route)]
