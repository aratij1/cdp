"""Low-cost template-lineage compatibility evidence.

This module deliberately answers a narrower question than registration:
whether two pages contain sufficiently similar *form structure* to justify an
expensive keypoint/homography attempt.  A family nomination is not treated as
proof that a particular reference asset is geometrically compatible.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from packages.template_compatibility import (
    TemplateCompatibilityEvidence,
    TemplateCompatibilityStatus,
)


def _normalize(values: np.ndarray) -> np.ndarray:
    values = values.astype(np.float64, copy=False)
    total = float(values.sum())
    return values / total if total else np.zeros_like(values)


def _intersection(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.minimum(_normalize(left), _normalize(right)).sum())


def _signature(image: Image.Image) -> dict[str, np.ndarray | float]:
    gray = np.asarray(image.convert("L").resize((384, 512)), dtype=np.uint8)
    edges = cv2.Canny(gray, 60, 180) > 0
    horizontal = cv2.morphologyEx(
        edges.astype(np.uint8), cv2.MORPH_OPEN, np.ones((1, 15), np.uint8)
    ) > 0
    vertical = cv2.morphologyEx(
        edges.astype(np.uint8), cv2.MORPH_OPEN, np.ones((15, 1), np.uint8)
    ) > 0
    grid = cv2.resize(
        edges.astype(np.float32), (12, 16), interpolation=cv2.INTER_AREA
    ).ravel()
    top_grid = cv2.resize(
        edges[:170].astype(np.float32), (12, 4), interpolation=cv2.INTER_AREA
    ).ravel()
    return {
        "horizontal_projection": horizontal.mean(axis=1),
        "vertical_projection": vertical.mean(axis=0),
        "layout_grid": grid,
        "top_grid": top_grid,
        "line_density": float(horizontal.mean() + vertical.mean()),
    }


def assess_template_compatibility(
    candidate: Image.Image,
    reference: Image.Image,
    *,
    family: str | None = None,
    family_compatibility: float = 1.0,
    anchor_visibility: float | None = None,
) -> TemplateCompatibilityEvidence:
    """Return deterministic, OCR-free evidence in normalized coordinates.

    Thresholds are deliberately conservative: ``INCOMPATIBLE`` only prevents
    an expensive SIFT attempt; it never authorizes a fixed-form extractor.
    ``PARTIALLY_COMPATIBLE`` still permits registration.
    """

    candidate_aspect = candidate.width / max(candidate.height, 1)
    reference_aspect = reference.width / max(reference.height, 1)
    aspect = min(candidate_aspect, reference_aspect) / max(candidate_aspect, reference_aspect)
    source, target = _signature(candidate), _signature(reference)
    horizontal = _intersection(
        source["horizontal_projection"], target["horizontal_projection"]
    )
    vertical = _intersection(source["vertical_projection"], target["vertical_projection"])
    projections = (horizontal + vertical) / 2
    layout = _intersection(source["layout_grid"], target["layout_grid"])
    density_left = float(source["line_density"])
    density_right = float(target["line_density"])
    line_structure = (
        min(density_left, density_right) / max(density_left, density_right)
        if max(density_left, density_right)
        else 0.0
    )
    fingerprint = 0.55 * layout + 0.45 * projections
    measured_anchor = _intersection(source["top_grid"], target["top_grid"])
    anchor = measured_anchor if anchor_visibility is None else float(anchor_visibility)
    score = float(np.clip(
        0.12 * aspect
        + 0.23 * line_structure
        + 0.20 * projections
        + 0.20 * layout
        + 0.10 * anchor
        + 0.10 * fingerprint
        + 0.05 * family_compatibility,
        0.0,
        1.0,
    ))
    if aspect < 0.85:
        status = TemplateCompatibilityStatus.INCOMPATIBLE
        reasons = ("ASPECT_RATIO_MISMATCH",)
    elif score >= 0.72:
        status = TemplateCompatibilityStatus.COMPATIBLE
        reasons = ("FORM_STRUCTURE_COMPATIBLE",)
    elif score >= 0.55:
        status = TemplateCompatibilityStatus.PARTIALLY_COMPATIBLE
        reasons = ("FORM_STRUCTURE_PARTIAL",)
    else:
        status = TemplateCompatibilityStatus.INCOMPATIBLE
        reasons = ("TEMPLATE_LINEAGE_MISMATCH",)
    return TemplateCompatibilityEvidence(
        family=family,
        family_compatibility=float(np.clip(family_compatibility, 0, 1)),
        aspect_ratio_similarity=aspect,
        line_structure_similarity=line_structure,
        edge_projection_similarity=projections,
        anchor_visibility=float(np.clip(anchor, 0, 1)),
        normalized_layout_similarity=layout,
        form_fingerprint_similarity=fingerprint,
        compatibility_score=score,
        status=status,
        reason_codes=reasons,
    )
