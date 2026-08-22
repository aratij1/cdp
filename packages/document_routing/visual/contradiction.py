"""Evidence-only veto over existing features; performs no OCR, CV or routing finalization."""
from __future__ import annotations
import math
from pydantic import BaseModel,Field
from packages.document_routing.router import RoutingEvidence
from .contracts import VisualRouteEvidence
class StandardContradictionEvidence(BaseModel):
    proposed_family:str;visual_probability:float;visual_margin:float;visual_entropy:float
    contradiction_detected:bool;contradiction_strength:float;contradiction_classes:list[str]=Field(default_factory=list)
    supporting_evidence:dict[str,float]=Field(default_factory=dict);opposing_evidence:dict[str,float]=Field(default_factory=dict)
    reason_codes:list[str]=Field(default_factory=list);recommended_action:str;policy_version:str="visual-contradiction-v1"
class VisualContradictionService:
    def __init__(self,stage:int=2,low_margin:float=.20,high_entropy:float=.85):self.stage=stage;self.low_margin=low_margin;self.high_entropy=high_entropy
    def evaluate(self,evidence:list[VisualRouteEvidence],deterministic:RoutingEvidence)->StandardContradictionEvidence:
      p={x.family:x.probability for x in evidence};rank=sorted(p,key=p.get,reverse=True);proposed=rank[0];margin=p[rank[0]]-p[rank[1]];entropy=-sum(v*math.log(max(v,1e-12)) for v in p.values())
      if proposed not in {"CMS1500","UB04"}:return StandardContradictionEvidence(proposed_family=proposed,visual_probability=p[proposed],visual_margin=margin,visual_entropy=entropy,contradiction_detected=False,contradiction_strength=0,contradiction_classes=["NO_CONTRADICTION"],recommended_action="NON_STANDARD_VISUAL_EVIDENCE")
      other="CMS1500" if proposed=="UB04" else "UB04";s=deterministic.standard_structure;support={"structure":s.get(proposed,0),"geometry":deterministic.anchor_geometry_score.get(proposed,0),"anchors":deterministic.weighted_anchor_coverage.get(proposed,0),"service_table":s.get("service_table_score",0) if proposed=="UB04" else 0};opp={"structure":s.get(other,0),"geometry":deterministic.anchor_geometry_score.get(other,0),"anchors":deterministic.weighted_anchor_coverage.get(other,0)}
      classes=[]
      if self.stage>=2 and proposed=="UB04" and support["structure"]<.70 and support["service_table"]<.20:classes += ["STRUCTURAL_CONTRADICTION","SERVICE_TABLE_CONTRADICTION"]
      if self.stage>=2 and proposed=="CMS1500" and s.get("UB04",0)>=.82 and s.get("service_table_score",0)>=.25:classes += ["STRUCTURAL_CONTRADICTION","SERVICE_TABLE_CONTRADICTION"]
      if self.stage>=3 and opp["structure"]>=support["structure"]+.05:classes.append("OPPOSING_STANDARD_EVIDENCE")
      if self.stage>=4 and opp["anchors"]>=.30 and support["anchors"]<.05:classes.append("SEMANTIC_CONTRADICTION")
      if self.stage>=4 and opp["geometry"]>=.35 and support["geometry"]<.05:classes.append("SPATIAL_CONTRADICTION")
      if self.stage>=5 and margin<self.low_margin:classes.append("VISUAL_LOW_MARGIN")
      if self.stage>=5 and entropy>self.high_entropy:classes.append("VISUAL_HIGH_ENTROPY")
      strong=len(set(classes)&{"STRUCTURAL_CONTRADICTION","SERVICE_TABLE_CONTRADICTION","OPPOSING_STANDARD_EVIDENCE","SEMANTIC_CONTRADICTION","SPATIAL_CONTRADICTION"})>=2 or (self.stage>=5 and "VISUAL_LOW_MARGIN" in classes and "VISUAL_HIGH_ENTROPY" in classes)
      return StandardContradictionEvidence(proposed_family=proposed,visual_probability=p[proposed],visual_margin=margin,visual_entropy=entropy,contradiction_detected=strong,contradiction_strength=min(1,len(set(classes))/3),contradiction_classes=classes or ["NO_CONTRADICTION"],supporting_evidence=support,opposing_evidence=opp,reason_codes=["STRONG_INDEPENDENT_CONTRADICTION"] if strong else ["VISUAL_STANDARD_NOT_CONTRADICTED"],recommended_action="STANDARD_AMBIGUOUS" if strong else "VISUAL_STANDARD_NOT_CONTRADICTED")
