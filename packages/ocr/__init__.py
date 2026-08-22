"""Shared, engine-neutral OCR contracts."""

from packages.ocr.contracts import OCRCandidate, OCREngine, OCRProvider, OCRRequest, OCRResult
from packages.ocr.rapidocr_provider import RapidOCRProvider

__all__ = [
    "OCRCandidate",
    "OCREngine",
    "OCRProvider",
    "OCRRequest",
    "OCRResult",
    "RapidOCRProvider",
]
