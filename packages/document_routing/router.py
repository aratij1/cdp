from __future__ import annotations

import re
from difflib import SequenceMatcher
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
import yaml
from PIL import Image
from pydantic import Field

from packages.domain.common import DomainModel


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config/document_routing.yaml"


class TextGeometry(Protocol):
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


class MultiSignalRoute(StrEnum):
    CMS1500 = "CMS1500"
    UB04 = "UB04"
    UNKNOWN_STRUCTURED = "UNKNOWN_STRUCTURED"
    UNKNOWN_UNSTRUCTURED = "UNKNOWN_UNSTRUCTURED"
    NON_CLAIM = "NON_CLAIM"


class RoutingEvidence(DomainModel):
    route: MultiSignalRoute
    confidence: float = Field(ge=0, le=1)
    scores: dict[str, float]
    best_score: float
    second_best_score: float
    margin: float
    grid_score: float
    horizontal_line_score: float
    vertical_line_score: float
    healthcare_label_density: float
    matched_anchors: dict[str, list[str]]
    reason_codes: list[str]


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _anchor_found(anchor: str, text: str) -> bool:
    normalized = _normalize(anchor)
    if normalized in text:
        return True
    words, width = text.split(), len(normalized.split())
    if not words or not width:
        return False
    # A high threshold tolerates a bounded OCR substitution/deletion while
    # preventing short healthcare vocabulary from becoming fuzzy authority.
    return max((SequenceMatcher(None, normalized, " ".join(words[index:index+width])).ratio()
                for index in range(max(1, len(words)-width+1))), default=0) >= .82


def _line_scores(image: Image.Image) -> tuple[float, float, float]:
    gray = np.asarray(image.convert("L"))
    if max(gray.shape) > 1400:
        scale = 1400 / max(gray.shape)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, gray.shape[1]//25), 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, gray.shape[0]//35))))
    h = min(1.0, np.count_nonzero(horizontal) / max(gray.size * .018, 1))
    v = min(1.0, np.count_nonzero(vertical) / max(gray.size * .012, 1))
    return h, v, min(1.0, .55*h + .45*v)


class MultiSignalRouter:
    def __init__(self, config: dict) -> None:
        self.config = config

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG) -> "MultiSignalRouter":
        return cls(yaml.safe_load(Path(path).read_text("utf-8")))

    def route(self, image: Image.Image, lines: list[TextGeometry]) -> RoutingEvidence:
        text = _normalize(" ".join(line.text for line in lines))
        anchors = self.config["anchors"]
        matched = {name: [anchor for anchor in values if _anchor_found(anchor, text)]
                   for name, values in anchors.items()}
        h, v, grid = _line_scores(image)
        cms_anchor = len(matched["CMS1500"]) / len(anchors["CMS1500"])
        ub_anchor = len(matched["UB04"]) / len(anchors["UB04"])
        cms_identity = float(bool(matched["CMS1500_IDENTITY"]))
        ub_identity = float(bool(matched["UB04_IDENTITY"]))
        healthcare = len(matched["healthcare"]) / len(anchors["healthcare"])
        negative = len(matched["negative"]) / max(len(anchors["negative"]), 1)
        # Independent signals: vocabulary cannot promote a standard form by
        # itself, and grid structure cannot distinguish CMS from UB by itself.
        scores = {
            "CMS1500": min(1.0, .45*cms_identity + .40*cms_anchor + .10*grid + .05*healthcare),
            "UB04": min(1.0, .45*ub_identity + .40*ub_anchor + .10*grid + .05*healthcare),
            "UNKNOWN_STRUCTURED": min(1.0, .50*healthcare + .32*grid + .18*min(1, len(lines)/18)),
            "UNKNOWN_UNSTRUCTURED": min(1.0, .45*(1-grid) + .25*healthcare + .30*min(1, len(lines)/12)),
            "NON_CLAIM": min(1.0, .70*negative + .20*(1-healthcare) + .10*(len(lines) < 5)),
        }
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best, second = ranked[0], ranked[1]
        standard = sorted(((name, scores[name]) for name in ("CMS1500", "UB04")),
                          key=lambda item: item[1], reverse=True)
        standard_margin = standard[0][1] - standard[1][1]
        reasons = ["MULTI_SIGNAL_ROUTER", f"BEST:{best[0]}"]
        if (standard[0][1] >= self.config["minimum_standard_score"] and
                standard_margin >= self.config["minimum_standard_margin"]):
            route = MultiSignalRoute(standard[0][0])
            reasons.extend(["STANDARD_MULTI_SIGNAL_THRESHOLD_MET",
                            f"STANDARD_MARGIN:{standard_margin:.3f}"])
        elif (scores["NON_CLAIM"] >= self.config["non_claim_score"] and
              len(matched["negative"]) >= 2 and healthcare <= .20):
            route = MultiSignalRoute.NON_CLAIM
            reasons.append("MULTIPLE_NEGATIVE_ANCHORS_LOW_HEALTHCARE_DENSITY")
        elif scores["UNKNOWN_STRUCTURED"] >= self.config["minimum_structured_score"]:
            route = MultiSignalRoute.UNKNOWN_STRUCTURED
            reasons.append("STANDARD_SCORE_OR_MARGIN_INSUFFICIENT")
        else:
            route = MultiSignalRoute.UNKNOWN_UNSTRUCTURED
            reasons.append("STRUCTURED_EVIDENCE_INSUFFICIENT")
        return RoutingEvidence(
            route=route, confidence=best[1], scores=scores, best_score=best[1],
            second_best_score=second[1], margin=best[1]-second[1], grid_score=grid,
            horizontal_line_score=h, vertical_line_score=v,
            healthcare_label_density=healthcare, matched_anchors=matched,
            reason_codes=reasons,
        )
