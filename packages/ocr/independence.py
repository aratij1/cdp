"""Canonical independence groups; model variants are not independent votes."""


def independence_group(engine: str) -> str:
    normalized = engine.lower()
    if "rapidocr" in normalized:
        return "RAPIDOCR_FAMILY"
    if "paddle" in normalized or "pp-ocr" in normalized:
        return "PADDLE_FAMILY"
    if "tesseract" in normalized:
        return "TESSERACT_FAMILY"
    if "gemini" in normalized:
        return "GEMINI_FAMILY"
    if "textract" in normalized:
        return "TEXTRACT_FAMILY"
    if "trocr" in normalized:
        return "TROCR_FAMILY"
    if "florence" in normalized:
        return "FLORENCE_FAMILY"
    if "got-ocr" in normalized or "got_ocr" in normalized:
        return "GOT_OCR_FAMILY"
    if "azure" in normalized:
        return "AZURE_READ_FAMILY"
    return normalized.upper()
