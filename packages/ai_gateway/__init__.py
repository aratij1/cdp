"""Central boundary for all external AI and cloud OCR calls."""

from packages.ai_gateway.contracts import (
    AIProvider,
    FieldResolutionRequest,
    FieldResolutionResponse,
    GatewayAuditRecord,
    TenantAIPolicy,
)
from packages.ai_gateway.gateway import AIGateway
from packages.ai_gateway.selective_resolution import (
    AuxiliaryCandidate,
    SelectiveResolutionCoordinator,
    SelectiveResolutionError,
    SelectiveResolutionResult,
)
from packages.ai_gateway.orchestration import AdaptiveResolutionService, ResolutionStep

__all__ = [
    "AIGateway",
    "AIProvider",
    "FieldResolutionRequest",
    "FieldResolutionResponse",
    "GatewayAuditRecord",
    "TenantAIPolicy",
    "AuxiliaryCandidate",
    "SelectiveResolutionCoordinator",
    "SelectiveResolutionError",
    "SelectiveResolutionResult",
    "AdaptiveResolutionService",
    "ResolutionStep",
]
