"""Hash-bound, source-reviewed field discovery. Never production form authority."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from workers.field_candidates.label_token_recovery import Token

AUTHORITY = "SOURCE_ONLY_VISUAL_TOPOLOGY_REVIEW_NOT_PRODUCTION_FORM_AUTHORITY"
SUPPORTED_FORMS = {"CMS1500", "UB"}
SUPPORTED_FIELDS = {"patient_name", "insured_name", "member_id", "total_charge"}


@dataclass(frozen=True, slots=True)
class SourceReviewedAnchor:
    source_sha256: str
    form_type: str
    field_name: str
    anchor_region: tuple[float, float, float, float]
    allowed_candidate_region: tuple[float, float, float, float]
    anchor_version: str
    review_provenance: str
    rotation: int = 0


@dataclass(frozen=True, slots=True)
class ReviewedSourceIdentity:
    source_sha256: str
    form_type: str
    rotation: int
    provenance: str


@dataclass(frozen=True)
class ReviewedCandidate:
    field_name: str
    value: str
    token_indices: tuple[int, ...]
    source_sha256: str
    form_type: str
    bbox: tuple[float, float, float, float]
    reason: str
    review_only: bool = True


def anchored_tokens(
    tokens: Sequence[Token],
    *,
    image_bytes: bytes,
    token_source_sha256: str,
    identity: ReviewedSourceIdentity,
    anchor: SourceReviewedAnchor,
    field_name: str,
    rotation: int,
) -> list[tuple[int, Token]]:
    """Fail closed on unknown/wrong form, source, field, coordinate frame or provenance."""
    digest = hashlib.sha256(image_bytes).hexdigest()
    if not (digest == token_source_sha256 == identity.source_sha256 == anchor.source_sha256):
        return []
    if not (identity.form_type == anchor.form_type and identity.form_type in SUPPORTED_FORMS):
        return []
    if not (field_name == anchor.field_name and field_name in SUPPORTED_FIELDS):
        return []
    if not (identity.provenance == anchor.review_provenance == AUTHORITY):
        return []
    if not (rotation == identity.rotation == anchor.rotation and rotation in (0, 180)):
        return []
    if anchor.anchor_version != "form-topology-v1":
        return []
    for region in (anchor.anchor_region, anchor.allowed_candidate_region):
        if not (0 <= region[0] < region[2] and 0 <= region[1] < region[3]):
            return []
    l, t, r, b = anchor.allowed_candidate_region
    return [
        (i, token)
        for i, token in enumerate(tokens)
        if l <= token.x0 < token.x1 <= r and t <= token.y0 < token.y1 <= b
    ]


def name_candidates(
    items: list[tuple[int, Token]], anchor: SourceReviewedAnchor
) -> list[ReviewedCandidate]:
    """Assemble spatial rows and observed LAST/FIRST notation without correcting characters."""
    if anchor.field_name not in {"patient_name", "insured_name"}:
        return []
    clean = []
    for i, token in items:
        text = token.text.strip()
        if not re.fullmatch(r"[A-Za-z ,.'-]+", text):
            continue
        if re.search(
            r"name|namo|namf|namc|nams|nanc|address|insured|patient|birth|same|self|medic|initial",
            text,
            re.IGNORECASE,
        ):
            continue
        if text.lower() in {"a", "b", "c", "s", "f", "m", "x"}:
            continue
        clean.append((i, token))
    rows: list[list[tuple[int, Token]]] = []
    for item in sorted(clean, key=lambda x: (x[1].y0, x[1].x0)):
        center = (item[1].y0 + item[1].y1) / 2
        for row in rows:
            first = row[0][1]
            if (
                abs(center - (first.y0 + first.y1) / 2)
                < min(first.y1 - first.y0, item[1].y1 - item[1].y0) * 0.6
            ):
                row.append(item)
                break
        else:
            rows.append([item])
    result = []
    for row in rows:
        row.sort(key=lambda x: x[1].x0)
        raw = " ".join(t.text.strip() for _, t in row)
        words = re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", raw)
        if not 2 <= len(words) <= 5:
            continue
        # Source-reviewed CMS labels explicitly specify LAST, FIRST, MIDDLE.
        # UB reviewed comma-separated rows establish this same bounded topology.
        # Ambiguous multiword surnames are retained raw rather than guessed.
        if "," in raw:
            family, rest = raw.split(",", 1)
            last = re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", family)
            given = re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", rest)
            ordered = " ".join(given + last) if last and given else raw
        elif anchor.form_type == "CMS1500" or len(words) == 2:
            ordered = " ".join(words[1:] + words[:1])
        else:
            ordered = raw
        bbox = (
            min(t.x0 for _, t in row),
            min(t.y0 for _, t in row),
            max(t.x1 for _, t in row),
            max(t.y1 for _, t in row),
        )
        for value in dict.fromkeys((ordered, raw)):
            result.append(
                ReviewedCandidate(
                    anchor.field_name,
                    value,
                    tuple(i for i, _ in row),
                    anchor.source_sha256,
                    anchor.form_type,
                    bbox,
                    "REVIEWED_NAME_CELL_ROW_ASSEMBLY",
                )
            )
    return result


def discover_names(
    tokens: Sequence[Token],
    *,
    image_bytes: bytes,
    token_source_sha256: str,
    identity: ReviewedSourceIdentity,
    anchor: SourceReviewedAnchor,
    field_name: str,
    rotation: int,
) -> list[ReviewedCandidate]:
    """Public discovery entry point: all identity guards precede row assembly."""
    items = anchored_tokens(
        tokens,
        image_bytes=image_bytes,
        token_source_sha256=token_source_sha256,
        identity=identity,
        anchor=anchor,
        field_name=field_name,
        rotation=rotation,
    )
    return name_candidates(items, anchor)
