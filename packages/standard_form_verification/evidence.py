from pydantic import Field

from packages.domain.common import DomainModel
from packages.document_taxonomy.taxonomy import DocumentClass


class StandardFormEvidence(DomainModel):
    candidate_family: DocumentClass
    page_geometry_score: float = Field(default=0, ge=0, le=1)
    region_layout_scores: dict[str, float] = Field(default_factory=dict)
    service_grid_score: float = Field(default=0, ge=0, le=1)
    high_value_anchor_score: float = Field(default=0, ge=0, le=1)
    spatial_relationship_score: float = Field(default=0, ge=0, le=1)
    template_registration_score: float | None = Field(default=None, ge=0, le=1)
    repeating_row_score: float = Field(default=0, ge=0, le=1)
    contradiction_codes: tuple[str, ...] = ()
    visual_probability: float | None = Field(default=None, ge=0, le=1)
    template_version: str | None = None


def evidence_from_router_features(candidate_family: DocumentClass, feature_bundle,
                                  routing_evidence, template_registration_score: float | None = None,
                                  template_version: str | None = None) -> StandardFormEvidence:
    family = candidate_family.value
    structure = routing_evidence.standard_structure
    geometry = routing_evidence.anchor_geometry_score.get(family, 0.0)
    anchors = routing_evidence.weighted_anchor_coverage.get(family, 0.0)
    base = structure.get(family, 0.0)
    regions = ({"patient_insured": anchors, "claim_information": anchors,
                "diagnosis": geometry, "provider_billing": geometry}
               if candidate_family == DocumentClass.CMS1500 else
               {"institutional_grid": base, "type_of_bill": anchors,
                "statement_covers": anchors, "payer_provider": geometry,
                "diagnosis": geometry, "revenue_service": structure.get("service_table_score", 0.0)})
    return StandardFormEvidence(candidate_family=candidate_family,
        page_geometry_score=structure.get("aspect_score", 0.0), region_layout_scores=regions,
        service_grid_score=(base if candidate_family == DocumentClass.CMS1500
                            else structure.get("service_table_score", 0.0)),
        high_value_anchor_score=anchors, spatial_relationship_score=geometry,
        template_registration_score=template_registration_score,
        repeating_row_score=structure.get("v4_service_table_repetition", 0.0),
        template_version=template_version)
