"""Field-specific ROI resolution contracts and deterministic resolver."""

from packages.roi_resolution.contracts import (
    AnchorRelativeContract,
    ObservedAnchor,
    ROIResolutionMode,
    ROIResolutionRequest,
    ROIResolutionResult,
)
from packages.roi_resolution.resolver import ROIResolver

__all__ = [
    "AnchorRelativeContract",
    "ObservedAnchor",
    "ROIResolutionMode",
    "ROIResolutionRequest",
    "ROIResolutionResult",
    "ROIResolver",
]
