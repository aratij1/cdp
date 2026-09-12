from .router import MultiSignalRoute, MultiSignalRouter, RoutingEvidence

RouteDecision = RoutingEvidence
CanonicalRoutingDecisionService = MultiSignalRouter
from .contracts import DocumentRoutingDecision
from .decision_service import DocumentRoutingDecisionService
from .eligibility import StandardEligibilityEvidence, evaluate_standard_eligibility
from .features import (
                       NormalizedPageGeometry,
                       RouterFeatureBundle,
                       TokenGroupMatch,
                       build_router_feature_bundle,
                       detect_content_bounds,
                       recover_token_groups,
)
from .observation import RouterObservation, build_router_observation
from .structural import StructuralDescriptors, describe_structure
from .v4 import InvariantRouterV4, StructuredDocumentEvidence

__all__ = [
                       "CanonicalRoutingDecisionService",
                       "DocumentRoutingDecision",
                       "DocumentRoutingDecisionService",
                       "InvariantRouterV4",
                       "MultiSignalRoute",
                       "MultiSignalRouter",
                       "NormalizedPageGeometry",
                       "RouteDecision",
                       "RouterFeatureBundle",
                       "RouterObservation",
                       "RoutingEvidence",
                       "StandardEligibilityEvidence",
                       "StructuralDescriptors",
                       "StructuredDocumentEvidence",
                       "TokenGroupMatch",
                       "build_router_feature_bundle",
                       "build_router_observation",
                       "describe_structure",
                       "detect_content_bounds",
                       "evaluate_standard_eligibility",
                       "recover_token_groups",
]
