from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import Field

from packages.domain.common import DomainModel
from packages.layout_intelligence.datatypes import valid
from packages.layout_intelligence.models import LayoutLine
from packages.layout_intelligence.reading_order import normalize_text


HEADERS = {
    "revenue_code": ("revenue code", "rev code", "revenue"),
    "procedure_code": ("procedure", "cpt", "hcpcs"),
    "description": ("description",),
    "service_date": ("service date", "date of service", "dos"),
    "units": ("units", "qty", "quantity"),
    "charge": ("charge", "amount", "total"),
}


class GenericServiceLine(DomainModel):
    revenue_code: str | None = None
    procedure_code: str | None = None
    description: str | None = None
    service_date: str | None = None
    units: Decimal | None = None
    charge: Decimal | None = None


class TableResult(DomainModel):
    detected: bool
    confidence: float = Field(ge=0, le=1)
    headers: dict[str, float]
    rows: list[GenericServiceLine]
    reason_codes: list[str]
    requires_docling: bool = False


def reconstruct_table(lines: list[LayoutLine]) -> TableResult:
    """Local-first reconstruction from aligned token columns and row baselines."""
    header_index, mapping = None, {}
    for index, line in enumerate(lines):
        for token in line.tokens:
            normalized = normalize_text(token.text)
            for field, aliases in HEADERS.items():
                if any(alias in normalized for alias in aliases):
                    mapping[field] = (token.bbox.x0 + token.bbox.x1) / 2
        if len(mapping) >= 3:
            header_index = index
            break
    if header_index is None:
        return TableResult(detected=False, confidence=0, headers={}, rows=[],
                           reason_codes=["TABLE_HEADERS_INSUFFICIENT"])
    ordered = sorted(mapping.items(), key=lambda item: item[1])
    rows = []
    for line in lines[header_index + 1:]:
        if len(line.tokens) < 2:
            continue
        values = {}
        for token in line.tokens:
            field = min(ordered, key=lambda item: abs(item[1] - (token.bbox.x0+token.bbox.x1)/2))[0]
            values[field] = (values.get(field, "") + " " + token.text).strip()
        if len(values) < 2:
            continue
        try:
            units = Decimal(values["units"].replace(",", "")) if "units" in values else None
        except InvalidOperation:
            units = None
        try:
            charge = Decimal(values["charge"].replace("$", "").replace(",", "")) if "charge" in values else None
        except InvalidOperation:
            charge = None
        rows.append(GenericServiceLine(
            revenue_code=values.get("revenue_code") if valid(values.get("revenue_code", ""), "REVENUE_CODE") else None,
            procedure_code=values.get("procedure_code") if valid(values.get("procedure_code", ""), "CPT_HCPCS") else None,
            description=values.get("description"), service_date=values.get("service_date"),
            units=units, charge=charge,
        ))
    confidence = min(1.0, len(mapping) / len(HEADERS) * .7 + min(len(rows), 3) * .1)
    return TableResult(
        detected=True, confidence=confidence,
        headers={field: x for field, x in ordered}, rows=rows,
        reason_codes=["OCR_COLUMN_ALIGNMENT", "HEADER_COLUMN_MAPPING"],
        requires_docling=confidence < .65,
    )
