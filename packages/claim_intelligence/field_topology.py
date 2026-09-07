"""Governed shadow field topology. No automatic acceptance or reference inputs.

Legacy evaluation rules remain immutable historical experiments. New structural
work uses this common contract; registrations are reviewed engineering evidence,
not qualified production form identity.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class TextLine(Protocol):
    """Structural token interface keeps shared topology independent of workers."""

    @property
    def text(self) -> str: ...
    @property
    def x0(self) -> float: ...
    @property
    def y0(self) -> float: ...
    @property
    def x1(self) -> float: ...
    @property
    def y1(self) -> float: ...
    @property
    def confidence(self) -> float: ...


DOCUMENTS = {
    "CMS1500",
    "UB04",
    "LABORATORY_BILL",
    "PSYCHOLOGY_RECEIPT",
    "PSYCHOLOGY_STATEMENT",
    "MEDICAL_SERVICES_CLAIM",
    "INSURANCE_CARD",
}


@dataclass(frozen=True)
class FormFieldTopology:
    form_type: str
    field_name: str
    normalized_region: tuple[float, float, float, float]
    label_relationship: str
    token_alignment: str
    assembly_policy: str
    validation_policy: str
    provenance: str
    version: str = "shadow-topology-v1"
    document_type: str = ""
    required_label_pattern: str = ""


def generate(
    tokens: Sequence[TextLine],
    *,
    topology: FormFieldTopology,
    form_type: str,
    document_type: str,
    source_sha256: str,
    reviewed_source_sha256: str,
    width: int,
    height: int,
) -> list[dict]:
    t = topology
    if (
        t.version != "shadow-topology-v1"
        or t.provenance != "SOURCE_REVIEWED_ENGINEERING_ONLY"
        or form_type not in {"CMS1500", "UB04", "OTHER"}
        or form_type != t.form_type
        or document_type not in DOCUMENTS
        or document_type != t.document_type
        or not re.fullmatch(r"[a-f0-9]{64}", source_sha256)
        or source_sha256 != reviewed_source_sha256
        or width <= 0
        or height <= 0
    ):
        return []
    if form_type == "OTHER" and document_type in {"CMS1500", "UB04"}:
        return []
    if form_type != "OTHER" and document_type != form_type:
        return []
    l, top, right, bottom = t.normalized_region
    if not (0 <= l < right <= 1 and 0 <= top < bottom <= 1):
        return []
    if not t.required_label_pattern or not any(
        re.search(t.required_label_pattern, x.text, re.IGNORECASE) for x in tokens
    ):
        return []
    selected = [
        (i, x)
        for i, x in enumerate(tokens)
        if l <= (x.x0 + x.x1) / (2 * width) <= right
        and top <= (x.y0 + x.y1) / (2 * height) <= bottom
    ]
    if not selected:
        return []
    if t.label_relationship == "LAB_SUMMARY_TAX_ID_ROW":
        tax = [
            x
            for x in tokens
            if re.search(r"Tax\s*(?:ID|1D)", x.text, re.IGNORECASE) and x.y0 / height > top
        ]
        if len(tax) != 1:
            return []
        selected = [(i, x) for i, x in selected if max(x.y0, tax[0].y0) < min(x.y1, tax[0].y1)]
    elif t.label_relationship not in {"OWN_LABELED_CELL", "SOURCE_REVIEWED_SUMMARY_ROW"}:
        return []
    selected.sort(key=lambda pair: pair[1].x0)
    outputs = []

    def emit(value, parts):
        outputs.append(
            {
                "field_name": t.field_name,
                "value": value,
                "review_only": True,
                "authority": "ENGINEERING_ONLY",
                "topology_version": t.version,
                "source_sha256": source_sha256,
                "document_type": document_type,
                "assembly_policy": t.assembly_policy,
                "normalized_region": list(t.normalized_region),
                "token_indices": [i for i, x in parts],
                "raw_tokens": [
                    {"text": x.text, "bbox": [x.x0, x.y0, x.x1, x.y1], "confidence": x.confidence}
                    for i, x in parts
                ],
            }
        )

    if t.field_name == "total_charge":
        roles = {
            "LABORATORY_BILL": "LAB_SUMMARY_TAX_ID_ROW",
            "PSYCHOLOGY_RECEIPT": "OWN_LABELED_CELL",
            "PSYCHOLOGY_STATEMENT": "SOURCE_REVIEWED_SUMMARY_ROW",
        }
        if roles.get(document_type) != t.label_relationship:
            return []
        if (
            t.assembly_policy != "EXPLICIT_CLAIM_TOTAL"
            or t.validation_policy != "CLAIM_TOTAL_ROLE_ONLY"
        ):
            return []
        if t.label_relationship not in {
            "LAB_SUMMARY_TAX_ID_ROW",
            "SOURCE_REVIEWED_SUMMARY_ROW",
            "OWN_LABELED_CELL",
        }:
            return []
        for part in selected:
            m = re.fullmatch(r"\s*[$Ss]?\s*([0-9]+(?:,[0-9]{3})*\.[0-9]{2})\s*", part[1].text)
            if m:
                emit(format(Decimal(m[1].replace(",", "")), ".2f"), [part])
    elif t.field_name == "member_id":
        for part in selected:
            raw = part[1].text.strip()
            if t.assembly_policy == "LABELED_IDENTIFIER":
                m = re.search(
                    r"Member\s*(?:ID|1D):\s*([A-Z0-9]+(?:[-/][A-Z0-9]+)*)", raw, re.IGNORECASE
                )
                if not m:
                    continue
                raw = m[1]
            elif t.assembly_policy not in {
                "IDENTIFIER_LITERAL",
                "IDENTIFIER_PRESENTATION_ALTERNATIVE",
            }:
                return []
            if not re.fullmatch(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*", raw) or not any(
                c.isdigit() for c in raw
            ):
                continue
            emit(raw, [part])
            if t.validation_policy == "PRESERVE_ALL_ALPHANUMERIC_COMPONENTS" and "-" in raw:
                # An additional presentation candidate; never replace the literal,
                # discard a suffix, change a letter, or confer identity authority.
                emit(raw.replace("-", ""), [part])
    elif t.field_name in {"patient_name", "insured_name"}:
        if t.validation_policy != "OBSERVED_NAME_COMPONENTS_ONLY":
            return []
        parts = [p for p in selected if re.fullmatch(r"[A-Za-z ,.'-]+", p[1].text.strip())]
        if not parts or len(parts) != len(selected):
            return []
        if max(p[1].y0 for p in parts) >= min(p[1].y1 for p in parts):
            return []
        words = [w for p in parts for w in re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)*", p[1].text)]
        if len(words) < 2 or any(
            w.upper() in {"SAME", "SELF", "NAME", "ADDRESS", "CLIENT"} for w in words
        ):
            return []
        if t.assembly_policy in {"NAME_LAST_FIRST", "NAME_COMPONENT_COLUMNS"}:
            value = " ".join(words[1:] + words[:1])
        elif t.assembly_policy == "NAME_FIRST_LAST":
            value = " ".join(words)
        else:
            return []
        emit(value, parts)
    return list({r["value"]: r for r in outputs}.values())


def observed_date_values(tokens: Sequence[TextLine]) -> list[str]:
    """Read complete schema-valid dates; unrelated labels are not date fragments."""
    from datetime import date

    result = []
    for token in tokens:
        raw = token.text.strip()
        if not re.fullmatch(r"[0-9]{8}", raw):
            continue
        try:
            value = date(int(raw[4:]), int(raw[:2]), int(raw[2:4])).isoformat()
        except ValueError:
            continue
        result.append(value)
    return list(dict.fromkeys(result))


def source_line_values(text: str, field: str, name_order: str = "LAST_FIRST") -> list[str]:
    """Conservative schema assembly for an already source-bound single row."""
    raw = text.strip()
    if field in {"patient_name", "insured_name"}:
        raw = raw.rstrip(" *.,")
        if not re.fullmatch(r"[A-Za-z ,.'-]+", raw):
            return []
        words = re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)*", raw)
        if len(words) < 2:
            return []
        return [" ".join(words if name_order == "FIRST_LAST" else words[1:] + words[:1])]
    if field == "principal_diagnosis" and re.fullmatch(
        r"[A-TV-Z][0-9]{2}(?:\.[A-Z0-9]{1,4})?", raw
    ):
        return [raw]
    return []


def rank_review_candidates(values: Sequence[str], evidence: Sequence[dict]) -> list[str]:
    """Source-only ordering inside the existing top-five coverage envelope.

    This is a review presentation rank, never an acceptance probability. Missing
    provenance receives no boost; candidates outside the envelope are preserved.
    """

    def score(value: str) -> tuple[int, float, int]:
        proofs = [
            p
            for p in evidence
            if p.get("value") == value
            and p.get("authority") == "ENGINEERING_ONLY"
            and p.get("review_only") is True
            and re.fullmatch(r"[a-f0-9]{64}", str(p.get("source_sha256", "")))
            and (
                p.get("normalized_region")
                or p.get("region_bbox")
                or p.get("region")
                or p.get("normalized_bbox")
                or p.get("bbox")
            )
        ]
        if not proofs:
            return (0, 0.0, 0)
        confidence = max(float(p.get("confidence", 0)) for p in proofs)
        return (1, confidence, len(value.split()))

    return sorted(values[:5], key=score, reverse=True) + list(values[5:])
