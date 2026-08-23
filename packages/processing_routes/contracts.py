from enum import StrEnum

from packages.domain.common import DomainModel

PROCESSING_ROUTE_CONTRACT_VERSION = "processing-route-contract-v1.0.0"


class ProcessingRoute(StrEnum):
    CMS_STANDARD_EXTRACTOR = "CMS_STANDARD_EXTRACTOR"
    UB_STANDARD_EXTRACTOR = "UB_STANDARD_EXTRACTOR"
    LAYOUT_STRUCTURED_EXTRACTOR = "LAYOUT_STRUCTURED_EXTRACTOR"
    UNSTRUCTURED_EXTRACTOR = "UNSTRUCTURED_EXTRACTOR"
    STOP_NON_CLAIM = "STOP_NON_CLAIM"
    SAFE_UNKNOWN = "SAFE_UNKNOWN"

    # Compatibility aliases; serialized values remain the canonical V1 values.
    CMS_FIXED_TEMPLATE = "CMS_STANDARD_EXTRACTOR"
    UB_FIXED_TEMPLATE = "UB_STANDARD_EXTRACTOR"
    LAYOUT_STRUCTURED = "LAYOUT_STRUCTURED_EXTRACTOR"
    LAYOUT_UNSTRUCTURED = "UNSTRUCTURED_EXTRACTOR"
    NON_CLAIM_STOP = "STOP_NON_CLAIM"


class ProcessingRouteDecision(DomainModel):
    route: ProcessingRoute
    reason_codes: tuple[str, ...]
    policy_version: str = "processing-route-policy-v1"
