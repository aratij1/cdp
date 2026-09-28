"""Composition helpers that wire concrete worker OCR adapters into packages.

This is the only module that builds OCRRouter engine factories from worker
extractors. Packages must never import these adapters directly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from packages.ocr_contracts import ModelNotAvailableError, TextLine
from packages.ocr_router import ENGINE_ORDER, OCRObservation, OCRRouteRequest, Recognizer


def regional_factory(engine: str) -> Recognizer:
    """Build a regional recognizer for rapidocr / paddleocr / tesseract."""
    if engine == "rapidocr":
        from workers.page_detection.text_extraction import RapidOCRTextExtractor

        extractor = RapidOCRTextExtractor()
    elif engine == "paddleocr":
        from workers.page_detection.text_extraction import PaddleOCRTextExtractor

        extractor = PaddleOCRTextExtractor()
    else:
        from workers.cascade.tesseract_adapter import TesseractTextExtractor

        extractor = TesseractTextExtractor()

    def recognize(request: OCRRouteRequest) -> OCRObservation:
        from packages.ocr_runtime_lock import ocr_inference_lock

        try:
            with ocr_inference_lock(engine):
                lines = extractor.extract_region(request.image, *request.bbox)
        except FileNotFoundError as exc:
            if engine != "tesseract":
                raise
            raise ModelNotAvailableError("Tesseract executable unavailable") from exc
        return OCRObservation(tuple(lines))

    return recognize


def handwriting_factory() -> Recognizer:
    """Build a TrOCR handwriting recognizer (lazy adapter construction)."""
    from workers.unstructured_extraction.trocr_adapter import TrOCRAdapter

    recognizer = TrOCRAdapter()

    def recognize(request: OCRRouteRequest) -> OCRObservation:
        try:
            result = recognizer.recognize(request.image.crop(request.bbox))
        except RuntimeError as exc:
            # The existing TrOCR adapter wraps missing optional imports only.
            if not isinstance(exc.__cause__, ImportError):
                raise
            raise ModelNotAvailableError("TrOCR dependencies unavailable") from exc
        lines = (
            ()
            if result.text is None
            else (TextLine(result.text, *request.bbox, result.confidence),)
        )
        return OCRObservation(lines, result.insufficient_evidence)

    return recognize


def build_default_ocr_engine_factories() -> Mapping[str, Callable[[], Recognizer]]:
    """Four ordered factories for OCRRouter (process-level model reuse inside)."""
    return {
        "rapidocr": lambda: regional_factory("rapidocr"),
        "paddleocr": lambda: regional_factory("paddleocr"),
        "tesseract": lambda: regional_factory("tesseract"),
        "trocr": handwriting_factory,
    }


def configure_default_ocr_engine_factories() -> None:
    """Register default worker factories on the package OCRRouter registry."""
    from packages.ocr_router import configure_ocr_engine_factories

    configure_ocr_engine_factories(build_default_ocr_engine_factories())


def _tesseract_region_text(image, box: tuple[int, int, int, int]) -> str:
    return _tesseract_region_text_psm(image, box, 6)


def _tesseract_region_text_confirm(image, box: tuple[int, int, int, int]) -> str:
    """Second segmentation. Disagreement blocks a one-pass insurance-row veto."""
    return _tesseract_region_text_psm(image, box, 11)


def _tesseract_region_text_psm(image, box: tuple[int, int, int, int], psm: int) -> str:
    from workers.cascade.tesseract_adapter import TesseractTextExtractor

    x0, y0, x1, y1 = box
    crop = image.crop((x0, y0, x1, y1))
    lines = TesseractTextExtractor(psm=psm).extract(crop)
    return " ".join(
        str(line.text if hasattr(line, "text") else line) for line in lines
    ).upper()


def _build_gpt4o_vision_adapter(**kwargs):
    from workers.vlm_fallback.adapter import AzureOpenAIVisionAdapter

    return AzureOpenAIVisionAdapter(**kwargs)


def _build_azure_review_adapter(settings):
    from workers.vlm_fallback.factory import build_azure_review_adapter

    return build_azure_review_adapter(settings)


def _get_shared_trocr_adapter(**kwargs):
    from workers.unstructured_extraction.trocr_adapter import get_shared_trocr_adapter

    return get_shared_trocr_adapter(**kwargs)


def wire_package_ocr_providers() -> None:
    """Composition root: inject all worker-backed providers into packages."""
    configure_default_ocr_engine_factories()

    from packages.azure_di_contracts import configure_azure_di_read_engine_factory
    from packages.extraction_recovery.dob_trocr_residual import (
        configure_trocr_adapter_factory,
    )
    from packages.extraction_recovery.gpt4o_crop_residual import (
        configure_claude_vision_adapter_factory,
        configure_gpt4o_vision_adapter_factory,
    )
    from packages.extraction_recovery.unstructured_reg_fallback import (
        configure_azure_review_adapter_factory,
    )
    from packages.recovery.registration_content import configure_registration_region_ocr
    from workers.cascade.azure_di_factory import build_azure_read_engine
    from workers.vlm_fallback.factory import build_anthropic_claude_adapter

    configure_azure_di_read_engine_factory(build_azure_read_engine)
    configure_trocr_adapter_factory(_get_shared_trocr_adapter)
    configure_gpt4o_vision_adapter_factory(_build_gpt4o_vision_adapter)
    configure_claude_vision_adapter_factory(build_anthropic_claude_adapter)
    configure_azure_review_adapter_factory(_build_azure_review_adapter)
    configure_registration_region_ocr(
        _tesseract_region_text,
        confirm_factory=_tesseract_region_text_confirm,
    )


# Back-compat aliases matching former packages.ocr_router private names.
_regional_factory = regional_factory
_handwriting_factory = handwriting_factory

assert set(build_default_ocr_engine_factories()) == set(ENGINE_ORDER)
