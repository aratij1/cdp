"""PHI-safe canonical observation contract for routing drift analysis."""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field

from packages.document_routing.router import RoutingEvidence
from packages.domain.common import DomainModel


class RouterObservation(DomainModel):
    observation_schema_version:str="1.0"
    document_id:str
    truth_family:str|None=None
    predicted_route:str
    page_width:int
    page_height:int
    aspect_ratio:float
    estimated_dpi:float|None=None
    image_quality_bucket:str|None=None
    ocr_latency_ms:float|None=None
    ocr_token_count:int|None=None
    ocr_line_count:int|None=None
    ocr_character_count:int|None=None
    healthcare_token_count:int|None=None
    healthcare_token_density:float|None=None
    family_evidence:dict[str,dict[str,Any]]
    structured_score:float
    unstructured_score:float
    non_claim_score:float
    winner:str
    runner_up:str
    margin:float
    decision_reason_codes:list[str]
    routing_stage_reached:str
    stage_latency_ms:dict[str,float|None]
    ocr_calls_page:int=1
    regions_ocred:int=0
    fallback_count:int=0
    cache_hit_rate:float=0.0
    retry_count:int=0
    family_eligibility:dict[str,dict[str,Any]]=Field(default_factory=dict)


def build_router_observation(*,document_id:str,image,lines,decision:RoutingEvidence,
        truth_family:str|None=None,image_quality_bucket:str|None=None,
        ocr_latency_ms:float|None=None,stage_latency_ms:dict[str,float|None]|None=None)->RouterObservation:
    tokens=[token for line in lines for token in re.findall(r"[A-Za-z0-9]+",line.text)]
    healthcare={"patient","member","provider","diagnosis","procedure","service","npi","charge","claim","hcpcs"}
    health=sum(token.casefold() in healthcare for token in tokens)
    ranked=sorted(decision.scores,key=decision.scores.get,reverse=True)
    family={}
    for name in ("CMS1500","UB04"):
        combinations=[x["combination_score"] for x in decision.anchor_combinations if x["family"]==name]
        family[name]={"identity_score":float(bool(decision.matched_anchors.get(f"{name}_IDENTITY"))),
            "anchor_score":len(decision.matched_anchors.get(name,[])),
            "weighted_anchor_coverage":decision.weighted_anchor_coverage.get(name,0.0),
            "geometry_score":decision.anchor_geometry_score.get(name,0.0),
            "structure_score":decision.standard_structure.get(name,0.0),
            "service_table_score":decision.standard_structure.get("service_table_score",0.0) if name=="UB04" else 0.0,
            "template_score":decision.standard_structure.get("template_similarity",0.0),
            "combination_score":max(combinations,default=0.0),"final_score":decision.scores[name],
            "eligible":decision.eligibility.get(name,False)}
    stages={"decode_ms":None,"image_features_ms":None,"structure_ms":None,"template_ms":None,
        "sparse_ocr_ms":ocr_latency_ms,"anchor_matching_ms":None,"geometry_ms":None,
        "full_page_ocr_ms":ocr_latency_ms,"fallback_ms":0.0,"decision_ms":None,"total_ms":None,
        **(stage_latency_ms or {})}
    return RouterObservation(document_id=document_id,truth_family=truth_family,
        predicted_route=decision.route.value,page_width=image.width,page_height=image.height,
        aspect_ratio=image.width/max(image.height,1),image_quality_bucket=image_quality_bucket,
        ocr_latency_ms=ocr_latency_ms,ocr_token_count=len(tokens),ocr_line_count=len(lines),
        ocr_character_count=sum(len(line.text) for line in lines),healthcare_token_count=health,
        healthcare_token_density=health/max(len(tokens),1),family_evidence=family,
        structured_score=decision.scores["UNKNOWN_STRUCTURED"],
        unstructured_score=decision.scores["UNKNOWN_UNSTRUCTURED"],non_claim_score=decision.scores["NON_CLAIM"],
        winner=ranked[0],runner_up=ranked[1],margin=decision.scores[ranked[0]]-decision.scores[ranked[1]],
        decision_reason_codes=decision.reason_codes,routing_stage_reached="CANONICAL_DECISION",
        stage_latency_ms=stages,family_eligibility=decision.family_eligibility)
