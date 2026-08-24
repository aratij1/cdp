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
                bbox=anchor.bbox, field_structural_confidence=anchor.confidence,
                reason_codes=("DYNAMIC_PRIORITY_1_ANCHOR", *anchor.reason_codes),
                resolver_version=self.version,
            )
        if structural and structural.method == ROIResolutionMode.STRUCTURAL_REGION and structural.bbox:
            return ROIResolutionResult(
                field_name=field_name, mode=ROIResolutionMode.STRUCTURAL_REGION,
                bbox=structural.bbox, field_structural_confidence=structural.confidence,
                reason_codes=("DYNAMIC_PRIORITY_2_STRUCTURE", *structural.reason_codes),
                resolver_version=self.version,
            )
        registration = geometry.registration
        registered_safe = bool(
            geometry.authorizes_fixed_roi
            and geometry.form_identity.status.value == "VERIFIED"
            and geometry.compatibility is not None
            and geometry.compatibility.status.value != "INCOMPATIBLE"
            and registration is not None
            and registration.accepted
            and registration.corner_validity is True
            and geometry.transformed_geometry_valid
            and registration.alignment_confidence >= 0.80
        )
        if registered_safe and registered_template_bbox:
            x0, y0, x1, y1 = registered_template_bbox
            bounded = x1 > x0 and y1 > y0 and x0 >= 0 and y0 >= 0
            if not bounded:
                return ROIResolutionResult(
                    field_name=field_name, mode=ROIResolutionMode.UNRESOLVED,
                    reason_codes=("REGISTERED_TEMPLATE_ROI_INVALID",),
                    resolver_version=self.version,
                )
            return ROIResolutionResult(
                field_name=field_name, mode=ROIResolutionMode.FIXED_REGISTERED,
                bbox=registered_template_bbox,
                field_structural_confidence=registration.alignment_confidence,
                reason_codes=("DYNAMIC_PRIORITY_3_TEMPLATE_FAST_PATH",),
                resolver_version=self.version,
            )
        return ROIResolutionResult(
            field_name=field_name, mode=ROIResolutionMode.UNRESOLVED,
            reason_codes=("DYNAMIC_ROI_UNRESOLVED",), resolver_version=self.version,
        )
