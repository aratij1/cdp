from .router import MultiSignalRoute, MultiSignalRouter, RoutingEvidence

RouteDecision = RoutingEvidence
CanonicalRoutingDecisionService = MultiSignalRouter
from .observation import RouterObservation, build_router_observation
from .structural import StructuralDescriptors, describe_structure
from .v4 import InvariantRouterV4, StructuredDocumentEvidence
from .features import (NormalizedPageGeometry, RouterFeatureBundle, TokenGroupMatch,
                       build_router_feature_bundle, detect_content_bounds, recover_token_groups)
from .eligibility import StandardEligibilityEvidence, evaluate_standard_eligibility

__all__ = ["CanonicalRoutingDecisionService", "MultiSignalRoute", "MultiSignalRouter",
           "RouteDecision", "RouterObservation", "RoutingEvidence", "build_router_observation",
           "InvariantRouterV4", "StructuredDocumentEvidence", "StructuralDescriptors", "describe_structure",
           "NormalizedPageGeometry", "RouterFeatureBundle", "TokenGroupMatch",
           "build_router_feature_bundle", "detect_content_bounds", "recover_token_groups",
           "StandardEligibilityEvidence", "evaluate_standard_eligibility"]
