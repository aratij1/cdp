"""Feature drift and failure taxonomy from frozen V3 and observed regression outputs."""

from __future__ import annotations

import json, math, statistics
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from evaluation.audit_production_holdout_v2 import DEFAULT_DATASET
from evaluation.run_production_holdout_v2 import TRUTH_ROUTE

ROOT=Path(__file__).resolve().parents[1]
DEV=ROOT/"evaluation_results/ROUTING_DEV_V3/benchmark.json"
REP=ROOT/"evaluation_results/PRODUCTION_REPRESENTATIVE_V2_ROUTER_V3_OBSERVATION/predictions.json"
OUTPUT=ROOT/"evaluation_results/ROUTER_V4_DOMAIN_SHIFT"


def _pct(values,p):
    if not values:return None
    return sorted(values)[max(0,math.ceil(p*len(values))-1)]
def _summary(values):
    values=[float(x) for x in values if x is not None]
    if not values:return {"mean":None,"median":None,"p10":None,"p90":None,"zero_frequency":None}
    return {"mean":statistics.fmean(values),"median":statistics.median(values),
        "p10":_pct(values,.1),"p90":_pct(values,.9),"zero_frequency":sum(x==0 for x in values)/len(values)}
def _effect(a,b):
    if len(a)<2 or len(b)<2:return None
    pooled=math.sqrt(((len(a)-1)*statistics.variance(a)+(len(b)-1)*statistics.variance(b))/(len(a)+len(b)-2))
    return (statistics.fmean(b)-statistics.fmean(a))/pooled if pooled else None
def _features(decision):
    return {"cms_identity":float(bool(decision["matched_anchors"].get("CMS1500_IDENTITY"))),
        "cms_weighted":decision["weighted_anchor_coverage"].get("CMS1500",0),
        "cms_geometry":decision["anchor_geometry_score"].get("CMS1500",0),
        "cms_structure":decision["standard_structure"].get("CMS1500",0),
        "cms_score":decision["scores"]["CMS1500"],
        "ub_identity":float(bool(decision["matched_anchors"].get("UB04_IDENTITY"))),
        "ub_weighted":decision["weighted_anchor_coverage"].get("UB04",0),
        "ub_geometry":decision["anchor_geometry_score"].get("UB04",0),
        "ub_structure":decision["standard_structure"].get("UB04",0),
        "ub_service_table":decision["standard_structure"].get("service_table_score",0),
        "ub_score":decision["scores"]["UB04"],"structured_score":decision["scores"]["UNKNOWN_STRUCTURED"],
        "unstructured_score":decision["scores"]["UNKNOWN_UNSTRUCTURED"],
        "non_claim_score":decision["scores"]["NON_CLAIM"],"grid_score":decision["grid_score"],
        "horizontal_score":decision["horizontal_line_score"],"vertical_score":decision["vertical_line_score"],
        "margin":decision["margin"]}
def _failure(truth,decision):
    family="CMS1500" if truth=="CMS1500" else "UB04" if truth=="UB04" else None
    if family:
        if not decision["matched_anchors"].get(f"{family}_IDENTITY"):return "IDENTITY_ANCHOR_MISS"
        if decision["weighted_anchor_coverage"].get(family,0)==0:return "ANCHOR_MATCH_FAILURE"
        if decision["anchor_geometry_score"].get(family,0)<.45:return "ZONE_MISMATCH"
        if decision["standard_structure"].get(family,0)<.35:return "STRUCTURE_SCORE_COLLAPSE"
        if family=="UB04" and decision["standard_structure"].get("service_table_score",0)<.35:return "SERVICE_TABLE_NOT_DETECTED"
        if not decision["eligibility"].get(family):return "SCORE_CALIBRATION_SHIFT"
        return "MARGIN_FAILURE"
    if truth=="UNKNOWN_STRUCTURED":return "CUSTOM_STRUCTURE_NOT_DETECTED"
    if truth=="NON_CLAIM":return "NON_CLAIM_PRIOR_FAILURE"
    return "OTHER"


def analyze():
    dev=json.loads(DEV.read_text("utf-8"))["details"]
    rep=json.loads(REP.read_text("utf-8"))
    metadata={x["document_id"]:x for x in (json.loads(line) for line in
        (DEFAULT_DATASET/"metadata/document_metadata.jsonl").read_text("utf-8").splitlines())}
    dev_rows=[{"source":"DEV","truth":x["truth_route"],"predicted":x["predicted_route"],
               "features":_features(x["decision"])} for x in dev]
    rep_rows=[]; failures=[]
    for x in rep:
        truth=TRUTH_ROUTE[metadata[x["document_id"]]["family"]]; decision=x["route_decision"]
        row={"source":"REPRESENTATIVE_OBSERVED","document_id":x["document_id"],"truth":truth,
             "predicted":x["predicted_route"],"quality":metadata[x["document_id"]]["quality_bucket"],
             "routing_seconds":x["routing_seconds"],"features":_features(decision)}
        rep_rows.append(row)
        if truth!=x["predicted_route"]:
            failures.append({"document_id":x["document_id"],"truth_family":truth,
                "predicted_route":x["predicted_route"],"quality_bucket":row["quality"],
                "category":_failure(truth,decision),"reason_codes":decision["reason_codes"]})
    comparisons={}
    family_map={"CMS1500":"CMS1500","UB04":"UB04","UNKNOWN_STRUCTURED":"UNKNOWN_STRUCTURED","NON_CLAIM":"NON_CLAIM"}
    for label,truth in family_map.items():
        a=[x for x in dev_rows if x["truth"]==truth]; b=[x for x in rep_rows if x["truth"]==truth]
        comparisons[label]={}
        for feature in next(iter(a or b))["features"]:
            av=[x["features"][feature] for x in a]; bv=[x["features"][feature] for x in b]
            sa,sb=_summary(av),_summary(bv); delta=(sb["mean"]-sa["mean"]) if sa["mean"] is not None and sb["mean"] is not None else None
            comparisons[label][feature]={"dev":sa,"representative":sb,"absolute_delta":delta,
                "relative_delta":delta/abs(sa["mean"]) if delta is not None and sa["mean"] else None,
                "effect_size":_effect(av,bv)}
    pareto=Counter(x["category"] for x in failures)
    report={"evidence_class":"DIAGNOSTIC_ONLY_OBSERVED_REPRESENTATIVE","tuning_permitted":False,
        "comparisons":comparisons,"failure_pareto":dict(pareto.most_common()),
        "meaningful_classification_rate":sum(x["category"]!="OTHER" for x in failures)/len(failures),
        "failure_count":len(failures),"attachment_success":{"correct":sum(x["truth"]=="UNKNOWN_UNSTRUCTURED" and x["predicted"]==x["truth"] for x in rep_rows),
            "total":sum(x["truth"]=="UNKNOWN_UNSTRUCTURED" for x in rep_rows),
            "invariant":"Fail-safe unstructured fallback requires no brittle positive standard/custom/non-claim evidence."},
        "latency":{"development_p95_seconds":json.loads(DEV.read_text("utf-8"))["latency"]["p95"],
            "representative_p95_seconds":_pct([x["routing_seconds"] for x in rep_rows],.95),
            "historical_stage_limit":"The frozen run retained total routing time only; stage-level schema is now implemented for V4."}}
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/"report.json").write_text(json.dumps(report,indent=2),"utf-8")
    (OUTPUT/"failures.json").write_text(json.dumps(failures,indent=2),"utf-8")
    return report


if __name__=="__main__":
    value=analyze(); print(json.dumps({k:v for k,v in value.items() if k!="comparisons"},indent=2))
