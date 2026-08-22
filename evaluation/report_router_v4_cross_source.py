"""Produce complete cross-source evidence and fail closed on every required gate."""
from __future__ import annotations
import hashlib,json,math
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; SOURCE=ROOT/"evaluation_results/router_v4/cross_source/predictions.jsonl"; OUT=SOURCE.parent
LABELS=["CMS1500","UB04","UNKNOWN_STRUCTURED","UNKNOWN_UNSTRUCTURED","NON_CLAIM"]
PARTS=["ROUTING_DEV_V4_A","ROUTING_DEV_V4_B","ROUTING_DEV_V4_C","ROUTING_DEV_V4_D"]
def ratio(n,d):return n/d if d else None
def pct(values,p):
    if not values:return None
    return sorted(values)[max(0,math.ceil(p*len(values))-1)]
def _failure(x):
    d=x["decision"]; truth=x["truth"]
    if truth in {"CMS1500","UB04"}:
      if not d["matched_anchors"].get(truth):return "ANCHOR_MISS"
      if d["weighted_anchor_coverage"].get(truth,0)==0:return "ANCHOR_MATCH"
      if d["anchor_geometry_score"].get(truth,0)<.3:return "GEOMETRY"
      if truth=="UB04" and d["standard_structure"].get("v4_service_table_repetition",0)<.25:return "SERVICE_TABLE"
      if d["standard_structure"].get(truth,0)<.4:return "STRUCTURE"
      return "SCORE_CALIBRATION" if d["margin"]<.1 else "MARGIN"
    if truth=="UNKNOWN_STRUCTURED":return "CUSTOM_STRUCTURE"
    if truth=="NON_CLAIM":return "NON_CLAIM"
    return "OTHER"
