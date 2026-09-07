"""Source-reviewed box-67 candidates; no acceptance or form-identity authority.

An anchor is a manual engineering region annotation bound to exact image bytes.
It is not a general UB detector. No reference value is accepted by this API.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from workers.field_candidates.label_token_recovery import Token

AUTHORITY = "SOURCE_VISUAL_ENGINEERING_REVIEW_NOT_RELEASE_TRUTH"


@dataclass(frozen=True)
class SourceBox67Anchor:
    image_sha256: str
    bbox: tuple[float, float, float, float]
    authority: str
    evidence: str


@dataclass(frozen=True)
class Box67Candidate:
    field_name: str
    value: str
    bbox: tuple[float, float, float, float]
    token_indices: tuple[int, ...]
    source_image_sha256: str
    anchor_bbox: tuple[float, float, float, float]
    reason: str = "SOURCE_REVIEWED_BOX_67_INTERIOR"
    review_only: bool = True


def generate_box67(
    tokens: Sequence[Token],
    *,
    image_bytes: bytes,
    token_image_sha256: str,
    anchor: SourceBox67Anchor | None,
) -> list[Box67Candidate]:
    """Preserve raw OCR inside a reviewed principal cell; never borrow box 69."""
    if anchor is None or anchor.authority != AUTHORITY or not anchor.evidence.strip():
        return []
    source_hash = hashlib.sha256(image_bytes).hexdigest()
    if source_hash != anchor.image_sha256 or source_hash != token_image_sha256:
        return []
    left, top, right, bottom = anchor.bbox
    if not (0 <= left < right and 0 <= top < bottom):
        return []
    result = []
    for index, token in enumerate(tokens):
        if not (left <= token.x0 < token.x1 <= right and top <= token.y0 < token.y1 <= bottom):
            continue
        # Lexical filtering only. In particular S is never repaired into 9.
        if not re.fullmatch(r"[A-Za-z][0-9][A-Za-z0-9](?:\.[A-Za-z0-9]{1,4})?", token.text.strip()):
            continue
        result.append(
            Box67Candidate(
                "principal_diagnosis",
                token.text,
                (token.x0, token.y0, token.x1, token.y1),
                (index,),
                source_hash,
                anchor.bbox,
            )
        )
    return result
