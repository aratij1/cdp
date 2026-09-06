"""Anchor-relative candidate generation using the existing field registry."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from packages.field_localization.registry import FieldDefinitionRegistry

from .document import DocumentPage, Token, fingerprint
from .models import Candidate, CandidateEvidence, EvidenceFeatures
from .normalization import normalize

TARGET_FIELDS = frozenset(
    {
        "member_id",
        "provider_name",
        "patient_name",
        "insured_name",
        "total_charge",
        "service_date",
        "patient_dob",
        "principal_diagnosis",
    }
)
IDENTITY_FIELDS = frozenset(
    {"member_id", "provider_name", "patient_name", "insured_name", "subscriber_id"}
)
ROOT = Path(__file__).resolve().parents[2]


def label_key(text: str) -> str:
    """Normalize printed labels only; never modify candidate characters."""
    value = " ".join(text.upper().replace("\u2019", "'").split()).rstrip(":")
    value = re.sub(r"^\d{1,2}[A-Z]?[.\s]+", "", value)
    value = re.sub(
        r"\s*\(LAST(?:\s*NAME)?,?\s*FIRST(?:\s*NAME)?,?\s*MIDDLE(?:\s*NAME|\s*INITIAL)?\)\s*$",
        "",
        value,
    )
    return re.sub(r"[\s']", "", value.strip())


def line_groups(tokens: tuple[Token, ...]) -> list[list[Token]]:
    rows: list[list[Token]] = []
    for token in sorted(tokens, key=lambda t: (t.bbox[1], t.bbox[0], t.provenance_id)):
        matching = next(
            (
                row
                for row in rows
                if abs(row[0].bbox[1] - token.bbox[1])
                <= min(row[0].bbox[3] - row[0].bbox[1], token.bbox[3] - token.bbox[1]) * 0.35
            ),
            None,
        )
        if matching is None:
            rows.append([token])
        else:
            matching.append(token)
    return [sorted(row, key=lambda t: t.bbox[0]) for row in rows]


def candidate_from_tokens(
    field: str, tokens: list[Token], *, anchor_confidence: float, geometry_confidence: float
) -> Candidate:
    text = " ".join(t.text for t in tokens)
    value, valid = normalize(field, text)
    evidence = tuple(
        CandidateEvidence(
            source="SPATIAL_EXTRACTION",
            confidence=t.ocr_confidence,
            page_id=t.page_id,
            crop_hash=t.crop_hash,
            localization_region=t.source_region_id,
            source_id=t.source_id,
            provenance_id=t.provenance_id,
            dependencies=t.dependencies,
            bbox=t.bbox,
        )
        for t in tokens
    )
    return Candidate(
        fingerprint((field, [(t.provenance_id, t.source_region_id) for t in tokens], value)),
        text,
        evidence,
        value,
        EvidenceFeatures(geometry_confidence, anchor_confidence, geometry_confidence, valid),
        field,
    )


class SpatialCandidateExtractor:
    def __init__(self, registries: tuple[FieldDefinitionRegistry, ...] | None = None):
        self.registries = registries or tuple(
            FieldDefinitionRegistry.load(ROOT / f"config/field_definitions/{family}_v1.yaml")
            for family in ("cms1500", "ub04")
        )

    def extract(
        self, page: DocumentPage, diagnostics: list[dict] | None = None
    ) -> dict[str, list[Candidate]]:
        if not page.canonical_identity_confirmed:
            return {}
        definitions = [
            d
            for r in self.registries
            for d in r.for_family(page.form_type)
            if d.field_name in TARGET_FIELDS
        ]
        all_labels = {
            label_key(alias)
            for r in self.registries
            for d in r.for_family(page.form_type)
            for alias in (*d.aliases, *d.negative_labels)
        }
        # Support both phrase tokens and adjacent OCR words. A line's value tokens
        # must not become part of its anchor phrase.
        anchors: list[tuple[str, tuple[float, float, float, float], float]] = []
        for row in line_groups(page.tokens):
            for start in range(len(row)):
                for end in range(start + 1, min(len(row), start + 8) + 1):
                    span = row[start:end]
                    text = label_key(" ".join(t.normalized_text for t in span))
                    if text in all_labels:
                        anchors.append(
                            (
                                text,
                                (
                                    span[0].bbox[0],
                                    min(t.bbox[1] for t in span),
                                    span[-1].bbox[2],
                                    max(t.bbox[3] for t in span),
                                ),
                                min(t.ocr_confidence for t in span),
                            )
                        )
        results: dict[str, list[Candidate]] = {}
        for definition in definitions:
            for label, box, anchor_confidence in anchors:
                if label not in {label_key(a) for a in definition.aliases}:
                    continue
                for relation in definition.relationships:
                    # Registry offsets are normalized page distances from anchor origin.
                    roi = (
                        box[0] + relation.x0_offset * page.width,
                        box[3],
                        box[0] + relation.x1_offset * page.width,
                        box[1] + relation.y1_offset * page.height,
                    )
                    # Same-row neighbors bound the field horizontally; the next label
                    # below it bounds the field vertically. Offsets alone can cross cells.
                    right_edges = [
                        b[0]
                        for text, b, _ in anchors
                        if text != label
                        and b[0] > box[0]
                        and abs(b[1] - box[1]) <= max(box[3] - box[1], b[3] - b[1])
                    ]
                    right = min(roi[2], min(right_edges, default=roi[2]))
                    lower_edges = [
                        b[1]
                        for text, b, _ in anchors
                        if text != label and b[1] >= box[3] and b[0] < right and b[2] > roi[0]
                    ]
                    bottom = min(roi[3], min(lower_edges, default=roi[3]))

                    def owned(t: Token, roi=roi, right=right, bottom=bottom) -> bool:
                        x0, y0, x1, y1 = t.bbox
                        overlap = max(0, min(x1, right) - max(x0, roi[0])) * max(
                            0, min(y1, bottom) - max(y0, roi[1])
                        )
                        return (
                            roi[0] <= (x0 + x1) / 2 < right
                            and roi[1] <= (y0 + y1) / 2 < bottom
                            and overlap / ((x1 - x0) * (y1 - y0)) >= 0.8
                        )

                    bounded = tuple(
                        t
                        for t in page.tokens
                        if owned(t) and label_key(t.normalized_text) not in all_labels
                    )
                    if diagnostics is not None:
                        diagnostics.append(
                            {
                                "field": definition.field_name,
                                "roi": [roi[0], roi[1], right, bottom],
                                "tokens": len(bounded),
                            }
                        )
                    for row in line_groups(bounded):
                        if definition.field_name in {"patient_dob", "service_date", "total_charge"}:
                            # Numeric fields must not absorb adjacent sex flags or labels.
                            row = [t for t in row if re.fullmatch(r"[0-9\s/.,$-]+", t.text)]
                        if any(
                            any(c.isdigit() for c in t.text) for t in row
                        ) and definition.field_name in {"patient_name", "insured_name"}:
                            continue
                        # Split spatially separate columns; never concatenate distant values.
                        spans: list[list[Token]] = []
                        for token in row:
                            if spans and token.bbox[0] - spans[-1][-1].bbox[2] <= 2 * (
                                token.bbox[3] - token.bbox[1]
                            ):
                                spans[-1].append(token)
                            else:
                                spans.append([token])
                        for span in spans:
                            candidate = candidate_from_tokens(
                                definition.field_name,
                                span,
                                anchor_confidence=anchor_confidence,
                                geometry_confidence=page.registration_confidence or 0.8,
                            )
                            # Invalid date/code/charge strings cannot be field alternatives.
                            # Original observations remain in DocumentPage for targeted OCR.
                            if (
                                definition.field_name
                                in {
                                    "service_date",
                                    "patient_dob",
                                    "principal_diagnosis",
                                    "total_charge",
                                }
                                and candidate.features.format_valid is False
                            ):
                                continue
                            results.setdefault(definition.field_name, []).append(candidate)
        return {name: bounded_candidates(candidates) for name, candidates in results.items()}


def bounded_candidates(candidates: list[Candidate], limit: int = 5) -> list[Candidate]:
    """Group identical normalized alternatives without treating repeats as independent.

    Invalid syntax remains available as a bounded shadow alternative; it never
    outranks a structurally valid observation. Source evidence is retained.
    """
    grouped: dict[str, Candidate] = {}
    for candidate in merge_candidates(candidates):
        key = candidate.normalized_value or candidate.value
        if key in grouped:
            prior = grouped[key]
            evidence = {fingerprint(e): e for e in (*prior.evidence, *candidate.evidence)}
            grouped[key] = replace(prior, evidence=tuple(evidence.values()))
        else:
            grouped[key] = candidate
    return sorted(grouped.values(), key=lambda c: c.features.format_valid is True, reverse=True)[
        :limit
    ]


def merge_candidates(candidates: list[Candidate]) -> list[Candidate]:
    # Only duplicate IDs are merged. Alternative values and observations survive.
    unique: dict[str, Candidate] = {}
    for candidate in candidates:
        if candidate.candidate_id in unique:
            prior = unique[candidate.candidate_id]
            if (prior.normalized_value or prior.value) != (
                candidate.normalized_value or candidate.value
            ):
                raise ValueError("CANDIDATE_ID_COLLISION")
            evidence = {fingerprint(e): e for e in (*prior.evidence, *candidate.evidence)}
            unique[candidate.candidate_id] = replace(prior, evidence=tuple(evidence.values()))
        else:
            unique[candidate.candidate_id] = candidate
    return list(unique.values())
