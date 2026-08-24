"""Conservative patient-name comparison for independent evidence only.

The normalized representation is never written back to the extracted field.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

NAME_NORMALIZATION_VERSION = "patient-name-agreement-v1"
_LABEL_PATTERNS = (
    re.compile(r"\bPATIENT\s+NAME\b", re.IGNORECASE),
    re.compile(r"\bINSURED\s+NAME\b", re.IGNORECASE),
    re.compile(r"\bSUBSCRIBER\s+NAME\b", re.IGNORECASE),
    re.compile(r"\bLAST\s+NAME\b", re.IGNORECASE),
    re.compile(r"\bFIRST\s+NAME\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class NameAgreement:
    left_normalized: str
    right_normalized: str
    left_tokens: tuple[str, ...]
    right_tokens: tuple[str, ...]
    agrees: bool
    label_contamination: bool
    version: str = NAME_NORMALIZATION_VERSION


def has_name_label_contamination(value: str | None) -> bool:
    text = unicodedata.normalize("NFKC", value or "")
    return any(pattern.search(text) for pattern in _LABEL_PATTERNS)


def normalize_name_for_agreement(
    value: str | None,
    *,
    surname_first_proven: bool = False,
) -> tuple[str, tuple[str, ...]]:
    """Normalize representation only; token order stays significant by default."""
    text = unicodedata.normalize("NFKC", value or "").strip().upper()
    if surname_first_proven and text.count(",") == 1:
        surname, given = text.split(",", 1)
        text = f"{given} {surname}"
    text = re.sub(r"[.'’`\-]+", "", text)
    text = re.sub(r"[,;:/\\|()\[\]{}]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = tuple(token for token in text.split(" ") if token)
    # The comparison key is compact so whitespace and safe punctuation are
    # representation-only; the token sequence remains available to detect
    # order disagreement and for forensic reporting.
    return "".join(tokens), tokens


def compare_patient_names(left: str | None, right: str | None) -> NameAgreement:
    left_normalized, left_tokens = normalize_name_for_agreement(left)
    right_normalized, right_tokens = normalize_name_for_agreement(right)
    contaminated = has_name_label_contamination(left) or has_name_label_contamination(right)
    return NameAgreement(
        left_normalized=left_normalized,
        right_normalized=right_normalized,
        left_tokens=left_tokens,
        right_tokens=right_tokens,
        agrees=bool(left_normalized)
        and left_normalized == right_normalized
        and not contaminated,
        label_contamination=contaminated,
    )
