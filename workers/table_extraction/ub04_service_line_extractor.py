"""Bounded UB-04 table-geometry recovery for evaluation/candidate use.

The component performs one regional OCR call and never invokes Docling.  It
prefers measured line/grid geometry, then falls back to the existing token
geometry and canonical template coordinates.  Runtime wiring remains on the
frozen engine until a tuning corpus with service-line truth can promote it.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from packages.templates.models import Template
from workers.page_detection.text_extraction import TextExtractor
from workers.table_extraction.ub04_service_lines import (
    UB04ReconstructionResult,
    UB04ServiceLineEngine,
    UB04Token,
)


@dataclass(frozen=True)
class UB04TableGeometry:
    row_boundaries: list[float] | None
    column_ranges: dict[str, tuple[float, float]] | None
    strategy: str
    fallback_trace: list[str]


def _group_positions(mask: np.ndarray, *, axis: int, threshold: float) -> list[int]:
    projection = (mask > 0).mean(axis=axis)
    indices = np.flatnonzero(projection >= threshold)
    groups: list[list[int]] = []
    for index in indices.tolist():
        if not groups or index > groups[-1][-1] + 1:
            groups.append([index])
        else:
            groups[-1].append(index)
    return [round(sum(group) / len(group)) for group in groups]


def detect_ub04_table_geometry(image, template: Template) -> UB04TableGeometry:
    table = template.service_line_region
    if table is None:
        return UB04TableGeometry(None, None, "NO_TABLE_CONFIGURATION", ["NO_TABLE_CONFIGURATION"])
    crop = np.asarray(image.convert("L"))[table.table_y0:table.table_y1,
                                           table.table_x0:table.table_x1]
    binary = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    horizontal = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, crop.shape[1] // 20), 1)),
    )
    vertical = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, crop.shape[0] // 16))),
    )
    ys = _group_positions(horizontal, axis=1, threshold=.20)
    xs = _group_positions(vertical, axis=0, threshold=.20)
    # PIL/NumPy crops exclude x1. Restore a missing outer table border from
    # the configured safe boundary; never infer an interior semantic column.
    if len(xs) == len(table.columns) and xs and xs[0] <= 3:
        xs.append(crop.shape[1] - 1)
    elif len(xs) == len(table.columns) and xs and xs[-1] >= crop.shape[1] - 4:
        xs.insert(0, 0)
    trace = [f"LINE_DETECTION:horizontal={len(ys)}:vertical={len(xs)}"]
    expected_columns = [column.field_name for column in table.columns]
    if 3 <= len(ys) <= table.max_rows + 2 and len(xs) == len(expected_columns) + 1:
        rows = [float(table.table_y0 + value) for value in ys]
        columns = {
            name: (float(table.table_x0 + xs[index]), float(table.table_x0 + xs[index + 1]))
            for index, name in enumerate(expected_columns)
        }
        return UB04TableGeometry(rows, columns, "DETERMINISTIC_LINE_GRID", trace)
    trace.append("DETERMINISTIC_LINE_GRID_UNAVAILABLE")
    # Projection and connected-component evidence is diagnostic only here;
    # without OCR tokens it must not manufacture semantic cell values.
    row_projection = (binary > 0).mean(axis=1)
    projection_peaks = int(np.count_nonzero(row_projection > .08))
    components = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8))[0] - 1
    trace.extend([
        f"PROJECTION_PROFILE:active_rows={projection_peaks}",
        f"CONNECTED_COMPONENTS:count={components}",
    ])
    return UB04TableGeometry(None, None, "OCR_TOKEN_GEOMETRY", trace)


class UB04ServiceLineExtractor:
    """One-call regional OCR plus bounded geometry selection."""

    def __init__(self, text_extractor: TextExtractor, engine: UB04ServiceLineEngine | None = None):
        self._text_extractor = text_extractor
        self._engine = engine or UB04ServiceLineEngine()

    def extract(
        self,
        image,
        template: Template,
        *,
        registration_confidence: float,
        claim_total=None,
    ) -> UB04ReconstructionResult:
        table = template.service_line_region
        if table is None:
            return self._engine.reconstruct(
                [], registration_confidence=registration_confidence,
                claim_total=claim_total, geometry_strategy="NO_TABLE_CONFIGURATION",
                fallback_trace=["NO_TABLE_CONFIGURATION"],
            )
        geometry = detect_ub04_table_geometry(image, template)
        lines = self._text_extractor.extract_region(
            image, table.table_x0, table.table_y0, table.table_x1, table.table_y1
        )
        tokens = [UB04Token(
            text=line.text, bbox=(line.x0, line.y0, line.x1, line.y1),
            confidence=line.confidence,
        ) for line in lines]
        trace = list(geometry.fallback_trace)
        if geometry.strategy == "OCR_TOKEN_GEOMETRY":
            trace.append("OCR_TOKEN_GEOMETRY_SELECTED" if tokens else "OCR_TOKEN_GEOMETRY_EMPTY")
        return self._engine.reconstruct(
            tokens,
            registration_confidence=registration_confidence,
            claim_total=claim_total,
            row_boundaries=geometry.row_boundaries,
            column_ranges=geometry.column_ranges,
            geometry_strategy=geometry.strategy,
            fallback_trace=trace,
        )
