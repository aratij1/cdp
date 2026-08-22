"""PHI-safe fixed-order ML contract derived from canonical routing evidence."""
from __future__ import annotations
from pydantic import BaseModel
from packages.document_routing.router import RoutingEvidence
FEATURE_SCHEMA_VERSION="ml-eligibility-features-v1"
class MLEligibilityFeatures(BaseModel):
    page_aspect_ratio:float;content_aspect_ratio:float;estimated_dpi:float;ocr_token_count:float;ocr_line_count:float;ocr_character_count:float;healthcare_token_density:float
    cms_identity_score:float;cms_anchor_score:float;cms_weighted_anchor_score:float;cms_structure_score:float;cms_geometry_score:float;cms_template_score:float;cms_combination_score:float
    ub_identity_score:float;ub_anchor_score:float;ub_weighted_anchor_score:float;ub_structure_score:float;ub_geometry_score:float;ub_template_score:float;ub_service_table_score:float;ub_combination_score:float
    horizontal_line_density:float;vertical_line_density:float;grid_density:float;service_row_repetition:float;claim_semantic_density:float;structured_score:float;unstructured_score:float;non_claim_score:float
FEATURE_NAMES=list(MLEligibilityFeatures.model_fields)
def features_from_evidence(decision:RoutingEvidence,observation:dict)->MLEligibilityFeatures:
    family=observation.get("family_evidence",{});cms=family.get("CMS1500",{});ub=family.get("UB04",{})
    combo=lambda f:max((x["combination_score"] for x in decision.anchor_combinations if x["family"]==f),default=0)
    return MLEligibilityFeatures(page_aspect_ratio=observation["aspect_ratio"],content_aspect_ratio=observation["aspect_ratio"],estimated_dpi=observation.get("estimated_dpi") or 200,
      ocr_token_count=observation.get("ocr_token_count") or 0,ocr_line_count=observation.get("ocr_line_count") or 0,ocr_character_count=observation.get("ocr_character_count") or 0,healthcare_token_density=observation.get("healthcare_token_density") or 0,
      cms_identity_score=float(bool(decision.matched_anchors.get("CMS1500_IDENTITY"))),cms_anchor_score=len(decision.matched_anchors.get("CMS1500",[])),cms_weighted_anchor_score=decision.weighted_anchor_coverage.get("CMS1500",0),cms_structure_score=decision.standard_structure.get("CMS1500",0),cms_geometry_score=decision.anchor_geometry_score.get("CMS1500",0),cms_template_score=decision.standard_structure.get("template_similarity",0),cms_combination_score=combo("CMS1500"),
      ub_identity_score=float(bool(decision.matched_anchors.get("UB04_IDENTITY"))),ub_anchor_score=len(decision.matched_anchors.get("UB04",[])),ub_weighted_anchor_score=decision.weighted_anchor_coverage.get("UB04",0),ub_structure_score=decision.standard_structure.get("UB04",0),ub_geometry_score=decision.anchor_geometry_score.get("UB04",0),ub_template_score=decision.standard_structure.get("template_similarity",0),ub_service_table_score=decision.standard_structure.get("service_table_score",0),ub_combination_score=combo("UB04"),
      horizontal_line_density=decision.horizontal_line_score,vertical_line_density=decision.vertical_line_score,grid_density=decision.grid_score,service_row_repetition=decision.standard_structure.get("service_table_score",0),claim_semantic_density=decision.healthcare_label_density,structured_score=decision.scores["UNKNOWN_STRUCTURED"],unstructured_score=decision.scores["UNKNOWN_UNSTRUCTURED"],non_claim_score=decision.scores["NON_CLAIM"])
