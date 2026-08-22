from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


def normalize_agreement_value(field_name: str, value: str | None) -> str:
    """Canonicalize only representation-level differences for E2 agreement.

    This is deliberately field-aware: stripping a decimal point from money,
    for example, could turn 10.00 and 1000 into a false agreement.
    """
    raw = (value or "").strip().upper()
    if not raw:
        return ""
    name = field_name.casefold()
    if any(token in name for token in ("charge", "amount", "paid", "rate")):
        try:
            number = Decimal(re.sub(r"[^0-9.()-]", "", raw).replace("(", "-").replace(")", ""))
            return format(number.normalize(), "f")
        except (InvalidOperation, ValueError):
            return raw
    if any(token in name for token in ("date", "dob")):
        return re.sub(r"\D", "", raw)
    if any(token in name for token in (
        "name", "address", "member", "insured_id", "subscriber_id", "npi",
        "diagnos", "icd", "code", "tax", "bill", "zip", "postal",
    )):
        return re.sub(r"[^A-Z0-9]", "", raw)
    return " ".join(raw.split())
