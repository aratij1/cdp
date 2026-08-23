from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from packages.field_normalization import normalize
from packages.validation_rules import is_valid_npi


@dataclass(frozen=True)
class LocalEvidenceDecision:
    accepted: bool
    normalized_value: str | None
    secondary_engine: str | None
    reason_codes: tuple[str, ...]


@lru_cache(maxsize=4)
def load_secondary_policy(path: str | Path = "config/secondary_ocr_policy_v1.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text("utf-8"))


def _field_type(datatype: str) -> str:
    return {
        "DATE": "date",
        "CURRENCY": "currency",
        "NPI": "npi",
        "CHECKBOX": "checkbox",
        "ALPHANUMERIC_ID": "code",
        "CPT_HCPCS": "code",
        "ICD_CODE": "code",
        "TYPE_OF_BILL": "code",
        "TAX_IDENTIFIER": "tax_id",
    }.get(datatype, "text")


def _valid(datatype: str, value: str | None) -> bool:
    if value is None:
        return False
    if datatype == "NPI":
        return is_valid_npi(value)
    if datatype == "CPT_HCPCS":
        return bool(re.fullmatch(r"(?:\d{5}|[A-Z]\d{4})", value))
    if datatype == "ICD_CODE":
        return bool(re.fullmatch(r"[A-TV-Z][0-9][0-9AB](?:\.[A-Z0-9]{1,4})?", value))
    if datatype == "TYPE_OF_BILL":
        return bool(re.fullmatch(r"\d{3,4}", value))
    if datatype == "TAX_IDENTIFIER":
        return bool(re.fullmatch(r"\d{9}", value))
    if datatype == "PERSON_NAME":
        return bool(re.fullmatch(r"[A-Z]{2,}(?:\s+[A-Z]{2,})+", value.upper().strip()))
    if datatype == "PERSON_OR_ORGANIZATION":
        parts = value.upper().strip().split()
        if not re.fullmatch(r"[A-Z]{2,}(?:\s+[A-Z]{2,})+", value.upper().strip()):
            return False
        if parts[-1] == "MD" and len(parts) < 3:
            return False
        if any(len(part) > 2 and part.endswith("MD") for part in parts):
            return False
        organization_suffixes = {"HOSPITAL", "CENTER", "SYSTEM", "CLINIC", "HEALTH"}
        if any(
            part != suffix and part.endswith(suffix)
            for part in parts
            for suffix in organization_suffixes
        ):
            return False
        return True
    return bool(value.strip())


def decide_local_candidate(raw_value: str, datatype: str, *, policy: dict | None = None):
    policy = policy or load_secondary_policy()
    if not raw_value.strip():
        route = policy["routes"].get(datatype, {"secondary": "NONE"})
        secondary = route["secondary"] if route["secondary"] != "NONE" else None
        return LocalEvidenceDecision(
            False, None, secondary, ("EMPTY_PRIMARY_CANDIDATE", "SECONDARY_OCR_SELECTIVE")
        )
    normalized, parsed = normalize(_field_type(datatype), raw_value)
    if parsed and _valid(datatype, normalized):
        return LocalEvidenceDecision(
            True, normalized, None, ("RAPID_CANDIDATE_DETERMINISTICALLY_VALID",)
        )
    route = policy["routes"].get(datatype, {"secondary": "NONE"})
    secondary = route["secondary"] if route["secondary"] != "NONE" else None
    return LocalEvidenceDecision(
        False, normalized, secondary, ("PRIMARY_VALIDATION_FAILED", "SECONDARY_OCR_SELECTIVE")
    )
