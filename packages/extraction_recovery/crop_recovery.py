from __future__ import annotations


def bounded_expand_bbox(
    bbox: tuple[int, int, int, int], page_size: tuple[int, int], *,
    edge_truncated: bool, expansion_fraction: float = .012,
) -> tuple[int, int, int, int]:
    """Expand only when an upstream edge-truncation signal is present."""
    if not edge_truncated:
        return bbox
    width, height = page_size
    dx = min(round(width * .02), max(1, round(width * expansion_fraction)))
    dy = min(round(height * .02), max(1, round(height * expansion_fraction)))
    x0, y0, x1, y1 = bbox
    return max(0, x0 - dx), max(0, y0 - dy), min(width, x1 + dx), min(height, y1 + dy)
