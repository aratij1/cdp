from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from itertools import pairwise

from .contracts import FieldCropTruth, FieldTruth, UB04ServiceLineTruth
from .schema import FIELDS_BY_FAMILY


def _syntax_warning(field: str, value: str) -> str | None:
    if not value:
        return None
    compact = value.replace(",", "").replace("$", "")
    if field in {"total_charge", "line_charge", "charge", "units"} and not re.fullmatch(
        r"\d+(?:\.\d{1,2})?", compact
    ):
        return "UNUSUAL_NUMERIC_SYNTAX"
    if field in {"provider_npi"} and not re.fullmatch(r"\d{10}", value):
        return "UNUSUAL_NPI_SYNTAX"
    if field in {"revenue_code"} and not re.fullmatch(r"\d{4}", value):
        return "UNUSUAL_REVENUE_CODE_SYNTAX"
    return None


def validate_dataset(
    fields: Iterable[FieldTruth],
    crops: Iterable[FieldCropTruth],
    service_lines: Iterable[UB04ServiceLineTruth],
) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    fields = list(fields)
    crops = list(crops)
    service_lines = list(service_lines)
    field_keys = [(row.document_id, row.page_id, row.field_name) for row in fields]
    crop_keys = [(row.document_id, row.page_id, row.field_name) for row in crops]
    for kind, keys in (("field", field_keys), ("crop", crop_keys)):
        for key, count in Counter(keys).items():
            if count > 1:
                errors.append({"code": "DUPLICATE_ANNOTATION", "kind": kind, "key": key})
    for row in fields:
        if row.field_name not in FIELDS_BY_FAMILY.get(row.form_family, ()):
            errors.append({"code": "FIELD_NOT_IN_FORM_SCHEMA", "key": (row.document_id, row.field_name)})
        warning = _syntax_warning(row.field_name, row.normalized_truth_value)
        if warning:
            warnings.append({"code": warning, "key": (row.document_id, row.field_name)})
    for item in service_lines:
        ordered = sorted(item.rows, key=lambda row: row.bbox.y1)
        for first, second in pairwise(ordered):
            overlap = max(0.0, first.bbox.y2 - second.bbox.y1)
            smaller = min(first.bbox.y2 - first.bbox.y1, second.bbox.y2 - second.bbox.y1)
            if smaller and overlap / smaller > 0.5:
                warnings.append({"code": "UB_ROW_BOX_GROSS_OVERLAP", "key": item.document_id})
    return {
        "status": "PASS" if not errors else "FAIL",
        "field_records": len(fields),
        "crop_records": len(crops),
        "service_line_pages": len(service_lines),
        "errors": errors,
        "warnings": warnings,
    }
