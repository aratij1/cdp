"""Pure field normalization shared by runtime workers and domain policies."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

_DATE_FORMATS = ["%m-%d-%Y", "%m/%d/%Y", "%m-%d-%y", "%m/%d/%y", "%Y%m%d", "%m%d%Y", "%m%d%y"]


def normalize_text(raw: str) -> tuple[str, bool]:
    cleaned = re.sub(r"\s+", " ", raw.strip())
    return cleaned, bool(cleaned)


DEFAULT_PIVOT_YEAR: int = 2026


def normalize_date(raw: str, current_year: int = DEFAULT_PIVOT_YEAR) -> tuple[str | None, bool]:
    """Normalize date strings into ISO format (YYYY-MM-DD).

    Deterministic Century Pivot:
    When a two-digit year (%y) is encountered:
      - If 2-digit year yy <= (current_year % 100) -> 2000 + yy (e.g. 26 -> 2026, 04 -> 2004)
      - If 2-digit year yy > (current_year % 100) -> 1900 + yy (e.g. 27 -> 1927, 45 -> 1945, 99 -> 1999)
    Default `current_year` is anchored to versioned `DEFAULT_PIVOT_YEAR` (2026) to guarantee
    absolute runtime determinism and multi-year reproducibility.
    4-digit years (%Y) are preserved without modification.
    """
    cleaned = re.sub(r"\s+", "/", raw.strip())
    cutoff_yy = (current_year if current_year is not None else DEFAULT_PIVOT_YEAR) % 100
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
        if "%y" in fmt:
            two_digit_yr = parsed.year % 100
            target_year = (2000 + two_digit_yr) if two_digit_yr <= cutoff_yy else (1900 + two_digit_yr)
            try:
                parsed = parsed.replace(year=target_year)
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
