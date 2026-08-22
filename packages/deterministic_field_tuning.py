"""Conservative structured-field gate for current-sample and runtime tuning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from packages.field_normalization import normalize_currency, normalize_date
from packages.validation_rules.npi import is_valid_npi

INDEPENDENT_BLANK_MARKERS = {"CROSS_ENGINE_BLANK_AGREEMENT", "REFERENCE_VERIFIED_BLANK"}


@dataclass(frozen=True)
class DeterministicResult:
    normalized_value: str | None
    valid: bool
    evidence: str


def validate_field(field: str, raw: object) -> DeterministicResult:
    value = "" if raw is None else str(raw).strip()
    name = field.lower()
    if name in {"date_from", "date_to", "service_date"}:
        normalized, valid = normalize_date(value)
        return DeterministicResult(normalized, valid, "VALID_DATE")
    if name in {"charges", "charge", "adjustment", "insurance_paid", "patient_paid"}:
        normalized, valid = normalize_currency(value)
        return DeterministicResult(str(normalized) if normalized is not None else None, valid, "VALID_AMOUNT")
    if name in {"rendering_provider_npi", "provider_npi"}:
        digits = re.sub(r"\D", "", value)
        valid = is_valid_npi(digits)
        return DeterministicResult(digits if valid else None, valid, "VALID_NPI_CHECKSUM")
    if name == "service_units":
        try:
            amount = Decimal(value)
            valid = amount > 0 and amount == amount.to_integral_value()
        except InvalidOperation:
            valid = False
        return DeterministicResult(value if valid else None, valid, "VALID_POSITIVE_UNITS")
    if name == "revenue_code":
        normalized = re.sub(r"\s", "", value).upper()
        valid = bool(re.fullmatch(r"\d{4}", normalized))
        return DeterministicResult(normalized if valid else None, valid, "VALID_REVENUE_CODE_FORMAT")
    if name in {"procedure_code", "cpt_code", "hcpcs_rate_hipps_code"}:
        normalized = re.sub(r"\s", "", value).upper()
        valid = bool(re.fullmatch(r"[A-Z0-9]{4,5}", normalized))
        return DeterministicResult(normalized if valid else None, valid, "VALID_PROCEDURE_CODE_FORMAT")
    if name in {"principal_diagnosis", "diagnosis_code"}:
        normalized = re.sub(r"\s", "", value).upper().rstrip(".")
        valid = bool(re.fullmatch(r"[A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?", normalized))
        return DeterministicResult(normalized if valid else None, valid, "VALID_DIAGNOSIS_FORMAT")
    if name == "place_of_service":
        valid = bool(re.fullmatch(r"\d{2}", value))
        return DeterministicResult(value if valid else None, valid, "VALID_PLACE_OF_SERVICE_FORMAT")
    if name == "type_of_bill":
        valid = bool(re.fullmatch(r"[1-8][1-8][0-9]", value))
        return DeterministicResult(value if valid else None, valid, "VALID_TYPE_OF_BILL_FORMAT")
    if name == "patient_sex":
        normalized = value.upper()
        valid = normalized in {"M", "F", "U"}
        return DeterministicResult(normalized if valid else None, valid, "VALID_SEX_CODE")
    if name == "rel_code":
        normalized = value.upper()
        valid = normalized in {"SELF", "SPOUSE", "CHILD", "OTHER", "01", "02", "09", "19", "G8"}
        return DeterministicResult(normalized if valid else None, valid, "VALID_RELATIONSHIP_CODE")
    if name == "emergency_indicator":
        normalized = value.upper()
        valid = normalized in {"Y", "N"}
        return DeterministicResult(normalized if valid else None, valid, "VALID_EMERGENCY_INDICATOR")
    if name == "diagnosis_pointer":
        normalized = " ".join(value.upper().split())
        tokens = normalized.split()
        valid = bool(tokens) and len(tokens) <= 4 and all(
            re.fullmatch(r"[A-L]|(?:[1-9]|1[0-2])", token) for token in tokens
        )
        return DeterministicResult(normalized if valid else None, valid, "VALID_DIAGNOSIS_POINTERS")
    if name in {"modifier", "modifiers"}:
        normalized = " ".join(value.upper().split())
        tokens = normalized.split()
        valid = bool(tokens) and len(tokens) <= 4 and all(
            re.fullmatch(r"[A-Z0-9]{2}", token) for token in tokens
        )
        return DeterministicResult(normalized if valid else None, valid, "VALID_MODIFIER_FORMAT")
    return DeterministicResult(None, False, "NO_DETERMINISTIC_RULE")


def eligible_for_consensus_acceptance(row: dict) -> DeterministicResult:
    validations = set(row.get("validation_results") or [])
    field = (row.get("field_identity") or {}).get("semantic_field", "")
    value = row.get("selected_value")
    if value is None or not str(value).strip():
        if validations.intersection(INDEPENDENT_BLANK_MARKERS):
            return DeterministicResult("", True, "INDEPENDENT_BLANK_CONSENSUS")
        return DeterministicResult(None, False, "INDEPENDENT_BLANK_CONSENSUS_REQUIRED")
    result = validate_field(field, value)
    if "CROSS_FAMILY_AGREEMENT" not in validations:
        return DeterministicResult(result.normalized_value, False, "INDEPENDENT_CONSENSUS_REQUIRED")
    return result
