"""Page routing (Bundle A/B/C/D): anchor phrases, grid/layout signature,
template similarity, MobileNetV3 fallback, human review escalation."""

from workers.page_detection.anchor_matching import AnchorMatchResult, verify_anchors
from workers.page_detection.grid_signature import (
    GridSignature,
    compute_grid_signature,
    signature_similarity,
)
from workers.page_detection.router import PageRoutingResult, PageRoutingService
from workers.page_detection.template_alignment import AlignmentResult, align_to_reference
from workers.page_detection.text_extraction import (
    ModelNotAvailableError,
    PaddleOCRTextExtractor,
    RapidOCRFullPageTextExtractor,
    TextExtractor,
    TextLine,
)

__all__ = [
    "AlignmentResult",
    "AnchorMatchResult",
    "GridSignature",
    "ModelNotAvailableError",
    "PaddleOCRTextExtractor",
    "RapidOCRFullPageTextExtractor",
    "PageRoutingResult",
    "PageRoutingService",
    "TextExtractor",
    "TextLine",
    "align_to_reference",
    "compute_grid_signature",
    "signature_similarity",
    "verify_anchors",
]
