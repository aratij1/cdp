"""Anchor-relative candidate generation using the existing field registry."""

from __future__ import annotations

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

    def extract(self, page: DocumentPage) -> dict[str, list[Candidate]]:
        if not page.canonical_identity_confirmed:
            return {}
        definitions = [
            d
            for r in self.registries
            for d in r.for_family(page.form_type)
            if d.field_name in TARGET_FIELDS
        ]
        all_labels = {
            alias.upper().rstrip(":")
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
                    text = " ".join(t.normalized_text for t in span).upper().rstrip(":")
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
                if label not in {a.upper().rstrip(":") for a in definition.aliases}:
                    continue
                for relation in definition.relationships:
                    # Registry offsets are normalized page distances from anchor origin.
                    roi = (
                        box[0] + relation.x0_offset * page.width,
                        box[1] + relation.y0_offset * page.height,
                        box[0] + relation.x1_offset * page.width,
                        box[1] + relation.y1_offset * page.height,
                    )
                    bounded = tuple(
                        t
                        for t in page.tokens
                        if roi[0] <= t.bbox[0] < t.bbox[2] <= roi[2]
                        and roi[1] <= t.bbox[1] < t.bbox[3] <= roi[3]
                        and t.normalized_text.upper().rstrip(":") not in all_labels
                    )
                    # A neighboring anchor inside the region owns the tokens below it.
                    neighbor_boxes = [
                        b
                        for text, b, _ in anchors
                        if text != label and roi[0] <= b[0] < roi[2] and roi[1] <= b[1] < roi[3]
                    ]
                    bounded = tuple(
                        t for t in bounded if not any(t.bbox[1] >= b[1] for b in neighbor_boxes)
                    )
                    for row in line_groups(bounded):
                        if any(
                            any(c.isdigit() for c in t.text) for t in row
                        ) and definition.field_name.endswith("name"):
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
                            results.setdefault(definition.field_name, []).append(
                                candidate_from_tokens(
                                    definition.field_name,
                                    span,
                                    anchor_confidence=anchor_confidence,
                                    geometry_confidence=page.registration_confidence or 0.8,
                                )
                            )
        return {name: merge_candidates(candidates) for name, candidates in results.items()}


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
