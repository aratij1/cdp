"""Invariant-based Router V4. Evaluation-only until an independent holdout passes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time

import yaml
from PIL import Image

from .router import MultiSignalRoute, MultiSignalRouter, RoutingEvidence, TextGeometry
from .structural import StructuralDescriptors, describe_structure
from .features import RouterFeatureBundle, build_router_feature_bundle
from .eligibility import evaluate_standard_eligibility

DEFAULT_V4_CONFIG=Path(__file__).resolve().parents[2]/"config/document_routing_v4.yaml"


@dataclass(frozen=True)
class StructuredDocumentEvidence:
    label_value_density: float
    alignment_regularity: float
    form_box_density: float
    table_presence: float
    repeated_rows: float
    date_density: float
    identifier_density: float
    currency_density: float
    healthcare_concept_density: float
    spatial_regularity: float
    final_score: float


def _structured_evidence(lines: list[TextGeometry], descriptor: StructuralDescriptors,
                         healthcare_density: float) -> StructuredDocumentEvidence:
    text=" ".join(x.text for x in lines)
    n=max(len(lines),1)
    labels=sum(":" in x.text or x.text.strip().isupper() for x in lines)/n
    dates=len(re.findall(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b",text))/n
    ids=len(re.findall(r"\b[A-Z]*\d{5,}\b",text,re.I))/n
    money=len(re.findall(r"(?:\$|\bUSD\b)?\s*\d+[.,]\d{2}\b",text,re.I))/n
    xs=[round(x.x0/max(1,max(y.x1 for y in lines)),1) for x in lines] if lines else []
    alignment=max((xs.count(x) for x in set(xs)),default=0)/n
    box=min(1.0,sum(descriptor.box_density_map[1:])/2)
    table=min(1.0,(sum(descriptor.grid_density_map)/len(descriptor.grid_density_map))*20)
    spatial=min(1.0,.55*alignment+.45*labels)
    final=min(1.0,.22*labels+.16*alignment+.14*box+.14*table+.12*descriptor.service_table_repetition
              +.05*min(1,dates*8)+.05*min(1,ids*8)+.04*min(1,money*8)+.08*healthcare_density)
    return StructuredDocumentEvidence(labels,alignment,box,table,descriptor.service_table_repetition,
        min(1,dates*8),min(1,ids*8),min(1,money*8),healthcare_density,spatial,final)


class InvariantRouterV4:
    """Balances independent semantic, spatial, and structural signals."""
    def __init__(self, config: dict, semantic_router: MultiSignalRouter | None = None):
        self.config=config; self.semantic_router=semantic_router or MultiSignalRouter.load(); self.last_profile={}
    @classmethod
    def load(cls,path: str|Path=DEFAULT_V4_CONFIG) -> "InvariantRouterV4":
        return cls(yaml.safe_load(Path(path).read_text("utf-8")))

    def route(self,image: Image.Image,lines: list[TextGeometry]) -> RoutingEvidence:
        total_start=time.perf_counter()
        use_geometry=self.config.get("experiments",{}).get("rem01_content_geometry",False)
        use_tokens=self.config.get("experiments",{}).get("rem02_token_groups",False)
        feature_start=time.perf_counter(); bundle=build_router_feature_bundle(image,lines) if (use_geometry or use_tokens) else None
        feature_ms=(time.perf_counter()-feature_start)*1000
        base_image=bundle.content_image if use_geometry else image
        base_lines=(list(bundle.enriched_lines if use_tokens else bundle.virtual_lines) if use_geometry
                    else list(bundle.enriched_original_lines) if use_tokens else lines)
        semantic_start=time.perf_counter(); base=self.semantic_router.route(base_image,base_lines); semantic_ms=(time.perf_counter()-semantic_start)*1000
        d=bundle.structural if use_geometry else describe_structure(image)
        scoring_start=time.perf_counter()
        structured=_structured_evidence(base_lines,d,base.healthcare_label_density)
        # Family-specific normalized structure: UB needs repeated table/grid; CMS is banded but less repetitive.
        grid=min(1.0,sum(d.grid_density_map)/len(d.grid_density_map)*20)
        structure_image=bundle.content_image if use_geometry else image
        cms_structure=min(1.0,.45*grid+.30*(1-abs(structure_image.width/max(structure_image.height,1)-.77))+.25*(1-d.service_table_repetition))
        ub_structure=min(1.0,.38*grid+.42*d.service_table_repetition+.20*base.standard_structure.get("vertical_line_score",0))
        w=self.config["standard_weights"]
        scores=dict(base.scores)
        for family,structure in (("CMS1500",cms_structure),("UB04",ub_structure)):
            identity=float(bool(base.matched_anchors.get(f"{family}_IDENTITY")))
            semantic=base.weighted_anchor_coverage.get(family,0)
            spatial=base.anchor_geometry_score.get(family,0)
            scores[family]=min(1.0,w["semantic"]*semantic+w["spatial"]*spatial+w["structural"]*structure+w["identity_bonus"]*identity)
        standard=sorted(((x,scores[x]) for x in ("CMS1500","UB04")),key=lambda x:x[1],reverse=True)
        rem03a=self.config.get("experiments",{}).get("enable_rem03a_eligibility",False)
        eligibility_stage=int(self.config.get("experiments",{}).get("rem03a_stage",1)) if rem03a else 1
        family_eligibility=({family:evaluate_standard_eligibility(base,family,stage=eligibility_stage).model_dump(mode="json") for family in ("CMS1500","UB04")} if rem03a else {})
        claim=max(scores["CMS1500"],scores["UB04"],structured.healthcare_concept_density)
        negative=len(base.matched_anchors.get("negative",[]))
        nonclaim_eligible=(negative>=self.config["two_sided_non_claim"]["minimum_negative_anchors"] and
            claim<=self.config["two_sided_non_claim"]["maximum_claim_evidence"])
        eligibility={"CMS1500":False,"UB04":False}
        if standard[0][1]>=self.config["minimum_standard_score"] and standard[0][1]-standard[1][1]>=self.config["minimum_standard_margin"]:
            route=MultiSignalRoute(standard[0][0]); eligibility[standard[0][0]]=True
            reasons=["ROUTER_V4_INVARIANT_STANDARD","THREE_EVIDENCE_FAMILIES",f"BEST:{route.value}"]
            if use_tokens and bundle and bundle.token_group_matches: reasons.append("TOKEN_GROUP_ANCHOR_RECOVERY")
        elif nonclaim_eligible and base.scores["NON_CLAIM"]>=self.config["minimum_non_claim_score"]:
            route=MultiSignalRoute.NON_CLAIM; reasons=["ROUTER_V4_TWO_SIDED_NON_CLAIM"]
        elif structured.final_score>=self.config["minimum_custom_score"]:
            route=MultiSignalRoute.UNKNOWN_STRUCTURED; reasons=["ROUTER_V4_STRUCTURED_DOCUMENT_EVIDENCE"]
        else:
            route=MultiSignalRoute.UNKNOWN_UNSTRUCTURED; reasons=["ROUTER_V4_SAFE_UNSTRUCTURED_FALLBACK"]
        scores["UNKNOWN_STRUCTURED"]=structured.final_score
        ranked=sorted(scores.items(),key=lambda x:x[1],reverse=True)
        evidence=base.model_dump()
        evidence.update(route=route,confidence=scores[route.value],scores=scores,best_score=ranked[0][1],
            second_best_score=ranked[1][1],margin=ranked[0][1]-ranked[1][1],reason_codes=reasons,
            router_version=self.config["router_version"],eligibility=eligibility,family_eligibility=family_eligibility,
            standard_structure={**base.standard_structure,"CMS1500":cms_structure,"UB04":ub_structure,
                "v4_structured_score":structured.final_score,"v4_service_table_repetition":d.service_table_repetition})
        result=RoutingEvidence(**evidence)
        self.last_profile={"feature_bundle_ms":feature_ms,"semantic_anchor_ms":semantic_ms,
            "route_scoring_ms":(time.perf_counter()-scoring_start)*1000,"total_router_ms":(time.perf_counter()-total_start)*1000,
            "content_bound_geometry_enabled":use_geometry,"token_group_anchor_enabled":use_tokens,
            "token_group_match_count":len(bundle.token_group_matches) if bundle else 0}
        return result
