"""Field-semantic span selection for bounded over-crops.

Rules only select or segment observed characters. They never substitute a
different identifier, date, amount, or code and therefore cannot silently
correct a value into validity.
"""

from __future__ import annotations

import re

from .contracts import SpanSelectionResult

_LABELS = (
    "PATIENT NAME", "INSURED NAME", "FACILITY/PROVIDER", "FACILITY PROVIDER",
    "PROVIDER NAME", "MEMBER ID", "MEMBERID", "TYPE OF BILL", "TYPEOFBILL",
    "PRINCIPAL DIAGNOSIS", "PRINCIPALDIAGNOSIS", "FEDERAL TAX NO",
    "TOTAL CHARGE", "SERVICE DATE", "RELATIONSHIP",
)


def _matches(pattern: str, text: str) -> list[str]:
    return [match.group(0).strip() for match in re.finditer(pattern, text, re.IGNORECASE)]


def _result(raw: str, selected: str, rule: str, candidates: list[str], confidence: float,
            *reasons: str) -> SpanSelectionResult:
    return SpanSelectionResult(
        raw_text=raw, selected_text=selected.strip(), rule_id=rule,
        confidence=confidence, candidate_spans=tuple(candidates),
        source_lines=tuple(line.strip() for line in raw.splitlines() if line.strip()),
        reason_codes=tuple(reasons),
    )


def select_field_span(raw_text: str, datatype: str, field_name: str = "") -> SpanSelectionResult:
    raw = " ".join((raw_text or "").replace("\u00a0", " ").split())
    if not raw:
        return _result(raw, "", "span-v1-empty", [], 0, "OCR_EMPTY")
    upper = raw.upper()
    datatype = datatype.upper()
    search_space = upper
    removed_labels = []
    for label in _LABELS:
        if label in search_space:
            search_space = search_space.replace(label, " ")
            removed_labels.append(label)

    patterns: list[tuple[str, str, str]] = []
    if datatype == "DATE":
        duplicated_edge = re.search(r"(?<!\d)\d(\d{2}[-/]\d{2}[-/]\d{4})(?!\d)", search_space)
        if duplicated_edge:
            selected = duplicated_edge.group(1)
            return _result(raw, selected, "span-v1-date-edge-glyph", [selected], .86,
                           "BOUNDED_EDGE_GLYPH_REMOVED")
        patterns = [("date", r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})", "last")]
    elif datatype == "NPI":
        patterns = [("npi", r"(?<!\d)\d{10}(?!\d)", "first")]
    elif datatype == "CURRENCY":
        patterns = [("currency", r"\$?\d[\d,]*\.\d{2}", "last")]
    elif datatype == "TYPE_OF_BILL":
        patterns = [("type-of-bill", r"(?<!\d)0?\d{3}(?!\d)", "first")]
    elif datatype == "ICD_CODE":
        patterns = [("icd", r"[A-TV-Z][0-9][0-9A-Z](?:\.?[0-9A-Z]{1,4})?", "last")]
    elif datatype == "CPT_HCPCS":
        patterns = [("cpt-hcpcs", r"\b(?:\d{5}|[A-Z]\d{4})\b", "last")]
    elif datatype == "TAX_IDENTIFIER":
        patterns = [("tax-id", r"(?<!\d)\d{2}-?\d{7}(?!\d)", "last")]
    elif datatype == "ALPHANUMERIC_ID":
        patterns = [
            ("member-id", r"[A-Z]\d{2}-\d{7}", "last"),
            ("generic-id", r"\b[A-Z0-9]{2,8}-[A-Z0-9-]{3,20}\b", "last"),
        ]
    elif datatype == "CHECKBOX" or field_name == "relationship":
        patterns = [("relationship", r"(?:SELF|SPOUSE|CHILD|OTHER)", "first")]

    for rule, pattern, preference in patterns:
        candidates = _matches(pattern, search_space)
        if candidates:
            selected = candidates[-1] if preference == "last" else candidates[0]
            return _result(raw, selected, f"span-v1-{rule}", candidates,
                           .96 if len(candidates) == 1 else .82,
                           "FIELD_SEMANTIC_SPAN",
                           "LABELS_REMOVED" if removed_labels else "NO_LABELS_REMOVED",
                           "MULTIPLE_SPANS" if len(candidates) > 1 else "SINGLE_SPAN")

    if datatype in {"PERSON_NAME", "PERSON_OR_ORGANIZATION"}:
        cleaned = upper
        removed = []
        for label in _LABELS:
            if label in cleaned:
                cleaned = cleaned.replace(label, " ")
                removed.append(label)
        cleaned = re.sub(r"[^A-Z0-9'. -]+", " ", cleaned)
        cleaned = " ".join(cleaned.split())
        if datatype == "PERSON_OR_ORGANIZATION" or field_name == "provider_name":
            match = re.search(r"([A-Z]{3,})\s*MEDICAL\s*GROUP\s*(\d{4})", cleaned)
            if match:
                selected = f"{match.group(1)} MEDICAL GROUP {match.group(2)}"
                return _result(raw, selected, "span-v1-provider-assembly", [selected], .92,
                               "GOVERNED_ORGANIZATION_ASSEMBLY", "LABELS_REMOVED" if removed else "NO_LABEL")
        if cleaned and cleaned != upper:
            return _result(raw, cleaned, "span-v1-name-label-strip", [cleaned], .80,
                           "KNOWN_LABEL_REMOVED")

    return _result(raw, raw, "span-v1-preserve", [raw], .55, "NO_UNIQUE_SEMANTIC_SPAN")
