"""Template-guided local translation correction after page homography."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from packages.templates.models import FieldRegion


@dataclass(frozen=True)
class LocalCropResult:
    crop: Image.Image
    offset_x: int
    offset_y: int
    match_score: float
    accepted: bool
    box: tuple[int, int, int, int]


def align_field_crop(
    aligned_page: Image.Image,
    reference_page: Image.Image,
    region: FieldRegion,
    search_radius: int = 14,
    minimum_score: float = 0.25,
) -> LocalCropResult:
    """Correct residual x/y error by matching printed form structure."""
    page = np.asarray(aligned_page.convert("L"))
    reference = np.asarray(reference_page.convert("L"))
    height, width = page.shape
    pad = region.padding_px
    target_box = (
        max(0, region.x0 - pad),
        max(0, region.y0 - pad),
        min(width, region.x1 + pad),
        min(height, region.y1 + pad),
    )
    x0, y0, x1, y1 = target_box
    template_edges = cv2.Canny(reference[y0:y1, x0:x1], 40, 120)
    sx0, sy0 = max(0, x0 - search_radius), max(0, y0 - search_radius)
    sx1, sy1 = min(width, x1 + search_radius), min(height, y1 + search_radius)
    search_edges = cv2.Canny(page[sy0:sy1, sx0:sx1], 40, 120)
    if (
        template_edges.size == 0
        or np.count_nonzero(template_edges) < 5
        or search_edges.shape[0] < template_edges.shape[0]
        or search_edges.shape[1] < template_edges.shape[1]
    ):
        return LocalCropResult(aligned_page.crop(target_box), 0, 0, 0.0, False, target_box)
    scores = cv2.matchTemplate(search_edges, template_edges, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(scores)
    corrected_x0, corrected_y0 = sx0 + location[0], sy0 + location[1]
    corrected = (
        corrected_x0,
        corrected_y0,
        corrected_x0 + (x1 - x0),
        corrected_y0 + (y1 - y0),
    )
    accepted = float(score) >= minimum_score
    box = corrected if accepted else target_box
    return LocalCropResult(
        aligned_page.crop(box),
        box[0] - x0,
        box[1] - y0,
        float(score),
        accepted,
        box,
    )
