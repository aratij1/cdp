"""In-memory OCR perception contracts; diagnostics never contain recognized text."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from packages.ocr.contracts import OCRToken


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class Token:
    text: str
    normalized_text: str
    bbox: tuple[float, float, float, float]
    ocr_confidence: float
    engine: str
    page_id: str
    source_region_id: str
    provenance_id: str
    source_id: str
    crop_hash: str
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            (
                self.page_id,
                self.source_region_id,
                self.provenance_id,
                self.source_id,
                self.crop_hash,
                self.engine,
            )
        ):
            raise ValueError("TOKEN_PROVENANCE_REQUIRED")
        if not math.isfinite(self.ocr_confidence) or not 0 <= self.ocr_confidence <= 1:
            raise ValueError("INVALID_TOKEN_CONFIDENCE")
        x0, y0, x1, y1 = self.bbox
        if not all(math.isfinite(v) for v in self.bbox) or x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
            raise ValueError("INVALID_TOKEN_GEOMETRY")


@dataclass(frozen=True)
class DocumentPage:
    page_id: str
    package_id: str
    form_type: str
    form_identity_state: str
    width: int
    height: int
    quality_band: str
    tokens: tuple[Token, ...]
    registration_confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.page_id or not self.package_id or self.width <= 0 or self.height <= 0:
            raise ValueError("INVALID_PAGE")
        if any(
            t.page_id != self.page_id or t.bbox[2] > self.width or t.bbox[3] > self.height
            for t in self.tokens
        ):
            raise ValueError("TOKEN_PAGE_OR_GEOMETRY_MISMATCH")

    @property
    def canonical_identity_confirmed(self) -> bool:
        return self.form_type in {"CMS1500", "UB04"} and self.form_identity_state == "VERIFIED"

    def diagnostics(self) -> dict[str, Any]:
        return {
            "page_id": fingerprint(self.page_id),
            "package_id": fingerprint(self.package_id),
            "width": self.width,
            "height": self.height,
            "tokens": len(self.tokens),
            "canonical_identity_confirmed": self.canonical_identity_confirmed,
        }


def adapt_ocr_tokens(
    tokens: tuple[OCRToken, ...],
    *,
    page_id: str,
    source_id: str,
    engine: str,
    invocation_id: str,
    crop_hash: str,
) -> tuple[Token, ...]:
    result = []
    for token in tokens:
        box = token.bounding_box
        bbox = (float(box.x0), float(box.y0), float(box.x1), float(box.y1))
        # Region identity depends on source pixels, never on the OCR engine name.
        region = fingerprint((source_id, page_id, bbox))
        result.append(
            Token(
                token.text,
                " ".join(token.text.split()),
                bbox,
                token.confidence,
                engine,
                page_id,
                region,
                invocation_id,
                source_id,
                crop_hash,
            )
        )
    return tuple(result)
