from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _JoinedGeometry:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


def _ordered_phrase_candidates(lines: list[TextGeometry], anchor: str) -> list[TextGeometry]:
    """Join bounded adjacent OCR tokens while retaining their union geometry."""
    ordered=sorted(lines,key=lambda line:(round(line.y0/18),line.x0,line.y0))
    width=max(1,len(_routing_tokens(anchor)))
    candidates:list[TextGeometry]=list(ordered)
    for size in range(2,min(width+2,6)):
        for index in range(len(ordered)-size+1):
            window=ordered[index:index+size]
            # Prevent phrases from jumping across distant form zones.
            if max(item.y1 for item in window)-min(item.y0 for item in window)>120:
                continue
            candidates.append(_JoinedGeometry(" ".join(item.text for item in window),
                min(item.x0 for item in window),min(item.y0 for item in window),
                max(item.x1 for item in window),max(item.y1 for item in window)))
    return candidates


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
    router_version: str = "2.0"
    exact_anchor_count: int = 0
    normalized_anchor_count: int = 0
    fuzzy_anchor_count: int = 0
    high_value_anchor_count: int = 0
    medium_value_anchor_count: int = 0
    weighted_anchor_coverage: dict[str, float] = Field(default_factory=dict)
    anchor_geometry_score: dict[str, float] = Field(default_factory=dict)
    standard_structure: dict[str, float] = Field(default_factory=dict)
    anchor_geometry_evidence: list[dict] = Field(default_factory=list)
    anchor_combinations: list[dict] = Field(default_factory=list)
    eligibility: dict[str, bool] = Field(default_factory=dict)
    family_eligibility: dict[str, dict] = Field(default_factory=dict)

    @property
    def winning_score(self) -> float:
        return self.best_score

    @property
    def runner_up_score(self) -> float:
        return self.second_best_score


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _routing_tokens(value: str) -> list[str]:
    tokens = _normalize(value).split()
    substitutions = {"patlent":"patient", "diagnos1s":"diagnosis", "biil":"bill",
                     "blll":"bill", "hcpcs":"hcpcs"}
    return [substitutions.get(token, token) for token in tokens]


def _phrase_match(anchor: str, text: str) -> tuple[str | None, float]:
    wanted = _routing_tokens(anchor); observed = _routing_tokens(text)
    if not wanted or not observed:
        return None, 0.0
    normalized_anchor, normalized_text = " ".join(wanted), " ".join(observed)
    if normalized_anchor in normalized_text:
        raw_exact = _normalize(anchor) in _normalize(text)
        return ("EXACT" if raw_exact else "NORMALIZED"), 1.0
    width = len(wanted)
    # Short/generic labels are never fuzzy routing authority.
    if width == 1 or len(normalized_anchor) < 8:
        return None, 0.0
    threshold = .82 if len(normalized_anchor) >= 18 else .88
    best = max((SequenceMatcher(None, normalized_anchor,
                " ".join(observed[index:index+width])).ratio()
                for index in range(max(1, len(observed)-width+1))), default=0.0)
    return ("FUZZY", best) if best >= threshold else (None, best)


def _anchor_found(anchor: str, text: str) -> bool:
    return _phrase_match(anchor, text)[0] is not None


def _bbox_score(line: TextGeometry, zone: list[float], width: int, height: int) -> float:
    cx=((line.x0+line.x1)/2)/max(width,1); cy=((line.y0+line.y1)/2)/max(height,1)
    x0,y0,x1,y1=zone; tolerance=.08
    if x0-tolerance <= cx <= x1+tolerance and y0-tolerance <= cy <= y1+tolerance:
        return 1.0 if x0 <= cx <= x1 and y0 <= cy <= y1 else .65
    return 0.0


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


def _structure_scores(image: Image.Image, h: float, v: float, grid: float) -> dict[str, float]:
    ratio=image.width/max(image.height,1); aspect=max(0.0,1-abs(ratio-.77)/.35)
    gray=np.asarray(image.convert("L")); start=int(gray.shape[0]*.18); end=int(gray.shape[0]*.78)
    band=gray[start:end]
    binary=cv2.threshold(band,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]
    rows=np.count_nonzero(binary,axis=1)/max(binary.shape[1],1)
    repeated=float(np.mean(rows>.28)) if len(rows) else 0.0
    service=min(1.0,repeated/.08)
    return {"grid_score":grid,"horizontal_line_score":h,"vertical_line_score":v,
            "service_table_score":service,"template_similarity":0.0,"aspect_score":aspect,
            "CMS1500":min(1.0,.38*grid+.32*h+.12*v+.18*aspect),
            "UB04":min(1.0,.28*grid+.20*h+.20*v+.20*service+.12*aspect)}


