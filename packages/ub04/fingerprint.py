from __future__ import annotations

from pydantic import Field

from packages.document_routing import RoutingEvidence
from packages.domain.common import DomainModel


class UB04FingerprintEvidence(DomainModel):
    page_aspect_ratio: float = Field(gt=0)
    grid_density: float = Field(ge=0, le=1)
    horizontal_line_score: float = Field(ge=0, le=1)
    vertical_line_score: float = Field(ge=0, le=1)
    institutional_anchor_coverage: float = Field(ge=0, le=1)
    identity_anchor_present: bool
    service_line_anchor_count: int = Field(ge=0)
    diagnosis_evidence: bool
    provider_evidence: bool
    type_of_bill_evidence: bool
    total_score: float = Field(ge=0, le=1)
    reason_codes: list[str]


def build_ub04_fingerprint(routing: RoutingEvidence, *, width: int, height: int) -> UB04FingerprintEvidence:
    anchors=routing.matched_anchors.get("UB04",[])
    service={"revenue code","hcpcs","service date","units","total charges"}
    return UB04FingerprintEvidence(
        page_aspect_ratio=width/height,grid_density=routing.grid_score,
        horizontal_line_score=routing.horizontal_line_score,
        vertical_line_score=routing.vertical_line_score,
        institutional_anchor_coverage=len(anchors)/10,
        identity_anchor_present=bool(routing.matched_anchors.get("UB04_IDENTITY")),
        service_line_anchor_count=len(service.intersection(anchors)),
        diagnosis_evidence="principal diagnosis" in anchors,
        provider_evidence=bool(routing.matched_anchors.get("healthcare") and
                               "provider" in routing.matched_anchors["healthcare"]),
        type_of_bill_evidence="type of bill" in anchors,
        total_score=routing.scores["UB04"], reason_codes=routing.reason_codes,
    )
