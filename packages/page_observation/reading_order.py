from __future__ import annotations

import statistics
from typing import Iterable, Protocol, TypeVar


class PositionedText(Protocol):
    x0: float
    y0: float
    x1: float
    y1: float


T = TypeVar("T", bound=PositionedText)


def line_clustered_reading_order(items: Iterable[T]) -> list[T]:
    """Return stable line-aware reading order for OCR boxes.

    OCR boxes on one visual line commonly differ by one or two y pixels. A
    raw ``(y, x)`` sort can therefore reverse names and adjacent codes. Lines
    are clustered using a tolerance derived from median token height, then
    ordered left-to-right.
    """
    values = list(items)
    if not values:
        return []
    def coordinates(item):
        if hasattr(item, "bbox"):
            return item.bbox
        return item.x0, item.y0, item.x1, item.y1

    median_height = statistics.median(
        max(1.0, coordinates(item)[3]-coordinates(item)[1]) for item in values
    )
    tolerance = max(2.0, median_height * .55)
    lines: list[list[T]] = []
    centers: list[float] = []
    for item in sorted(values, key=lambda value: (
        (coordinates(value)[1]+coordinates(value)[3])/2, coordinates(value)[0]
    )):
        box = coordinates(item)
        center = (box[1]+box[3])/2
        best = min(
            range(len(lines)), key=lambda index: abs(center-centers[index]), default=None
        )
        if best is None or abs(center-centers[best]) > tolerance:
            lines.append([item])
            centers.append(center)
        else:
            lines[best].append(item)
            centers[best] = statistics.fmean(
                (coordinates(entry)[1]+coordinates(entry)[3])/2 for entry in lines[best]
            )
    return [
        item
        for _, line in sorted(zip(centers, lines), key=lambda pair: pair[0])
        for item in sorted(line, key=lambda value: coordinates(value)[0])
    ]