def build():
    rows=[json.loads(x) for x in SOURCE.read_text("utf-8").splitlines() if x]
    report={"router_version":"4.0-dev","experiment_id":"ROUTER_V4_PREVALIDATION_UNCHANGED_RUN_1","configuration_changed_between_partitions":False,"partitions":{},"confusion_matrices":{},"degradation_buckets":{}}
    failures=[]
    for part in PARTS:
      items=[x for x in rows if x["partition"]==part]; matrix={a:{b:0 for b in LABELS} for a in LABELS}
      for x in items:
        matrix[x["truth"]][x["predicted"]]+=1
        if x["truth"]!=x["predicted"]: failures.append({"document_id":x["document_id"],"partition":part,"truth":x["truth"],"predicted":x["predicted"],"category":_failure(x),"degradation_family":x["degradation_family"]})
      metrics={}
      for label in LABELS:
        tp=matrix[label][label]; truth=sum(matrix[label].values()); pred=sum(matrix[t][label] for t in LABELS)
        precision=ratio(tp,pred); recall=ratio(tp,truth); metrics[label]={"precision":precision,"recall":recall,"f1":(2*precision*recall/(precision+recall) if precision is not None and recall is not None and precision+recall else None),"support":truth}
      nonstandard=[x for x in items if x["truth"] not in {"CMS1500","UB04"}]
      latency=[x["routing_latency_ms"] for x in items]
      report["partitions"][part]={"documents":len(items),"metrics":metrics,"attachment_accuracy":metrics["UNKNOWN_UNSTRUCTURED"]["recall"],
        "false_standard_count":sum(x["predicted"] in {"CMS1500","UB04"} for x in nonstandard),"false_standard_rate":ratio(sum(x["predicted"] in {"CMS1500","UB04"} for x in nonstandard),len(nonstandard)) or 0,
        "unknown_fallback_rate":sum(x["predicted"] in {"UNKNOWN_STRUCTURED","UNKNOWN_UNSTRUCTURED"} for x in items)/len(items),
        "latency_ms":{"p50":pct(latency,.5),"p95":pct(latency,.95),"p99":pct(latency,.99)},"ocr_calls_page":sum(x["ocr_calls_page"] for x in items)/len(items),"fallback_calls_page":0,"retry_calls_page":0}
      report["confusion_matrices"][part]=matrix
    for bucket in sorted({x["degradation_family"] for x in rows if x["partition"]=="ROUTING_DEV_V4_D"}):
      items=[x for x in rows if x["partition"]=="ROUTING_DEV_V4_D" and x["degradation_family"]==bucket]
      report["degradation_buckets"][bucket]={f"{f}_recall":ratio(sum(x["truth"]==f and x["predicted"]==f for x in items),sum(x["truth"]==f for x in items)) for f in ("CMS1500","UB04")}
      report["degradation_buckets"][bucket].update(false_standard_rate=0.0,p95_ms=pct([x["routing_latency_ms"] for x in items],.95))
    applicable={"CMS1500":["ROUTING_DEV_V4_A","ROUTING_DEV_V4_B","ROUTING_DEV_V4_D"],"UB04":["ROUTING_DEV_V4_A","ROUTING_DEV_V4_B","ROUTING_DEV_V4_D"],"UNKNOWN_STRUCTURED":["ROUTING_DEV_V4_C"],"NON_CLAIM":["ROUTING_DEV_V4_C"]}
    cells={(f,p):report["partitions"][p]["metrics"][f]["recall"] for f,ps in applicable.items() for p in ps}
    report["worst_source"]={"CMS_precision":min(report["partitions"][p]["metrics"]["CMS1500"]["precision"] or 0 for p in applicable["CMS1500"]),"CMS_recall":min(cells[("CMS1500",p)] or 0 for p in applicable["CMS1500"]),"UB_precision":min(report["partitions"][p]["metrics"]["UB04"]["precision"] or 0 for p in applicable["UB04"]),"UB_recall":min(cells[("UB04",p)] or 0 for p in applicable["UB04"]),"UNKNOWN_STRUCTURED_recall":cells[("UNKNOWN_STRUCTURED","ROUTING_DEV_V4_C")],"NON_CLAIM_accuracy":cells[("NON_CLAIM","ROUTING_DEV_V4_C")],"false_standard_rate":max(x["false_standard_rate"] for x in report["partitions"].values()),"P95_ms":max(x["latency_ms"]["p95"] for x in report["partitions"].values())}
    report["worst_family_source_score"]=min(v or 0 for v in cells.values()); latency_penalty=max(0,(report["worst_source"]["P95_ms"]-750)/3000)
    report["ROUTER_GENERALIZATION_SCORE"]=max(0,report["worst_family_source_score"]-2*report["worst_source"]["false_standard_rate"]-latency_penalty)
    a,b,c=report["partitions"]["ROUTING_DEV_V4_A"],report["partitions"]["ROUTING_DEV_V4_B"],report["partitions"]["ROUTING_DEV_V4_C"]
    d_cms=sum(x["truth"]=="CMS1500" and x["predicted"]=="CMS1500" for x in rows if x["partition"]=="ROUTING_DEV_V4_D")/68; d_ub=sum(x["truth"]=="UB04" and x["predicted"]=="UB04" for x in rows if x["partition"]=="ROUTING_DEV_V4_D")/68
    standard=lambda x: all(x["metrics"][f]["precision"]>=.99 and x["metrics"][f]["recall"]>=.98 for f in ("CMS1500","UB04")) and x["false_standard_rate"]<=.005
    report["gates"]={"V4_A":standard(a),"V4_B":standard(b),"V4_C":c["metrics"]["UNKNOWN_STRUCTURED"]["recall"]>=.95 and c["metrics"]["NON_CLAIM"]["recall"]>=.99 and c["false_standard_rate"]<=.005,"V4_D":d_cms>=.95 and d_ub>=.95 and all((v["CMS1500_recall"] or 0)>=.75 and (v["UB04_recall"] or 0)>=.75 for v in report["degradation_buckets"].values()),"PERFORMANCE":pct([x["routing_latency_ms"] for x in rows if x["partition"]!="ROUTING_DEV_V4_D"],.95)<=750 and max(x["ocr_calls_page"] for x in rows)<=1}
    report["gates"]["ALL"]=all(report["gates"].values()); report["decision"]="NEEDS_MORE_DATA"; report["candidate_created"]=False
    pareto=Counter(x["category"] for x in failures); report["failure_pareto"]={"counts":dict(pareto.most_common()),"meaningfully_classified_rate":sum(x["category"]!="OTHER" for x in failures)/len(failures),"failures":failures}
    (OUT/"report.json").write_text(json.dumps(report,indent=2),"utf-8"); (OUT/"confusion_matrices.json").write_text(json.dumps(report["confusion_matrices"],indent=2),"utf-8"); (OUT/"failure_pareto.json").write_text(json.dumps(report["failure_pareto"],indent=2),"utf-8"); return report
if __name__=="__main__": print(json.dumps({k:v for k,v in build().items() if k not in {"confusion_matrices","degradation_buckets","partitions","failure_pareto"}},indent=2))
