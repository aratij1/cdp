"""Field-aware eligibility for bounded OCR recovery."""
from __future__ import annotations

import re
from dataclasses import dataclass

from packages.domain.extraction import FieldEvidence
from packages.field_normalization import normalize
from packages.validation_rules.npi import is_valid_npi


@dataclass(frozen=True)
class RecoveryAssessment:
    eligible: bool
    reasons: tuple[str, ...]


_LABELS = {
    "patient_name": {"PATIENT", "PATIENTS", "NAME"},
    "insured_name": {"INSURED", "NAME"},
    "provider_name": {"SIGNED", "DATE", "PROVIDER", "SUPPLIER"},
    "patient_dob": {"PATIENT", "BIRTH", "DATE"},
    "insured_id_number": {"INSURED", "ID", "NUMBER"},
    "federal_tax_no": {"FEDERAL", "TAX", "ID", "NUMBER"},
    "total_charge": {"TOTAL", "CHARGE"},
}


def _tokens(evidence: FieldEvidence) -> list[str]:
    return [str(token.get("text", "")).strip().upper() for token in evidence.tokens]


def assess_recovery(field_name: str, field_type: str, evidence: FieldEvidence) -> RecoveryAssessment:
    raw = evidence.raw_text.strip()
    reasons: list[str] = []
    if not raw:
        reasons.append("OCR_EMPTY")
    labels = _LABELS.get(field_name, set())
    raw_words = set(re.findall(r"[A-Z]+", raw.upper()))
    if labels and (any(token in labels for token in _tokens(evidence)) or bool(raw_words & labels)):
        reasons.append("LABEL_CONTAMINATION")
    if field_type == "text" and raw.endswith(","):
        reasons.append("TRUNCATED_TEXT")
    _normalized, parseable = normalize(field_type, raw)
    if raw and not parseable:
        reasons.append("NORMALIZATION_FAILED")
    if field_type == "npi":
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 10 and not is_valid_npi(digits):
            reasons.append("CHECKSUM_INVALID")
    if evidence.bounding_box and len(evidence.tokens) > 1:
        box = evidence.bounding_box
        for token in evidence.tokens:
            token_box = token.get("bounding_box")
            if not isinstance(token_box, dict):
                continue
            if (float(token_box.get("x1", 0)) >= box.x1 - 1
                    or float(token_box.get("y1", 0)) >= box.y1 - 1):
                reasons.append("TOKEN_TOUCHES_CROP_EDGE")
                break
    return RecoveryAssessment(bool(reasons), tuple(dict.fromkeys(reasons)))

