from __future__ import annotations

from pydantic import Field

from packages.domain.common import DomainModel
from packages.field_localization import FieldLocationEvidence
from packages.page_observation import PageObservation
from packages.roi_resolution import ROIResolutionMode


class UB04StructuralMap(DomainModel):
    institutional_grid: tuple[int, int, int, int] | None = None
    header_region: tuple[int, int, int, int]
    patient_payer_region: tuple[int, int, int, int]
    provider_region: tuple[int, int, int, int]
    diagnosis_region: tuple[int, int, int, int]
    service_table_region: tuple[int, int, int, int] | None = None
    totals_region: tuple[int, int, int, int]
    confidence: float = Field(ge=0, le=1)
    reason_codes: tuple[str, ...] = ()

    def field_region(self, field_name: str) -> FieldLocationEvidence | None:
        mapping = {
            "member_id": self.patient_payer_region,
            "patient_name": self.patient_payer_region,
            "patient_dob": self.patient_payer_region,
            "provider_name": self.provider_region,
            "provider_npi": self.provider_region,
            "type_of_bill": self.header_region,
            "principal_diagnosis": self.diagnosis_region,
            "total_charge": self.totals_region,
        }
        box = mapping.get(field_name)
        return FieldLocationEvidence(
            field_name=field_name, form_family="UB04", bbox=box,
            method=ROIResolutionMode.STRUCTURAL_REGION, confidence=self.confidence,
            structure_ids=("ub04-structural-map",), reason_codes=self.reason_codes,
        ) if box else None


class UB04StructuralMapDetector:
    version = "ub04-structural-map-v1"

    def detect(self, observation: PageObservation) -> UB04StructuralMap:
        width, height = observation.width, observation.height
        grids = sorted(observation.table_regions,
                       key=lambda item: (item.bbox[2]-item.bbox[0])*(item.bbox[3]-item.bbox[1]),
                       reverse=True)
        grid = grids[0] if grids else None
        # Broad normalized semantic zones are lineage-independent. FieldLocator
        # anchors narrow these regions before they can become field crops.
        service = grid.bbox if grid and grid.bbox[1] >= .25 * height else (
            round(.03*width), round(.28*height), round(.97*width), round(.72*height)
        )
        confidence = min(1.0, .45 + .04*len(observation.vertical_lines) +
                         .02*len(observation.horizontal_lines))
        return UB04StructuralMap(
            institutional_grid=grid.bbox if grid else None,
            header_region=(0, 0, width, round(.22*height)),
            patient_payer_region=(0, round(.12*height), width, round(.35*height)),
            provider_region=(0, 0, round(.65*width), round(.18*height)),
            diagnosis_region=(0, round(.72*height), width, round(.91*height)),
            service_table_region=service,
            totals_region=(round(.60*width), round(.68*height), width, round(.82*height)),
            confidence=confidence,
            reason_codes=(("INSTITUTIONAL_GRID_OBSERVED",) if grid else
                          ("NORMALIZED_INSTITUTIONAL_ZONES",)),
        )
