from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import Field

from packages.domain.common import DomainModel
from packages.validation_rules.cpt_hcpcs import is_valid_hcpcs_syntax, is_valid_modifier_syntax
from packages.validation_rules.icd10 import is_valid_icd10_syntax
from packages.validation_rules.npi import is_valid_npi


class DeterministicEvidenceResult(DomainModel):
    field_name: str
    passed: bool
    evidence: set[str] = Field(default_factory=set)
    cross_field_evidence: set[str] = Field(default_factory=set)
    failure_reasons: list[str] = Field(default_factory=list)


class DeterministicEvidenceService:
    """Truth-blind field and claim invariants shared by runtime and evaluation."""

    policy_version = "deterministic-evidence-v1"

    def evaluate(self, field_name: str, value: str | None, *,
                 claim_values: dict[str, str | None] | None = None) -> DeterministicEvidenceResult:
        raw = (value or "").strip()
        if not raw:
            return DeterministicEvidenceResult(
                field_name=field_name, passed=False, failure_reasons=["EMPTY_VALUE"]
            )
        name = field_name.casefold()
        evidence: set[str] = set()
        failures: list[str] = []
        if "npi" in name:
            (evidence.add("CHECKSUM_VALID") if is_valid_npi(_digits(raw)) else failures.append("CHECKSUM_FAILURE"))
        elif any(token in name for token in ("date", "dob", "statement_period")):
            parsed = _parse_date(raw)
            if parsed is None or parsed > date.today():
                failures.append("INVALID_DATE")
            else:
                evidence.update({"FORMAT_VALID", "DATE_VALID"})
        elif any(token in name for token in ("cpt", "hcpcs", "procedure_code")):
            (evidence.update({"FORMAT_VALID", "CODE_SYNTAX_VALID"})
             if is_valid_hcpcs_syntax(raw.replace(" ", "")) else failures.append("INVALID_CODE_SYNTAX"))
        elif "modifier" in name:
            (evidence.update({"FORMAT_VALID", "CODE_SYNTAX_VALID"})
             if is_valid_modifier_syntax(raw) else failures.append("INVALID_MODIFIER_SYNTAX"))
        elif "diagnos" in name or "icd" in name:
            codes = raw.split()
            (evidence.update({"FORMAT_VALID", "CODE_SYNTAX_VALID"})
             if codes and all(is_valid_icd10_syntax(code) for code in codes)
             else failures.append("INVALID_ICD10_SYNTAX"))
        elif any(token in name for token in ("charge", "amount", "paid")):
            try:
                amount = Decimal(re.sub(r"[^0-9.-]", "", raw))
                evidence.add("FORMAT_VALID") if amount >= 0 else failures.append("NEGATIVE_AMOUNT")
            except InvalidOperation:
                failures.append("INVALID_CURRENCY")
        elif "units" in name:
            try:
                evidence.add("FORMAT_VALID") if Decimal(raw) > 0 else failures.append("INVALID_UNITS")
            except InvalidOperation:
                failures.append("INVALID_UNITS")
        elif "zip" in name or "postal" in name:
            (evidence.add("FORMAT_VALID") if re.fullmatch(r"\d{5}(?:-\d{4})?", raw)
             else failures.append("INVALID_ZIP_FORMAT"))
        elif "state" in name:
            (evidence.add("FORMAT_VALID") if re.fullmatch(r"[A-Za-z]{2}", raw)
             else failures.append("INVALID_STATE_FORMAT"))
        elif any(token in name for token in ("checkbox", "indicator", "patient_sex", "rel_code")):
            allowed = {"0", "1", "Y", "N", "M", "F", "X", "01", "02", "03", "04", "05", "06", "07", "08"}
            (evidence.update({"FORMAT_VALID", "CHECKBOX_GEOMETRY_VALID"})
             if raw.upper() in allowed else failures.append("CHECKBOX_AMBIGUOUS"))
        elif _label_contaminated(name, raw):
            failures.append("LABEL_CONTAMINATION")
        else:
            evidence.add("FORMAT_VALID")

        cross = self._cross_field(name, raw, claim_values or {}) if not failures else set()
        return DeterministicEvidenceResult(
            field_name=field_name, passed=not failures and bool(evidence), evidence=evidence,
            cross_field_evidence=cross, failure_reasons=failures,
        )

    def _cross_field(self, name: str, raw: str, values: dict[str, str | None]) -> set[str]:
        evidence: set[str] = set()
        if name in {"patient_dob", "dob"}:
            dob = _parse_date(raw)
            service = _parse_date(values.get("service_date") or values.get("date_from") or "")
            if dob and service and dob < service:
                evidence.add("DATE_RELATIONSHIP_CONFIRMED")
        if name in {"date_from", "statement_period_from"}:
            start, end = _parse_date(raw), _parse_date(values.get("date_to") or values.get("statement_period_to") or "")
            if start and end and start <= end:
                evidence.add("DATE_RELATIONSHIP_CONFIRMED")
        if name in {"total_charge", "total_charges"}:
            line_values = values.get("service_line_charges")
            if line_values:
                try:
                    expected = sum((Decimal(item) for item in str(line_values).split(",")), Decimal(0))
                    actual = Decimal(re.sub(r"[^0-9.-]", "", raw))
                    if expected == actual:
                        evidence.add("CLAIM_TOTAL_CONFIRMED")
                except InvalidOperation:
                    pass
        return evidence


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _parse_date(value: str) -> date | None:
    digits = _digits(value)
    candidates = [value]
    if len(digits) == 8:
        candidates.extend([f"{digits[:4]}-{digits[4:6]}-{digits[6:]}", f"{digits[4:]}-{digits[:2]}-{digits[2:4]}"])
    elif len(digits) == 6:
        candidates.append(f"20{digits[4:]}-{digits[:2]}-{digits[2:4]}")
    for candidate in candidates:
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _label_contaminated(field_name: str, value: str) -> bool:
    tokens = set(field_name.replace("_", " ").split())
    words = set(value.casefold().replace(":", "").split())
    return len(tokens & words) >= max(1, len(tokens) - 1)
