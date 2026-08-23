from __future__ import annotations

from packages.extraction_geometry import ExtractionGeometryDecision
from packages.roi_resolution import ROIResolutionMode, ROIResolutionResult

from .contracts import FieldLocationEvidence


class DynamicROIResolver:
    """Anchor/structure first; registered template is an optional third-priority fast path."""

    version = "dynamic-roi-resolver-v1"

    def resolve(
        self,
        field_name: str,
        *,
        anchor: FieldLocationEvidence | None,
        structural: FieldLocationEvidence | None,
        geometry: ExtractionGeometryDecision,
        registered_template_bbox: tuple[int, int, int, int] | None = None,
    ) -> ROIResolutionResult:
        if anchor and anchor.method == ROIResolutionMode.ANCHOR_RELATIVE and anchor.bbox:
            return ROIResolutionResult(
                field_name=field_name, mode=ROIResolutionMode.ANCHOR_RELATIVE,
                bbox=anchor.bbox, reason_codes=("DYNAMIC_PRIORITY_1_ANCHOR", *anchor.reason_codes),
                resolver_version=self.version,
            )
        if structural and structural.method == ROIResolutionMode.STRUCTURAL_REGION and structural.bbox:
            return ROIResolutionResult(
                field_name=field_name, mode=ROIResolutionMode.STRUCTURAL_REGION,
                bbox=structural.bbox,
                reason_codes=("DYNAMIC_PRIORITY_2_STRUCTURE", *structural.reason_codes),
                resolver_version=self.version,
            )
        if geometry.authorizes_fixed_roi and registered_template_bbox:
            return ROIResolutionResult(
                field_name=field_name, mode=ROIResolutionMode.FIXED_REGISTERED,
                bbox=registered_template_bbox, reason_codes=("DYNAMIC_PRIORITY_3_TEMPLATE_FAST_PATH",),
                resolver_version=self.version,
            )
        return ROIResolutionResult(
            field_name=field_name, mode=ROIResolutionMode.UNRESOLVED,
            reason_codes=("DYNAMIC_ROI_UNRESOLVED",), resolver_version=self.version,
        )
