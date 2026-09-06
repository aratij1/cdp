"""Bounded registry-label discovery outside canonical extraction.

This produces review candidates only. It cannot confirm a form, authorize
localization, create truth, or change a canonical claim decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from packages.field_localization.scoring import type_compatibility

from .document import DocumentPage, fingerprint
from .models import Candidate
from .normalization import calendar_date
from .spatial import (
    TARGET_FIELDS,
    SpatialCandidateExtractor,
    bounded_candidates,
    candidate_from_tokens,
    label_key,
    line_groups,
)


def _within_two_edits(left: str, right: str) -> bool:
    """Bounded whole-label distance; no prefix, substring or value matching."""
    if abs(len(left) - len(right)) > 2:
        return False
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (char != other)))
        if min(current) > 2:
            return False
        previous = current
    return previous[-1] <= 2


@dataclass(frozen=True)
class DiscoveryResult:
    candidates: dict[str, list[Candidate]]
    authority: str = field(default="UNVERIFIED_DISCOVERY", init=False)
    canonical_localization: bool = field(default=False, init=False)
    production_authority: bool = field(default=False, init=False)


class NoncanonicalDiscovery:
    """Reuse token geometry and registry labels; approximate labels stay weak."""

    def __init__(self) -> None:
        registries = SpatialCandidateExtractor().registries
        aliases: dict[str, set[str]] = {}
        self.boundaries: set[str] = set()
        for registry in registries:
            for definition in registry.definitions:
                self.boundaries.update(
                    label_key(a) for a in (*definition.aliases, *definition.negative_labels)
                )
                if definition.field_name in TARGET_FIELDS | {
                    "provider_npi",
                    "relationship",
                    "type_of_bill",
                    "diagnosis",
                }:
                    for alias in definition.aliases:
                        aliases.setdefault(label_key(alias), set()).add(definition.field_name)
        # A generic TOTAL is not specific enough to identify a claim total.
        self.labels = {
            key: next(iter(names))
            for key, names in aliases.items()
            if len(names) == 1 and key != "TOTAL"
        }

    def _anchors(self, page: DocumentPage):
        # Printed-label punctuation only. Observed values are never normalized here.
        def key(token):
            return label_key(token.normalized_text).strip("[]()")

        anchors = []
        for token in page.tokens:
            observed = key(token)
            if observed in self.boundaries:
                anchors.append((token, observed))
                continue
            # A compound is exact only when every part names the same registry field.
            parts = observed.split("/")
            fields = {self.labels.get(part) for part in parts}
            if len(parts) > 1 and len(fields) == 1 and None not in fields:
                anchors.append((token, parts[0]))
        exact = tuple(anchors)
        weak = set()
        for token in page.tokens:
            if any(token is a for a, _ in exact):
                continue
            observed = key(token)
            if len(observed) < 10:
                continue
            matches = [
                alias
                for alias in self.labels
                if self.labels[alias]
                in {"patient_name", "insured_name", "provider_name", "principal_diagnosis"}
                and len(alias) >= 10
                and _within_two_edits(observed, alias)
            ]
            fields = {self.labels[alias] for alias in matches}
            if len(fields) != 1:
                continue
            # A second literal field label must corroborate the row. Approximate
            # labels cannot bootstrap one another or confirm document identity.
            height = token.bbox[3] - token.bbox[1]
            if not any(
                self.labels.get(alias) not in fields
                and abs((a.bbox[1] + a.bbox[3] - token.bbox[1] - token.bbox[3]) / 2)
                <= max(height, a.bbox[3] - a.bbox[1])
                and (a.bbox[2] <= token.bbox[0] or a.bbox[0] >= token.bbox[2])
                for a, alias in exact
            ):
                continue
            anchors.append((token, min(matches)))
            weak.add(id(token))
        return anchors, weak

    def extract(self, page: DocumentPage, regions: list[dict] | None = None) -> DiscoveryResult:
        if page.form_type != "OTHER_CLAIM_FORM":
            return DiscoveryResult({})
        anchors, weak = self._anchors(page)
        anchor_ids = {id(token) for token, _ in anchors}
        result: dict[str, list[Candidate]] = {}
        for anchor, key in anchors:
            if key not in self.labels:
                continue
            name = self.labels[key]
            x0, y0, x1, y1 = anchor.bbox
            height = y1 - y0
            overlap = 0.35 if id(anchor) in weak else 0.25
            left = max(0, x0 - height)
            right = min(page.width, x0 + max(x1 - x0, page.width * 0.25))
            bottom = min(page.height, y1 + height * 3)
            inline_right = min(page.width, x1 + page.width * 0.25)
            for neighbor, other in anchors:
                if other == key:
                    continue
                nx0, ny0, nx1, ny1 = neighbor.bbox
                if nx0 > x0 and abs(ny0 - y0) <= max(height, ny1 - ny0):
                    right = min(right, nx0)
                    if nx0 >= x1:
                        inline_right = min(inline_right, nx0)
                if ny0 >= y1 and nx0 < right and nx1 > x0:
                    bottom = min(bottom, ny0)
            if regions is not None and right > left and bottom > y1:
                regions.append(
                    {
                        "field": name,
                        "bbox": (left, max(0, y1 - height * 0.25), right, bottom),
                        "reason": "OBSERVED_LABEL_NEIGHBORHOOD",
                    }
                )
            tokens = tuple(
                t
                for t in page.tokens
                if id(t) not in anchor_ids
                and label_key(t.normalized_text) not in self.boundaries
                and left <= t.bbox[0] < t.bbox[2] <= right
                and y1 <= (t.bbox[1] + t.bbox[3]) / 2
                and t.bbox[1] >= y1 - height * overlap
                and t.bbox[3] <= bottom
            )
            inline = tuple(
                t
                for t in page.tokens
                if id(t) not in anchor_ids
                and label_key(t.normalized_text) not in self.boundaries
                and x1 <= t.bbox[0] < t.bbox[2] <= inline_right
                and t.bbox[0] - x1 <= height * 3
                and abs((t.bbox[1] + t.bbox[3]) / 2 - (y0 + y1) / 2) <= height * 0.5
            )
            for row in [*line_groups(inline), *line_groups(tokens)]:
                if name in {"relationship", "type_of_bill"}:
                    # These registry fields are atomic printed values. Preserve each
                    # complete observed token; do not trim a prefix or join flags.
                    for token in row:
                        valid = (
                            type_compatibility("ALPHANUMERIC_ID", token.text, name) == 1.0
                            if name == "relationship"
                            else bool(re.fullmatch(r"0?[0-9]{3}", token.text))
                        )
                        if valid:
                            atom = candidate_from_tokens(
                                name,
                                [token],
                                anchor_confidence=anchor.ocr_confidence,
                                geometry_confidence=0.5,
                            )
                            result.setdefault(name, []).append(
                                replace(
                                    atom,
                                    features=replace(atom.features, format_valid=True),
                                )
                            )
                    continue
                if name in {"patient_dob", "service_date", "total_charge"}:
                    row = [t for t in row if re.fullmatch(r"[0-9\s/.,$-]+", t.text)]
                    if not row:
                        continue
                # A complete calendar token is a bounded observation in its own right.
                # Preserve it separately from adjacent numeric flags; never trim a token
                # or manufacture a date from a substring of corrupted OCR text.
                if name in {"patient_dob", "service_date"} and len(row) > 1:
                    for token in row:
                        if calendar_date(token.text) is not None:
                            result.setdefault(name, []).append(
                                candidate_from_tokens(
                                    name,
                                    [token],
                                    anchor_confidence=anchor.ocr_confidence,
                                    geometry_confidence=0.5,
                                )
                            )
                candidate = candidate_from_tokens(
                    name, row, anchor_confidence=anchor.ocr_confidence, geometry_confidence=0.5
                )
                if candidate.features.format_valid is True:
                    if id(anchor) in weak:
                        candidate = replace(
                            candidate,
                            candidate_id=fingerprint((candidate.candidate_id, "WEAK_LABEL")),
                            evidence=tuple(
                                replace(
                                    e,
                                    source="WEAK_LABEL_DISCOVERY",
                                    metadata={
                                        "label_match": "APPROXIMATE",
                                        "anchor_bbox": anchor.bbox,
                                    },
                                )
                                for e in candidate.evidence
                            ),
                            features=replace(candidate.features, anchor_confidence=None),
                        )
                    result.setdefault(name, []).append(candidate)
        bounded = {}
        for name, values in result.items():
            exact_values = {
                c.normalized_value or c.value
                for c in values
                if all(e.source == "SPATIAL_EXTRACTION" for e in c.evidence)
            }
            # Weak duplicates cannot contaminate or replace a literal observation.
            retained = [
                c
                for c in values
                if all(e.source == "SPATIAL_EXTRACTION" for e in c.evidence)
                or (c.normalized_value or c.value) not in exact_values
            ]
            bounded[name] = bounded_candidates(retained, 3)
        return DiscoveryResult(bounded)


def select_recovery(
    field_name: str,
    candidates: list[Candidate],
    *,
    existing_value: str | None,
    wrong_crop: bool = False,
    missing_crop: bool = False,
) -> tuple[Candidate | None, tuple[str, ...]]:
    """Rank one label-bound recovery in shadow; retain sound existing extraction.

    Field-family syntax is checked before selection. Formatting agreement is not
    independent evidence, identity validation, or permission to overwrite a value.
    """
    from .normalization import comparison_key, normalize
    from .provenance import complete

    families = {
        "patient_name": "NAME",
        "insured_name": "NAME",
        "provider_name": "ORGANIZATION_NAME",
        "member_id": "IDENTIFIER",
        "patient_dob": "DATE",
        "service_date": "DATE",
        "total_charge": "CHARGE",
        "principal_diagnosis": "DIAGNOSIS",
    }
    if field_name not in families:
        return None, ("FIELD_FAMILY_NOT_SUPPORTED",)
    if existing_value and not wrong_crop and not missing_crop:
        return None, ("EXISTING_EXTRACTION_RETAINED",)
    valid = [
        c
        for c in candidates
        if c.field_name == field_name
        and c.features.format_valid is True
        and normalize(field_name, c.value)[1] is True
        and c.evidence
        and all(e.source == "SPATIAL_EXTRACTION" and complete(e) for e in c.evidence)
    ]
    keys = {comparison_key(field_name, c.normalized_value or c.value) for c in valid}
    if not valid or len(keys) != 1 or not all(keys):
        return None, ("NO_UNIQUE_STRUCTURAL_RECOVERY",)
    chosen = min(
        valid,
        key=lambda c: (-min((e.confidence or 0 for e in c.evidence), default=0), c.candidate_id),
    )
    return chosen, (
        families[field_name] + "_STRUCTURALLY_VALID",
        "OBSERVED_LABEL_BOUND",
        "RECOVERY_FROM_MISSING_OR_WRONG_CROP",
        "SHADOW_ONLY",
    )
