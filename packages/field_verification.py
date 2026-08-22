"""Deterministic field evidence without conflating syntax with truth."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from packages.validation_rules.icd10 import is_valid_icd10_syntax
from packages.validation_rules.npi import is_valid_npi


@dataclass(frozen=True)
class VerificationEvidence:
    valid: bool
    strength: str
    reason_code: str
    auto_verifiable: bool = False


def normalize_field_value(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9.]", "", (value or "").upper())


def repair_npi_missing_leading_digit(value: str | None) -> str | None:
    """Repair only the bounded, checksum-unique 9-digit left-edge loss case."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 9:
        return None
    candidates = [prefix + digits for prefix in "123456789" if is_valid_npi(prefix + digits)]
    return candidates[0] if len(candidates) == 1 else None


def verify_field(field_name: str, value: str | None, independent_agreement: int = 1) -> VerificationEvidence:
    cleaned = normalize_field_value(value)
    name = field_name.lower()
    if not cleaned:
        return VerificationEvidence(False, "NONE", "MISSING_VALUE")
    if "npi" in name:
        valid = is_valid_npi(re.sub(r"\D", "", cleaned))
        agreed = independent_agreement >= 2
        return VerificationEvidence(
            valid, "CHECKSUM" if valid else "NONE",
            "NPI_CHECKSUM_VALID" if valid else "NPI_CHECKSUM_INVALID",
            auto_verifiable=valid and agreed,
        )
    if "diagnosis" in name or name.startswith("icd"):
        valid = is_valid_icd10_syntax(cleaned)
        return VerificationEvidence(valid, "SYNTAX", "ICD10_SYNTAX_VALID" if valid else "ICD10_SYNTAX_INVALID")
    if "type_of_bill" in name:
        valid = bool(re.fullmatch(r"\d{3,4}", cleaned))
        return VerificationEvidence(valid, "SYNTAX", "TYPE_OF_BILL_SYNTAX_VALID" if valid else "TYPE_OF_BILL_SYNTAX_INVALID")
    if "dob" in name or "date" in name:
        raw = (value or "").strip()
        parsed = None
        for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y%m%d", "%m%d%Y"):
            try:
                parsed = datetime.strptime(raw, pattern).date()
                break
            except ValueError:
                continue
        valid = parsed is not None and parsed <= date.today()
        return VerificationEvidence(valid, "SEMANTIC", "DATE_VALID" if valid else "DATE_INVALID")
    if "charge" in name or "amount" in name:
        try:
            valid = Decimal(cleaned.replace("$", "")) >= 0
        except (InvalidOperation, ValueError):
            valid = False
        return VerificationEvidence(valid, "SEMANTIC", "CURRENCY_VALID" if valid else "CURRENCY_INVALID")
    return VerificationEvidence(True, "PRESENCE", "VALUE_PRESENT")
