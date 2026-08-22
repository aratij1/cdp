"""Inspectable standard candidate admission; eligibility is never route acceptance."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml
from pydantic import Field
from packages.domain.common import DomainModel
from .router import RoutingEvidence

DEFAULT=Path(__file__).resolve().parents[2]/"config/router_v4_eligibility.yaml"
CLASSES={"identity":"IDENTITY","semantic":"SEMANTIC","structure":"STRUCTURAL","spatial":"SPATIAL","template":"TEMPLATE","service_table":"SERVICE_TABLE","combination":"SEMANTIC"}
class StandardEligibilityEvidence(DomainModel):
    family:str;eligible:bool;eligibility_paths_passed:list[str]=Field(default_factory=list);eligibility_paths_failed:list[str]=Field(default_factory=list)
    identity_evidence:float;anchor_evidence:float;geometry_evidence:float;structure_evidence:float;template_evidence:float;combination_evidence:float;service_table_evidence:float
    independent_evidence_classes:list[str]=Field(default_factory=list);primary_rejection_reason:str|None=None;secondary_rejection_reasons:list[str]=Field(default_factory=list)
    evidence_completeness:float;router_version:str="4.0-dev";config_version:str="rem03a-development-v1";path_details:dict[str,Any]=Field(default_factory=dict)
def load_config(path=DEFAULT):return yaml.safe_load(Path(path).read_text("utf-8"))
def _reason(name,observed,required):
    return {"identity":"IDENTITY_REQUIRED","semantic":"WEIGHTED_ANCHOR_MIN_NOT_MET","structure":"STRUCTURE_MIN_NOT_MET","spatial":"GEOMETRY_MIN_NOT_MET","template":"TEMPLATE_MIN_NOT_MET","service_table":"SERVICE_TABLE_MIN_NOT_MET","combination":"COMBINATION_REQUIRED"}.get(name,"OTHER")
def evaluate_standard_eligibility(decision:RoutingEvidence,family:str,*,stage:int=5,config=None)->StandardEligibilityEvidence:
    config=config or load_config(); combinations=[x["combination_score"] for x in decision.anchor_combinations if x["family"]==family]
    values={"identity":float(bool(decision.matched_anchors.get(f"{family}_IDENTITY"))),"semantic":decision.weighted_anchor_coverage.get(family,0),"spatial":decision.anchor_geometry_score.get(family,0),"structure":decision.standard_structure.get(family,0),"template":decision.standard_structure.get("template_similarity",0),"combination":max(combinations,default=0),"service_table":decision.standard_structure.get("service_table_score",0) if family=="UB04" else 0}
    order=["identity_confirmed","semantic_structural_spatial"]
    if family=="UB04":order.append("institutional")
    order.append("structure_dominant")
    if stage<2:allowed=[]
    elif stage==2:allowed=["identity_confirmed"]
    elif stage==3:allowed=["identity_confirmed","semantic_structural_spatial"]
    elif stage==4:allowed=["identity_confirmed","semantic_structural_spatial"]+(["institutional"] if family=="UB04" else [])
    else:allowed=order
    details={};passed=[];reasons=[];active_classes=set()
    for path in order:
      policy=config["paths"][family][path];conditions={}
      for key,required in policy.items():
        if key=="minimum_classes":continue
        observed=values["structure"] if key=="support_structure" else values[key];conditions[key]={"observed_value":observed,"required_value":required,"absolute_gap":observed-required,"relative_gap":((observed-required)/required if required else None),"passed":observed>=required}
      classes={CLASSES.get(k,k) for k,v in conditions.items() if v["passed"]}
      ok=path in allowed and all(v["passed"] for v in conditions.values()) and len(classes)>=policy["minimum_classes"]
      details[path]={"enabled_in_stage":path in allowed,"conditions":conditions,"independent_evidence_classes":sorted(classes),"passed":ok}
      if ok:passed.append(path);active_classes|=classes
      else:
        for key,value in conditions.items():
          if not value["passed"]:reasons.append(_reason(key,value["observed_value"],value["required_value"]))
        if len(classes)<policy["minimum_classes"]:reasons.append("INSUFFICIENT_INDEPENDENT_EVIDENCE")
    reasons=list(dict.fromkeys(reasons)) or ["OTHER"]
    return StandardEligibilityEvidence(family=family,eligible=bool(passed),eligibility_paths_passed=passed,eligibility_paths_failed=[x for x in order if x not in passed],
      identity_evidence=values["identity"],anchor_evidence=values["semantic"],geometry_evidence=values["spatial"],structure_evidence=values["structure"],template_evidence=values["template"],combination_evidence=values["combination"],service_table_evidence=values["service_table"],independent_evidence_classes=sorted(active_classes),primary_rejection_reason=None if passed else reasons[0],secondary_rejection_reasons=[] if passed else reasons[1:],evidence_completeness=sum(v>0 for v in values.values())/len(values),router_version=decision.router_version,config_version=config["config_version"],path_details=details)
