"""Alternate preprocessing presets for OCR retry -- deliberately different
from `workers.document_preparation.preprocessing`'s defaults (more
aggressive contrast, upscaling, hard binarization) since the point of a
retry is to try something *different*, not repeat what already failed.
Applied to a single failed field's crop, never a whole page -- retries are
field-scoped and therefore cheap.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image
from dataclasses import dataclass

UPSCALE_FACTOR = 2.0
AGGRESSIVE_CLAHE_CLIP_LIMIT = 4.0


def _to_gray_array(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("L"))


def upscale(image: Image.Image, factor: float = UPSCALE_FACTOR) -> Image.Image:
    new_size = (int(image.width * factor), int(image.height * factor))
    return image.resize(new_size, Image.LANCZOS)


def aggressive_contrast(image: Image.Image) -> Image.Image:
    arr = _to_gray_array(image)
    clahe = cv2.createCLAHE(clipLimit=AGGRESSIVE_CLAHE_CLIP_LIMIT, tileGridSize=(4, 4))
    return Image.fromarray(clahe.apply(arr))


def binarize(image: Image.Image) -> Image.Image:
    arr = _to_gray_array(image)
    _, binary = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(binary)


def sharpen(image: Image.Image) -> Image.Image:
    arr = _to_gray_array(image)
    blurred = cv2.GaussianBlur(arr, (0, 0), sigmaX=3)
    sharpened = cv2.addWeighted(arr, 1.5, blurred, -0.5, 0)
    return Image.fromarray(sharpened)


def strong_denoise(image: Image.Image) -> Image.Image:
    """`fastNlMeansDenoising` -- too expensive (~8.5s, measured against a
    real full page in tests/performance/test_throughput.py) to run
    unconditionally on every page in the default pipeline
    (workers.document_preparation.preprocessing.denoise uses a median
    blur instead), but a single failed field's crop is small enough that
    the cost is trivial here, and it genuinely outperforms a median blur
    on heavier scan noise."""
    arr = _to_gray_array(image)
    return Image.fromarray(cv2.fastNlMeansDenoising(arr, h=10))


def adaptive_threshold(image: Image.Image) -> Image.Image:
    arr = _to_gray_array(image)
    return Image.fromarray(
        cv2.adaptiveThreshold(
            arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
        )
    )


def invert_binary(image: Image.Image) -> Image.Image:
    return Image.fromarray(cv2.bitwise_not(_to_gray_array(image)))


def remove_printed_lines(
    image: Image.Image,
    maximum_ink_loss: float = 0.18,
) -> tuple[Image.Image, bool, float]:
    """Remove form rules, rejecting the transform when too much ink is lost."""
    gray = _to_gray_array(image)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(12, image.width // 8), 1)
    )
    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(12, image.height // 3))
    )
    rules = cv2.bitwise_or(
        cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel),
        cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel),
    )
    cleaned = cv2.bitwise_and(binary, cv2.bitwise_not(rules))
    original_ink = int(np.count_nonzero(binary))
    if original_ink < max(3, int(binary.size * 0.001)):
        return image.copy(), True, 0.0
    ink_loss = 1.0 - (np.count_nonzero(cleaned) / original_ink)
    accepted = ink_loss <= maximum_ink_loss
    if not accepted:
        return image.copy(), False, float(ink_loss)
    return Image.fromarray(cv2.bitwise_not(cleaned)), True, float(ink_loss)


# Applied in this order until one preset's OCR result beats the original
# confidence -- upscale first (cheapest, often sufficient for small text),
# then contrast, then stronger denoising, then a hard binarize + sharpen
# combination as a last resort.
PRESETS: list[tuple[str, list]] = [
    ("upscale", [upscale]),
    ("aggressive_contrast", [aggressive_contrast]),
    ("upscale_and_contrast", [upscale, aggressive_contrast]),
    ("strong_denoise", [strong_denoise]),
    ("binarize_and_sharpen", [sharpen, binarize]),
    ("adaptive_threshold", [adaptive_threshold]),
]

PRESET_STEPS = dict(PRESETS)


@dataclass(frozen=True)
class PreprocessingContext:
    """Signals available at retry time; contains no field values or PHI."""

    field_type: str = "text"
    quality_score: float | None = None
    failure_reason: str | None = None
    registration_confidence: float | None = None


class PreprocessingRouter:
    """Select a small, deterministic retry portfolio from observable evidence."""

    max_variants = 2

    def select(self, context: PreprocessingContext) -> tuple[str, ...]:
        field_type = context.field_type.casefold()
        reason = (context.failure_reason or "").casefold()
        selected: list[str] = []

        def add(name: str) -> None:
            if name not in selected and len(selected) < self.max_variants:
                selected.append(name)

        if "line" in reason or "grid" in reason or "table" in reason:
            add("adaptive_threshold")
        if "noise" in reason or (context.quality_score is not None and context.quality_score < .45):
            add("strong_denoise")
        if "blur" in reason or "small" in reason or field_type in {"date", "currency", "number", "code"}:
            add("upscale_and_contrast")
        if "contrast" in reason or "faint" in reason:
            add("aggressive_contrast")
        if context.registration_confidence is not None and context.registration_confidence < .85:
            add("upscale")
        add("upscale")
        add("binarize_and_sharpen")
        return tuple(selected)


def apply_preset(image: Image.Image, steps: list) -> Image.Image:
    result = image
    for step in steps:
        result = step(result)
    return result
