from __future__ import annotations

from packages.extraction_geometry.contracts import (
    ExtractionGeometryMode,
    FormIdentityStatus,
)
from packages.roi_resolution.contracts import (
    ROIResolutionMode,
    ROIResolutionRequest,
    ROIResolutionResult,
)


def _clip(box: tuple[int, int, int, int], width: int, height: int):
    x0, y0, x1, y1 = box
    clipped = (max(0, x0), max(0, y0), min(width, x1), min(height, y1))
    return clipped if clipped[2] > clipped[0] and clipped[3] > clipped[1] else None


class ROIResolver:
    version = "roi-resolver-v1"

    def resolve(self, request: ROIResolutionRequest) -> ROIResolutionResult:
        geometry = request.geometry
        if geometry.mode == ExtractionGeometryMode.REGISTERED_FIXED:
            if not geometry.authorizes_fixed_roi or request.fixed_region is None:
                return self._unresolved(request, "FIXED_GEOMETRY_NOT_AUTHORIZED")
            box = _clip(request.fixed_region, request.page_width, request.page_height)
            return (
                ROIResolutionResult(field_name=request.field_name,
                    mode=ROIResolutionMode.FIXED_REGISTERED, bbox=box,
                    field_structural_confidence=geometry.registration.alignment_confidence,
                    reason_codes=("REGISTERED_TEMPLATE_ROI",))
                if box else self._unresolved(request, "FIXED_ROI_OUT_OF_BOUNDS")
            )
        if geometry.mode == ExtractionGeometryMode.ANCHOR_RELATIVE:
            if geometry.form_identity.status != FormIdentityStatus.VERIFIED:
                return self._unresolved(request, "ANCHOR_ROI_REQUIRES_VERIFIED_IDENTITY")
            contract = request.anchor_contract
            if contract is None or contract.field_name != request.field_name:
                return self._unresolved(request, "FIELD_ANCHOR_CONTRACT_MISSING")
            anchor = next((item for item in request.observed_anchors
                           if item.anchor_id == contract.anchor_id), None)
            if anchor is None or anchor.confidence < contract.min_anchor_confidence:
                return self._unresolved(request, "REQUIRED_FIELD_ANCHOR_UNAVAILABLE")
            ax0, ay0, _, _ = anchor.bbox
            box = _clip((
                round(ax0 + contract.x0_offset * request.page_width),
                round(ay0 + contract.y0_offset * request.page_height),
                round(ax0 + contract.x1_offset * request.page_width),
                round(ay0 + contract.y1_offset * request.page_height),
            ), request.page_width, request.page_height)
            return (
                ROIResolutionResult(field_name=request.field_name,
                    mode=ROIResolutionMode.ANCHOR_RELATIVE, bbox=box,
                    field_structural_confidence=anchor.confidence,
                    reason_codes=("FIELD_SPECIFIC_ANCHOR_CONTRACT",))
                if box else self._unresolved(request, "ANCHOR_RELATIVE_ROI_OUT_OF_BOUNDS")
            )
        if geometry.mode == ExtractionGeometryMode.STRUCTURAL_LAYOUT:
            box = request.structural_region and _clip(
                request.structural_region, request.page_width, request.page_height)
            return (
                ROIResolutionResult(field_name=request.field_name,
                    mode=ROIResolutionMode.STRUCTURAL_REGION, bbox=box,
                    field_structural_confidence=geometry.structural_confidence or 0.0,
                    reason_codes=("STRUCTURAL_REGION",))
                if box else self._unresolved(request, "STRUCTURAL_REGION_UNAVAILABLE")
            )
        return self._unresolved(request, "EXTRACTION_GEOMETRY_UNAVAILABLE")

    def _unresolved(self, request: ROIResolutionRequest, reason: str) -> ROIResolutionResult:
        return ROIResolutionResult(
            field_name=request.field_name,
            mode=ROIResolutionMode.UNRESOLVED,
            reason_codes=(reason,),
            resolver_version=self.version,
        )
