from __future__ import annotations

import re
from decimal import Decimal
from itertools import pairwise

from packages.forms.ub04.structural_map import UB04StructuralMap
from packages.page_observation import PageObservation
from workers.table_extraction.ub04_service_lines import (
    UB04ReconstructionResult,
    UB04ServiceLineEngine,
    UB04Token,
)


class UB04ObservationServiceLineExtractor:
    """Reconstruct UB rows from the already-computed full-page OCR tokens."""

    version = "ub04-observation-service-lines-v1"

    def __init__(self, engine: UB04ServiceLineEngine | None = None):
        self._engine = engine or UB04ServiceLineEngine()

    def extract(self, observation: PageObservation, structure: UB04StructuralMap,
                *, claim_total: Decimal | None = None) -> UB04ReconstructionResult:
        region = structure.service_table_region
        if region is None:
            return self._engine.reconstruct(
                [], registration_confidence=0, claim_total=claim_total,
                geometry_strategy="STRUCTURAL_REGION_UNAVAILABLE",
                fallback_trace=["STRUCTURAL_REGION_UNAVAILABLE"],
            )
        x0, y0, x1, y1 = region
        tokens = [UB04Token(text=token.text, bbox=token.bbox, confidence=token.confidence)
                  for token in observation.ocr_tokens
                  if x0 <= (token.bbox[0]+token.bbox[2])/2 <= x1
                  and y0 <= (token.bbox[1]+token.bbox[3])/2 <= y1]
        normalized = lambda value: re.sub(r"[^A-Z0-9]", "", value.upper())
        header_aliases = {
            "revenue_code": {"REV", "REVENUECODE"},
            "description": {"DESCRIPTION"},
            "hcpcs_rate_hipps_code": {"HCPCS", "HCPCSRATEHIPPSCODE"},
            "service_date": {"SERVICEDATE"},
            "service_units": {"UNITS", "SERVICEUNITS"},
            "total_charges": {"CHARGE", "TOTALCHARGES"},
        }
        headers = {}
        for name, aliases in header_aliases.items():
            match = next((token for token in observation.ocr_tokens
                          if normalized(token.text) in aliases
                          and x0 <= (token.bbox[0]+token.bbox[2])/2 <= x1
                          and y0 <= (token.bbox[1]+token.bbox[3])/2 <= y1), None)
            if match:
                headers[name] = match
        column_ranges = None
        header_bottom = y0
        if len(headers) >= 6:
            ordered_headers = sorted(headers.items(), key=lambda item: item[1].bbox[0])
            centers = [(token.bbox[0]+token.bbox[2])/2 for _, token in ordered_headers]
            boundaries_x = [float(x0)] + [float((left+right)/2)
                for left, right in pairwise(centers)] + [float(x1)]
            column_ranges = {name: (boundaries_x[index], boundaries_x[index+1])
                             for index, (name, _) in enumerate(ordered_headers)}
            header_bottom = max(token.bbox[3] for _, token in ordered_headers)
        data_tokens = [token for token in tokens if token.bbox[1] > header_bottom + 3]
        centers_y = sorted((token.bbox[1]+token.bbox[3])/2 for token in data_tokens)
        row_centers: list[float] = []
        for center in centers_y:
            if not row_centers or center-row_centers[-1] > .012*observation.height:
                row_centers.append(center)
            else:
                row_centers[-1] = (row_centers[-1]+center)/2
        if len(row_centers) >= 2:
            gaps = [b-a for a, b in pairwise(row_centers)]
            typical = min(gaps)
            kept = [row_centers[0]]
            for center in row_centers[1:]:
                if center-kept[-1] > max(.08*observation.height, 2.2*typical):
                    break
                kept.append(center)
            row_centers = kept
        boundaries = None
        if row_centers:
            gap = (row_centers[1]-row_centers[0]) if len(row_centers) > 1 else .04*observation.height
            boundaries = [row_centers[0]-gap/2] + [
                (left+right)/2 for left, right in pairwise(row_centers)
            ] + [row_centers[-1]+gap/2]
        return self._engine.reconstruct(
            data_tokens,
            # This legacy argument represents geometry confidence. Dynamic
            # structural evidence, not homography, is the authority here.
            registration_confidence=structure.confidence,
            claim_total=claim_total, row_boundaries=boundaries, column_ranges=column_ranges,
            geometry_strategy="PAGE_OBSERVATION_TOKEN_GEOMETRY",
            fallback_trace=["FULL_PAGE_OCR_REUSED", "OBSERVED_HEADER_COLUMNS", "NO_CELL_OCR"],
        )
