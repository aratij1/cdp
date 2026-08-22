"""Geometry-based checkbox selection; OCR is not used for checkbox authority."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class CheckboxResult:
    selected_index: int | None
    densities: tuple[float, ...]
    ambiguous: bool


def detect_checkbox_selection(
    crop: Image.Image,
    interiors: list[tuple[int, int, int, int]],
    selected_threshold: float = 0.12,
    ambiguity_margin: float = 0.025,
) -> CheckboxResult:
    gray = np.asarray(crop.convert("L"))
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    densities: list[float] = []
    for x0, y0, x1, y1 in interiors:
        interior = ink[max(0, y0) : y1, max(0, x0) : x1]
        densities.append(
            float(np.count_nonzero(interior) / interior.size) if interior.size else 0.0
        )
    ranked = sorted(enumerate(densities), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] < selected_threshold:
        return CheckboxResult(None, tuple(densities), False)
    ambiguous = (
        len(ranked) > 1
        and ranked[1][1] >= selected_threshold
        and ranked[0][1] - ranked[1][1] < ambiguity_margin
    )
    return CheckboxResult(None if ambiguous else ranked[0][0], tuple(densities), ambiguous)
