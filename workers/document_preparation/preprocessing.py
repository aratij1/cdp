"""Per-page preprocessing: orientation, deskew, denoise, optional contrast.

Every transform is a pure function `(PIL.Image, params) -> (PIL.Image, dict)`
so the pipeline can record exactly what was applied (see
`packages.domain.document.PageTransform`) without ever mutating the
original decoded page in place.

Orientation detection here is a lightweight projection-profile heuristic
(good enough for machine-printed, mostly-upright scans like the supplied
dataset) â€” it is NOT a substitute for a trained OSD model. That upgrade
path is called out in the README as a known limitation.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

# Row-projection variance is identical under a 180-degree reversal. Testing
# both introduces floating-point tie flips; it provides no orientation evidence.
_ROTATIONS = (0, 90)


def _to_gray_array(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("L"))


def detect_orientation(image: Image.Image) -> int:
    """Return the rotation (degrees, clockwise) that should be applied to
    make the page upright, chosen as whichever of 0/90/180/270 maximizes
    the row-projection-profile variance (text lines create strong
    horizontal peaks only when the page is upright or upside-down; the
    0-vs-180 ambiguity is intentionally left to downstream anchor-phrase
    matching, which is cheap and authoritative for CMS-1500/UB forms)."""

    arr = _to_gray_array(image)
    best_rotation = 0
    best_score = -1.0
    for rotation in _ROTATIONS:
        rotated = np.rot90(arr, k=-rotation // 90)
        row_sums = rotated.mean(axis=1)
        score = float(row_sums.var())
        if score > best_score:
            best_score = score
            best_rotation = rotation
    return best_rotation


def apply_orientation(image: Image.Image, rotation: int) -> Image.Image:
    if rotation == 0:
        return image
    return image.rotate(-rotation, expand=True)


def detect_skew_angle(image: Image.Image, max_angle: float = 15.0) -> float:
    """Estimate small-angle skew (degrees) via minAreaRect over ink pixels."""

    arr = _to_gray_array(image)
    _, binary = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = cv2.findNonZero(binary)
    if coords is None:
        return 0.0
    angle = cv2.minAreaRect(coords)[-1]
    # cv2.minAreaRect returns angle in (-90, 0]; normalize to a small skew
    if angle < -45:
        angle = 90 + angle
    if abs(angle) > max_angle:
        return 0.0
    return round(float(angle), 3)


def deskew(image: Image.Image, angle: float) -> Image.Image:
    if abs(angle) < 0.05:
        return image
    arr = _to_gray_array(image)
    (h, w) = arr.shape
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        arr, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return Image.fromarray(rotated)


def denoise(image: Image.Image) -> Image.Image:
    """Median blur, not `fastNlMeansDenoising` -- the latter is tuned for
    photographic sensor noise and its default search window costs ~8.5s on
    a real ~1700x2200 scanned page (measured in
    tests/performance/test_throughput.py against the real dataset: it was
    the dominant cost in the whole preparation pipeline, 0.15 pages/sec).
    Median blur is both ~300x cheaper and the more appropriate tool for
    scan/fax salt-and-pepper artifacts. `fastNlMeansDenoising` is still
    available for the OCR-retry path (workers/retry/
    alternate_preprocessing.py), where it only ever runs on a single
    failed field's small crop -- the cost is trivial there."""
    arr = _to_gray_array(image)
    denoised = cv2.medianBlur(arr, 3)
    return Image.fromarray(denoised)


def enhance_contrast(image: Image.Image, clip_limit: float = 2.0) -> Image.Image:
    arr = _to_gray_array(image)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    enhanced = clahe.apply(arr)
    return Image.fromarray(enhanced)


def make_thumbnail(image: Image.Image, max_dimension: int = 300) -> Image.Image:
    thumb = image.copy()
    thumb.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    return thumb
