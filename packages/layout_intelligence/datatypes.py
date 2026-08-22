from __future__ import annotations

import re
from datetime import datetime


PATTERNS = {
    "MONEY": re.compile(r"^\$?\s*\d[\d,]*(?:\.\d{2})?$"),
    "NPI": re.compile(r"^\d{10}$"),
    "MEMBER_ID": re.compile(r"^[A-Z0-9][A-Z0-9-]{4,24}$", re.I),
    "TAX_ID": re.compile(r"^\d{2}-?\d{7}$"),
    "CPT_HCPCS": re.compile(r"^(?:\d{5}|[A-Z]\d{4})$", re.I),
    "ICD": re.compile(r"^[A-TV-Z]\d{2}(?:\.?[A-Z0-9]{1,4})?$", re.I),
    "REVENUE_CODE": re.compile(r"^\d{4}$"),
    "TYPE_OF_BILL": re.compile(r"^\d{3,4}$"),
    "INTEGER": re.compile(r"^\d+$"),
}


def valid(value: str, datatype: str) -> bool:
    cleaned = value.strip().strip(":")
    if datatype == "DATE":
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%m/%d/%y"):
            try:
                datetime.strptime(cleaned, fmt)
                return True
            except ValueError:
                pass
        return False
    if datatype == "NAME":
        words = re.findall(r"[A-Za-z][A-Za-z'.-]+", cleaned)
        return 1 < len(words) <= 6 and not any(word.isdigit() for word in words)
    if datatype in {"TEXT", "ADDRESS"}:
        return bool(cleaned)
    pattern = PATTERNS.get(datatype)
    return bool(pattern and pattern.fullmatch(cleaned.replace(" ", "")))
