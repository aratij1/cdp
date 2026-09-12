from __future__ import annotations

import re
from statistics import median
from typing import Protocol

from packages.domain.common import BoundingBox

from .models import LayoutLine, LayoutToken


class GeometricText(Protocol):
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float


def normalize_text(value: str) -> str:
    value = value.casefold().replace("|", "i")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def reconstruct(lines: list[GeometricText], *, page_number: int, width: int, height: int,
                engine: str) -> list[LayoutLine]:
    """Cluster OCR words by baseline, then order columns left-to-right."""
    if not lines:
        return []
    heights = [max(line.y1 - line.y0, 1) for line in lines]
    tolerance = max(3.0, median(heights) * .55)
    rows: list[list[GeometricText]] = []
    for item in sorted(lines, key=lambda value: ((value.y0 + value.y1) / 2, value.x0)):
        center = (item.y0 + item.y1) / 2
        target = next((row for row in rows if abs(center - sum((x.y0+x.y1)/2 for x in row)/len(row)) <= tolerance), None)
        if target is None:
            rows.append([item])
        else:
            target.append(item)
    result = []
    token_order = 0
    for line_index, row in enumerate(rows):
        row = sorted(row, key=lambda value: value.x0)
        tokens = []
        for item in row:
            tokens.append(LayoutToken(
                text=item.text, normalized_text=normalize_text(item.text),
                confidence=item.confidence,
                bbox=BoundingBox(x0=item.x0, y0=item.y0, x1=item.x1, y1=item.y1,
                                 image_width=width, image_height=height),
                page_number=page_number, engine=engine, reading_order=token_order,
            ))
            token_order += 1
        result.append(LayoutLine(
            tokens=tokens, text=" ".join(token.text for token in tokens), reading_order=line_index,
            bbox=BoundingBox(x0=min(x.x0 for x in row), y0=min(x.y0 for x in row),
                             x1=max(x.x1 for x in row), y1=max(x.y1 for x in row),
                             image_width=width, image_height=height),
        ))
    return result


def field_lines(lines: list[LayoutLine]) -> list[LayoutLine]:
    """Keep table rows intact elsewhere; separate distant columns for field linking."""
    result: list[LayoutLine] = []
    for line in lines:
        groups: list[list[LayoutToken]] = []
        for token in sorted(line.tokens, key=lambda t:t.bbox.x0):
            if groups:
                previous = groups[-1][-1].bbox
                gap = token.bbox.x0 - previous.x1
                height = max(previous.y1-previous.y0, token.bbox.y1-token.bbox.y0, 1)
            if not groups or gap > 2*height:
                groups.append([])
            groups[-1].append(token)
        for group in groups:
            result.append(LayoutLine(tokens=group, text=" ".join(t.text for t in group),
                reading_order=len(result), bbox=BoundingBox(
                    x0=min(t.bbox.x0 for t in group), y0=min(t.bbox.y0 for t in group),
                    x1=max(t.bbox.x1 for t in group), y1=max(t.bbox.y1 for t in group),
                    image_width=line.bbox.image_width,image_height=line.bbox.image_height)))
    return result
