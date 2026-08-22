from .router import MultiSignalRoute, MultiSignalRouter, RoutingEvidence

RouteDecision = RoutingEvidence
CanonicalRoutingDecisionService = MultiSignalRouter

__all__ = ["CanonicalRoutingDecisionService", "MultiSignalRoute", "MultiSignalRouter",
           "RouteDecision", "RoutingEvidence"]
