"""Canonical-template to page-coordinate polygon transformation."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TransformedRegion:
    source_polygon: tuple[tuple[float, float], ...]
    mapped_polygon: tuple[tuple[float, float], ...]
    bbox: tuple[int, int, int, int] | None
    valid: bool
    reason_code: str


def transform_template_region(
    bbox: tuple[int, int, int, int],
    matrix: list[list[float]],
    page_size: tuple[int, int] | None = None,
) -> TransformedRegion:
    """Map all four corners through a homography and validate the result."""
    x0, y0, x1, y1 = bbox
    source = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    if x1 <= x0 or y1 <= y0 or len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        return TransformedRegion(source, (), None, False, "INVALID_SOURCE_OR_MATRIX")
    mapped = []
    for x, y in source:
        denominator = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
        if abs(denominator) < 1e-9:
            return TransformedRegion(source, tuple(mapped), None, False, "DEGENERATE_TRANSFORM")
        point = (
            (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / denominator,
            (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / denominator,
        )
        if not all(math.isfinite(item) for item in point):
            return TransformedRegion(source, tuple(mapped), None, False, "NONFINITE_TRANSFORM")
        mapped.append(point)
    polygon = tuple(mapped)
    if not _convex(polygon):
        return TransformedRegion(source, polygon, None, False, "INVALID_TRANSFORMED_POLYGON")
    low_x, high_x = min(x for x, _ in polygon), max(x for x, _ in polygon)
    low_y, high_y = min(y for _, y in polygon), max(y for _, y in polygon)
    if page_size:
        width, height = page_size
        low_x, high_x = max(0, low_x), min(width, high_x)
        low_y, high_y = max(0, low_y), min(height, high_y)
    transformed_bbox = (round(low_x), round(low_y), round(high_x), round(high_y))
    if transformed_bbox[2] <= transformed_bbox[0] or transformed_bbox[3] <= transformed_bbox[1]:
        return TransformedRegion(source, polygon, None, False, "TRANSFORM_OUTSIDE_PAGE")
    return TransformedRegion(source, polygon, transformed_bbox, True, "TRANSFORMED_POLYGON_VALID")


def _convex(polygon: tuple[tuple[float, float], ...]) -> bool:
    signs = []
    for index in range(len(polygon)):
        a, b, c = polygon[index], polygon[(index + 1) % 4], polygon[(index + 2) % 4]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) > 1e-7:
            signs.append(cross > 0)
    return bool(signs) and all(item == signs[0] for item in signs)