class MultiSignalRouter:
    def __init__(self, config: dict) -> None:
        self.config = config

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG) -> "MultiSignalRouter":
        return cls(yaml.safe_load(Path(path).read_text("utf-8")))

    def route(self, image: Image.Image, lines: list[TextGeometry]) -> RoutingEvidence:
        text = " ".join(line.text for line in lines)
        anchors = self.config["anchors"]
        matched = {name: [anchor for anchor in values if _anchor_found(anchor, text)]
                   for name, values in anchors.items()}
        geometry_evidence=[]; match_counts=Counter(); family_counts={}; geometry_scores={}; weighted={}
        weight_value={"high":3.0,"medium":2.0,"low":.5}
        for family in ("CMS1500","UB04"):
            family_geometry=[]; numerator=denominator=0.0; family_count=Counter()
            classes=self.config.get("anchor_weights",{}).get(family,{})
            for anchor_class, values in classes.items():
                for anchor in values:
                    weight=weight_value[anchor_class]; denominator+=weight
                    candidates=[]
                    for line in _ordered_phrase_candidates(lines,anchor):
                        match_type,phrase_score=_phrase_match(anchor,line.text)
                        if match_type:
                            zone=self.config.get("anchor_zones",{}).get(family,{}).get(anchor)
                            zone_score=_bbox_score(line,zone,image.width,image.height) if zone else .5
                            candidates.append((phrase_score*max(zone_score,.35),line,match_type,
                                               phrase_score,zone_score))
                    if not candidates:
                        continue
                    _,line,match_type,phrase_score,zone_score=max(candidates,key=lambda item:item[0])
                    numerator += weight*phrase_score
                    family_geometry.append(zone_score)
                    match_counts[match_type]+=1; match_counts[anchor_class]+=1
                    family_count[match_type]+=1; family_count[anchor_class]+=1
                    geometry_evidence.append({"family":family,"anchor":anchor,
                        "matched_text":line.text,"expected_zone":self.config.get("anchor_zones",{}).get(family,{}).get(anchor),
                        "observed_bbox":[line.x0,line.y0,line.x1,line.y1],"zone_match":zone_score>0,
                        "geometry_score":zone_score,"match_type":match_type,"phrase_score":phrase_score,
                        "anchor_class":anchor_class.upper()+"_DISCRIMINATION"})
            weighted[family]=numerator/max(denominator,1)
            family_counts[family]=family_count
            geometry_scores[family]=statistics.fmean(family_geometry) if family_geometry else 0.0
        h, v, grid = _line_scores(image)
        structure=_structure_scores(image,h,v,grid)
        cms_anchor = len(matched["CMS1500"]) / len(anchors["CMS1500"])
        ub_anchor = len(matched["UB04"]) / len(anchors["UB04"])
        cms_identity = float(bool(matched["CMS1500_IDENTITY"]))
        ub_identity = float(bool(matched["UB04_IDENTITY"]))
        healthcare = len(matched["healthcare"]) / len(anchors["healthcare"])
        negative = len(matched["negative"]) / max(len(anchors["negative"]), 1)
        combinations=[]; combination_bonus={"CMS1500":0.0,"UB04":0.0}
        for family,items in self.config.get("anchor_combinations",{}).items():
            detected=set(matched[family])
            for item in items:
                present=[anchor for anchor in item["anchors"] if anchor in detected]
                score=len(present)/len(item["anchors"])
                geometry_valid=geometry_scores[family]>=self.config["minimum_geometry_score"]
                combinations.append({"family":family,"combination_id":item["id"],
                    "required_or_weighted_anchors":item["anchors"],"anchors_detected":present,
                    "geometry_valid":geometry_valid,"combination_score":score})
                if geometry_valid and score>=.66: combination_bonus[family]=max(combination_bonus[family],score)
        identity={"CMS1500":cms_identity,"UB04":ub_identity}
        raw_standard={}
        for family in ("CMS1500","UB04"):
            raw_standard[family]=min(1.0,
                .34*weighted[family]+.16*geometry_scores[family]+.25*structure[family]
                +.15*identity[family]+.10*combination_bonus[family])
        scores = {
            "CMS1500": min(1.0,raw_standard["CMS1500"]+self.config.get("identity_discrimination_bonus",0)*cms_identity),
            "UB04": min(1.0,raw_standard["UB04"]+self.config.get("identity_discrimination_bonus",0)*ub_identity),
            "UNKNOWN_STRUCTURED": min(1.0, .50*healthcare + .32*grid + .18*min(1, len(lines)/18)),
            "UNKNOWN_UNSTRUCTURED": min(1.0, .45*(1-grid) + .25*healthcare + .30*min(1, len(lines)/12)),
            "NON_CLAIM": min(1.0, .70*negative + .20*(1-healthcare) + .10*(len(lines) < 5)),
        }
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best, second = ranked[0], ranked[1]
        standard = sorted(((name, scores[name]) for name in ("CMS1500", "UB04")),
                          key=lambda item: item[1], reverse=True)
        standard_margin = standard[0][1] - standard[1][1]
        standard_identity = {
            "CMS1500": cms_identity,
            "UB04": ub_identity,
        }[standard[0][0]]
        standard_specific_anchor_count = len(matched[standard[0][0]])
        identity_backed = (
            standard_identity > 0
            and identity[standard[1][0]] == 0
            and standard_specific_anchor_count > 0
            and weighted[standard[0][0]] > 0
            and structure[standard[0][0]] >= .20
        )
        structure_backed = (
            family_counts[standard[0][0]]["high"] >= 2
            and weighted[standard[0][0]] >= self.config["minimum_weighted_anchor_coverage"]
            and geometry_scores[standard[0][0]] >= self.config["minimum_geometry_score"]
            and structure[standard[0][0]] >= self.config["minimum_structure_score"]
            and standard[0][1] >= self.config["minimum_structure_backed_score"]
        )
        eligible={"CMS1500":False,"UB04":False}; eligible[standard[0][0]]=identity_backed or structure_backed
        reasons = ["MULTI_SIGNAL_ROUTER", f"BEST:{best[0]}"]
        if eligible[standard[0][0]] and standard_margin >= self.config["minimum_standard_margin"]:
            route = MultiSignalRoute(standard[0][0])
            reasons.extend([f"{standard[0][0].replace('1500','')}_IDENTITY_CONFIRMED" if identity_backed
                            else f"{standard[0][0].replace('1500','')}_STRUCTURE_CONFIRMED",
                            f"{standard[0][0].replace('1500','')}_WEIGHTED_ANCHORS",
                            f"STANDARD_MARGIN:{standard_margin:.3f}"])
            if geometry_scores[standard[0][0]]>=self.config["minimum_geometry_score"]:
                reasons.append(f"{standard[0][0].replace('1500','')}_GEOMETRY_CONFIRMED")
            if standard[0][0]=="UB04" and structure["service_table_score"]>=.35:
                reasons.append("UB04_SERVICE_TABLE_CONFIRMED")
        elif (scores["NON_CLAIM"] >= self.config["non_claim_score"] and
              len(matched["negative"]) >= 2 and healthcare <= .20):
            route = MultiSignalRoute.NON_CLAIM
            reasons.append("MULTIPLE_NEGATIVE_ANCHORS_LOW_HEALTHCARE_DENSITY")
        elif scores["UNKNOWN_STRUCTURED"] >= self.config["minimum_structured_score"]:
            route = MultiSignalRoute.UNKNOWN_STRUCTURED
            reasons.extend(["STANDARD_EVIDENCE_INSUFFICIENT",
                            "UNKNOWN_STRUCTURED_CONFIRMED"])
        else:
            route = MultiSignalRoute.UNKNOWN_UNSTRUCTURED
            reasons.append("UNKNOWN_UNSTRUCTURED_CONFIRMED")
        return RoutingEvidence(
            route=route, confidence=best[1], scores=scores, best_score=best[1],
            second_best_score=second[1], margin=best[1]-second[1], grid_score=grid,
            horizontal_line_score=h, vertical_line_score=v,
            healthcare_label_density=healthcare, matched_anchors=matched,
            reason_codes=reasons,router_version=self.config.get("router_version","3.0"),
            exact_anchor_count=match_counts["EXACT"],normalized_anchor_count=match_counts["NORMALIZED"],
            fuzzy_anchor_count=match_counts["FUZZY"],high_value_anchor_count=match_counts["high"],
            medium_value_anchor_count=match_counts["medium"],weighted_anchor_coverage=weighted,
            anchor_geometry_score=geometry_scores,standard_structure=structure,
            anchor_geometry_evidence=geometry_evidence,anchor_combinations=combinations,
            eligibility=eligible,
        )
