"""Pure field normalization shared by runtime workers and domain policies."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

_DATE_FORMATS = ["%m-%d-%Y", "%m/%d/%Y", "%m-%d-%y", "%m/%d/%y", "%Y%m%d", "%m%d%Y", "%m%d%y"]


def normalize_text(raw: str) -> tuple[str, bool]:
    cleaned = re.sub(r"\s+", " ", raw.strip())
    return cleaned, bool(cleaned)


def normalize_date(raw: str) -> tuple[str | None, bool]:
    cleaned = re.sub(r"\s+", "/", raw.strip())
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
        return parsed.isoformat(), True
    return None, False


def normalize_currency(raw: str) -> tuple[Decimal | None, bool]:
    source = raw.strip().strip("|").strip()
    parenthesized = source.startswith("(") and source.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", source)
    if not cleaned:
        return None, False
    if parenthesized and not cleaned.startswith("-"):
        cleaned = f"-{cleaned}"
    try:
        return Decimal(cleaned).quantize(Decimal("0.01")), True
    except InvalidOperation:
        return None, False


def normalize_npi(raw: str) -> tuple[str | None, bool]:
    digits = re.sub(r"\D", "", raw)
    return (digits, True) if len(digits) == 10 else (None, False)


def normalize_tax_id(raw: str) -> tuple[str | None, bool]:
    digits = re.sub(r"\D", "", raw)
    return (digits, True) if len(digits) == 9 else (None, False)


def normalize_code(raw: str) -> tuple[str, bool]:
    cleaned = re.sub(r"\s+", "", raw.strip().upper())
    return cleaned, bool(cleaned)


def normalize_checkbox(raw: str) -> tuple[bool | None, bool]:
    cleaned = raw.strip().upper()
    if cleaned in ("X", "[X]", "YES"):
        return True, True
    if cleaned in ("", "[ ]", "NO"):
        return False, True
    return None, False


_PROCESSORS = {
    "text": normalize_text,
    "date": normalize_date,
    "currency": normalize_currency,
    "npi": normalize_npi,
    "tax_id": normalize_tax_id,
    "code": normalize_code,
    "checkbox": normalize_checkbox,
}


def normalize(field_type: str, raw: str) -> tuple[str | None, bool]:
    value, ok = _PROCESSORS.get(field_type, normalize_text)(raw)
    return (str(value) if value is not None else None), ok
