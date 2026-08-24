"""Shared, engine-neutral OCR contracts."""

from packages.ocr.contracts import OCRCandidate, OCREngine, OCRProvider, OCRRequest, OCRResult
from packages.ocr.rapidocr_provider import RapidOCRProvider
from packages.ocr.provenance import EvidenceProvenance
from packages.ocr.execution import OCRExecutionService

__all__ = [
    "OCRCandidate",
    "OCREngine",
    "OCRProvider",
    "OCRRequest",
    "OCRResult",
    "RapidOCRProvider",
    "EvidenceProvenance",
    "OCRExecutionService",
]
