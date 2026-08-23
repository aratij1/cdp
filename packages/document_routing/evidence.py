from packages.domain.common import DomainModel
from packages.document_routing.router import MultiSignalRoute, RoutingEvidence


class HierarchicalRoutingEvidence(DomainModel):
    legacy_route: MultiSignalRoute
    structured: bool
    claim_related: bool
    confidence: float
    supporting_codes: tuple[str, ...]
    contradicting_codes: tuple[str, ...] = ()


def from_routing_evidence(evidence: RoutingEvidence) -> HierarchicalRoutingEvidence:
    return HierarchicalRoutingEvidence(legacy_route=evidence.route,
        structured=evidence.route in {MultiSignalRoute.CMS1500, MultiSignalRoute.UB04,
                                      MultiSignalRoute.UNKNOWN_STRUCTURED},
        claim_related=evidence.route not in {MultiSignalRoute.NON_CLAIM}, confidence=evidence.confidence,
        supporting_codes=tuple(evidence.reason_codes))
