"""Formatting-only normalization. Syntax is engineering evidence, not truth."""

import re
from datetime import UTC, datetime
from decimal import Decimal

from packages.claim_evidence.charge_reconciliation import normalize_money
from packages.validation_rules.icd10 import is_valid_icd10_syntax
from packages.validation_rules.npi import is_valid_npi


def money(value: str) -> Decimal | None:
    if not isinstance(value, str) or not re.fullmatch(
        r"\$?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?", value.strip()
    ):
        return None
    return normalize_money(value)[0]


def calendar_date(value: str | None):
    if not value:
        return None
    # US claim date cells may be separate numeric tokens. Require the full year;
    # never infer a century or replace an OCR character.
    components = re.fullmatch(r"([0-9]{2})\s+([0-9]{2})\s+([0-9]{4})", value.strip())
    if components:
        value = "/".join(components.groups())
    # No inferred century. The US-format option is explicit for these US claim forms.
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y"):
        try:
            parsed = datetime.strptime(value.strip(), pattern).replace(tzinfo=UTC).date()
            if parsed.strftime(pattern) == value.strip():
                return parsed
        except ValueError:
            pass
    return None


def normalize(field: str, value: str) -> tuple[str, bool | None]:
    value = " ".join(value.strip().split())
    if field == "total_charge":
        amount = money(value)
        return (str(amount), True) if amount is not None else (value, False)
    if field in {"patient_dob", "service_date", "patient_DOB"}:
        parsed = calendar_date(value)
        return (parsed.isoformat(), True) if parsed else (value, False)
    if field in {"principal_diagnosis", "diagnosis"}:
        compact = re.sub(r"\s+", "", value.upper())
        # Tighten syntax to require a numeric second character, without OCR substitutions.
        valid = bool(re.fullmatch(r"[A-Z][0-9][A-Z0-9](?:\.?[A-Z0-9]{1,4})?", compact))
        valid = valid and is_valid_icd10_syntax(compact)
        if valid:
            raw = compact.replace(".", "")
            return (raw[:3] + "." + raw[3:] if len(raw) > 3 else raw), True
        return value, False
    if field == "provider_npi":
        return value, is_valid_npi(value)
    if field in {"member_id", "subscriber_id"}:
        # Preserve punctuation and character case; no payer format is assumed.
        return value, bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{1,39}", value))
    if field in {"patient_name", "provider_name", "insured_name"}:
        valid = (
            bool(value) and any(c.isalpha() for c in value) and not any(c.isdigit() for c in value)
        )
        return value, valid
    return value, None
