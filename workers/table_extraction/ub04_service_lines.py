"""UB-04 service-line reconstruction and fail-closed structural validation."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

from workers.table_extraction.normalization import normalize_cell
from workers.table_extraction.template_registration import load_spec


class UB04Token(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float = Field(ge=0, le=1)


class UB04ServiceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_number: int = Field(ge=1)
    revenue_code: str | None = None
    description: str | None = None
    hcpcs: str | None = None
    service_date: date | None = None
    units: Decimal | None = None
    charge: Decimal | None = None
    non_covered_charge: Decimal | None = None
    source_token_count: int = Field(default=0, ge=0)
    mean_confidence: float = Field(default=0, ge=0, le=1)
    validation_errors: list[str] = Field(default_factory=list)
    automatically_eligible: bool = False


class UB04ReconstructionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: list[UB04ServiceLine]
    unassigned_tokens: int = Field(ge=0)
    geometry_valid: bool
    totals_reconciled: bool | None = None
    escalation: str | None = None
    reason_codes: list[str] = Field(default_factory=list)


_HCPCS = re.compile(r"(?:[A-Z]\d{4}|\d{5})")


class UB04ServiceLineEngine:
    """Associate registered OCR tokens to FL42-FL48 rows before parsing values."""

    def __init__(self, hcpcs_reference: set[str] | None = None) -> None:
        self._spec = load_spec("UB04")
        self._hcpcs_reference = hcpcs_reference

    def reconstruct(
        self,
        tokens: list[UB04Token],
        *,
        registration_confidence: float,
        claim_total: Decimal | None = None,
    ) -> UB04ReconstructionResult:
        if registration_confidence < 0.80:
            return UB04ReconstructionResult(
                lines=[], unassigned_tokens=len(tokens), geometry_valid=False,
                escalation="DOCLING", reason_codes=["LOW_REGISTRATION_CONFIDENCE"],
            )
        rows = self._spec["rows"]
        row_height = (rows["last_y"] - rows["first_y"]) / rows["count"]
        buckets: dict[int, dict[str, list[UB04Token]]] = {}
        unassigned = 0
        for token in tokens:
            x = (token.bbox[0] + token.bbox[2]) / 2
            y = (token.bbox[1] + token.bbox[3]) / 2
            row_index = int((y - rows["first_y"]) // row_height)
            field = next((f for f in self._spec["fields"] if f["x0"] <= x < f["x1"]), None)
            if not 0 <= row_index < rows["count"] or field is None:
                unassigned += 1
                continue
            buckets.setdefault(row_index, {}).setdefault(field["semantic_field_name"], []).append(token)

        if tokens and unassigned / len(tokens) > 0.25:
            return UB04ReconstructionResult(
                lines=[], unassigned_tokens=unassigned, geometry_valid=False,
                escalation="DOCLING", reason_codes=["TABLE_GEOMETRY_UNRELIABLE"],
            )
        lines = [self._parse_row(index, cells) for index, cells in sorted(buckets.items())]
        lines = [line for line in lines if line.source_token_count]
        total_ok = self._reconcile_totals(lines, claim_total)
        reasons: list[str] = []
        if total_ok is False:
            reasons.append("TOTAL_CHARGES_MISMATCH")
            for line in lines:
                line.automatically_eligible = False
        elif total_ok is None and lines:
            reasons.append("TOTAL_RECONCILIATION_UNAVAILABLE")
            for line in lines:
                line.automatically_eligible = False
        if any(line.validation_errors for line in lines):
            reasons.append("SERVICE_LINE_VALIDATION_FAILED")
        return UB04ReconstructionResult(
            lines=lines, unassigned_tokens=unassigned, geometry_valid=True,
            totals_reconciled=total_ok,
            escalation="HITL" if reasons else None,
            reason_codes=reasons,
        )

    @staticmethod
    def _text(tokens: list[UB04Token]) -> str:
        return " ".join(t.text for t in sorted(tokens, key=lambda token: token.bbox[0])).strip()

    def _parse_row(self, row_index: int, cells: dict[str, list[UB04Token]]) -> UB04ServiceLine:
        raw = {name: self._text(tokens) for name, tokens in cells.items()}
        all_tokens = [token for tokens in cells.values() for token in tokens]
        errors: list[str] = []
        revenue = self._normalized(raw.get("revenue_code", ""), "revenue_code", errors)
        if revenue and not re.fullmatch(r"\d{4}", revenue):
            errors.append("INVALID_REVENUE_CODE")
        charge = self._decimal(raw.get("total_charges", ""), "total_charges", errors)
        units = self._decimal(raw.get("service_units", ""), "service_units", errors)
        noncovered = self._decimal(raw.get("non_covered_charges", ""), "non_covered_charges", errors)
        service_date = self._date(raw.get("service_date", ""), errors)
        hcpcs = raw.get("hcpcs_rate_hipps_code") or None
        if hcpcs:
            hcpcs = re.sub(r"\s", "", hcpcs).upper()
            if not _HCPCS.fullmatch(hcpcs):
                errors.append("INVALID_HCPCS_FORMAT")
            elif self._hcpcs_reference is None:
                errors.append("HCPCS_REFERENCE_UNAVAILABLE")
            elif hcpcs not in self._hcpcs_reference:
                errors.append("HCPCS_REFERENCE_MISMATCH")
        if not revenue:
            errors.append("MISSING_REVENUE_CODE")
        if charge is None:
            errors.append("MISSING_CHARGE")
        if units is not None and units < 0:
            errors.append("INVALID_UNITS")
        confidence = sum(t.confidence for t in all_tokens) / len(all_tokens) if all_tokens else 0
        return UB04ServiceLine(
            line_number=row_index + 1, revenue_code=revenue or None,
            description=raw.get("description") or None, hcpcs=hcpcs,
            service_date=service_date, units=units, charge=charge,
            non_covered_charge=noncovered, source_token_count=len(all_tokens),
            mean_confidence=confidence, validation_errors=list(dict.fromkeys(errors)),
            automatically_eligible=not errors and confidence >= 0.90,
        )

    @staticmethod
    def _normalized(raw: str, column: str, errors: list[str]) -> str:
        value, _transform, validation, _acceptable = normalize_cell(raw, column)
        if raw and validation == "INVALID":
            errors.append(f"INVALID_{column.upper()}")
        return value

    @staticmethod
    def _decimal(raw: str, column: str, errors: list[str]) -> Decimal | None:
        if not raw.strip():
            return None
        value = UB04ServiceLineEngine._normalized(raw, column, errors)
        try:
            return Decimal(value)
        except InvalidOperation:
            return None

    @staticmethod
    def _date(raw: str, errors: list[str]) -> date | None:
        if not raw.strip():
            return None
        compact = re.sub(r"\D", "", raw)
        if len(compact) in {6, 8}:
            year_digits = compact[4:]
            year = int(year_digits) + (2000 if len(year_digits) == 2 else 0)
            try:
                return date(year, int(compact[:2]), int(compact[2:4]))
            except ValueError:
                errors.append("INVALID_SERVICE_DATE")
                return None
        value = UB04ServiceLineEngine._normalized(raw, "service_date", errors)
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _reconcile_totals(lines: list[UB04ServiceLine], claim_total: Decimal | None) -> bool | None:
        if claim_total is None:
            return None
        charges = [line.charge for line in lines if line.charge is not None]
        if not charges:
            return False
        return abs(sum(charges, Decimal("0")) - claim_total) <= Decimal("0.01")
