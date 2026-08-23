from __future__ import annotations

import re
from decimal import Decimal
from itertools import pairwise

from packages.forms.ub04.structural_map import UB04StructuralMap
from packages.page_observation import PageObservation
from packages.page_observation import line_clustered_reading_order
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
                *, claim_total: Decimal | None = None, image=None,
                text_extractor=None) -> UB04ReconstructionResult:
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
        result = self._engine.reconstruct(
            data_tokens,
            # This legacy argument represents geometry confidence. Dynamic
            # structural evidence, not homography, is the authority here.
            registration_confidence=structure.confidence,
            claim_total=claim_total, row_boundaries=boundaries, column_ranges=column_ranges,
            geometry_strategy="PAGE_OBSERVATION_TOKEN_GEOMETRY",
            fallback_trace=["FULL_PAGE_OCR_REUSED", "OBSERVED_HEADER_COLUMNS", "NO_CELL_OCR"],
        )
        regional_calls = 0
        if image is not None and text_extractor is not None:
            for line in result.lines:
                current = line.hcpcs or ""
                # Missing/invalid HCPCS and the observed 000xx false-positive
                # family are the measured full-page recognition failures. Use
                # one bounded high-resolution retry; geometry remains primary
                # and only an exact HCPCS-shaped candidate may replace it.
                needs_retry = (
                    not re.fullmatch(r"(?:[A-Z]\d{4}|\d{5})", current)
                    or current.startswith("000")
                )
                bbox = line.column_bboxes.get("hcpcs_rate_hipps_code")
                if needs_retry and bbox is not None:
                    hcpcs_lines = text_extractor.extract_region(
                        image, *(round(value) for value in bbox)
                    )
                    regional_calls += 1
                    candidates = [
                        re.sub(r"\s", "", item.text).upper()
                        for item in line_clustered_reading_order(hcpcs_lines)
                    ]
                    valid = [
                        value for value in candidates
                        if re.fullmatch(r"(?:[A-Z]\d{4}|\d{5})", value)
                    ]
                    if len(valid) == 1:
                        line.hcpcs = valid[0]
                        line.validation_errors = [
                            reason for reason in line.validation_errors
                            if reason != "INVALID_HCPCS_FORMAT"
                        ]
                if line.units is not None:
                    continue
                units_bbox = line.column_bboxes.get("service_units")
                if units_bbox is None:
                    continue
                unit_lines = text_extractor.extract_region(
                    image, *(round(value) for value in units_bbox)
                )
                regional_calls += 1
                unit_candidates = [
                    re.sub(r"\s", "", item.text)
                    for item in line_clustered_reading_order(unit_lines)
                ]
                valid_units = [
                    value for value in unit_candidates
                    if re.fullmatch(r"\d{1,3}", value) and Decimal(value) > 0
                ]
                if len(valid_units) == 1:
                    line.units = Decimal(valid_units[0])
        if regional_calls:
            result.regional_ocr_calls = regional_calls
            result.fallback_trace = [
                *result.fallback_trace,
                f"SELECTIVE_UB_CELL_REGIONAL_OCR_{regional_calls}",
            ]
        return result
