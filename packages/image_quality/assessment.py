"""Fast, model-free page quality assessment suitable for the common path."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from packages.image_quality.contracts import ImageQualityEvidence


def _skew(binary: np.ndarray) -> float:
    lines = cv2.HoughLinesP(
        binary,
        1,
        np.pi / 180,
        threshold=80,
        minLineLength=max(30, binary.shape[1] // 8),
        maxLineGap=12,
    )
    if lines is None:
        return 0.0
    angles = [np.degrees(np.arctan2(y2 - y1, x2 - x1)) for x1, y1, x2, y2 in lines.reshape(-1, 4)]
    horizontal = [a for a in angles if abs(a) <= 15]
    return round(float(np.median(horizontal)), 3) if horizontal else 0.0


def _block_artifacts(gray: np.ndarray) -> float:
    """Estimate JPEG-like 8px boundary discontinuities relative to neighbors."""
    if min(gray.shape) < 24:
        return 0.0
    arr = gray.astype(np.float32)
    vertical = np.abs(arr[:, 8::8] - arr[:, 7:-1:8]).mean()
    horizontal = np.abs(arr[8::8, :] - arr[7:-1:8, :]).mean()
    neighbor = (np.abs(np.diff(arr, axis=0)).mean() + np.abs(np.diff(arr, axis=1)).mean()) / 2
    return float(np.clip(((vertical + horizontal) / 2 - neighbor) / 32.0, 0.0, 1.0))


def assess_image_quality(image: Image.Image) -> ImageQualityEvidence:
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    height, width = gray.shape
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    blur_score = float(laplacian.var())
    contrast = float(np.clip(gray.std() / 64.0, 0.0, 1.0))
    brightness = float(gray.mean() / 255.0)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    text_density = float(np.count_nonzero(ink) / ink.size)
    noise = float(np.clip(np.median(np.abs(laplacian)) / 32.0, 0.0, 1.0))
    border = max(1, round(min(height, width) * 0.01))
    border_ink = np.concatenate(
        (
            ink[:border].ravel(),
            ink[-border:].ravel(),
            ink[:, :border].ravel(),
            ink[:, -border:].ravel(),
        )
    )
    edge_clipping = float(np.count_nonzero(border_ink) / border_ink.size)
    rotation = 90 if height < width * 0.85 else 0
    # Letter/A4 pages are close enough for a routing estimate, never archival metadata.
    estimated_dpi = float(round(max(width / 8.5, height / 11.7), 1))
    artifacts = _block_artifacts(gray)
    reasons: list[str] = []
    if blur_score < 80:
        reasons.append("BLUR_DETECTED")
    if contrast < 0.25:
        reasons.append("LOW_CONTRAST")
    if brightness < 0.35:
        reasons.append("UNDEREXPOSED")
    if brightness > 0.98:
        reasons.append("OVEREXPOSED")
    if estimated_dpi < 150:
        reasons.append("LOW_RESOLUTION")
    if edge_clipping > 0.25:
        reasons.append("EDGE_CLIPPING")
    if artifacts > 0.25:
        reasons.append("COMPRESSION_ARTIFACTS")
    quality = float(
        np.clip(
            0.30 * min(1.0, blur_score / 250.0)
            + 0.25 * contrast
            + 0.20 * (1.0 - abs(brightness - 0.82) / 0.82)
            + 0.15 * (1.0 - edge_clipping)
            + 0.10 * (1.0 - artifacts),
            0.0,
            1.0,
        )
    )
    return ImageQualityEvidence(
        blur_score=blur_score,
        contrast=contrast,
        brightness=brightness,
        skew_degrees=_skew(ink),
        rotation_degrees=rotation,
        noise_estimate=noise,
        estimated_dpi=estimated_dpi,
        compression_artifact_estimate=artifacts,
        edge_clipping=edge_clipping,
        text_density=text_density,
        width_px=width,
        height_px=height,
        quality_score=quality,
        reason_codes=reasons,
    )
