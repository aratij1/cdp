"""Attribute isolated REM-01/02 recoveries, costs and pre-scoring failure conditions."""
from __future__ import annotations
import json,statistics
from pathlib import Path
from PIL import Image
from packages.document_routing import detect_content_bounds
ROOT=Path(__file__).resolve().parents[1]; BASE=ROOT/"evaluation_results/router_v4"
def load(label):return {x["document_id"]:x for x in (json.loads(v) for v in (BASE/f"remediation_01_{label}.jsonl").read_text("utf-8").splitlines())}
def percentile(v,p):return sorted(v)[max(0,int(len(v)*p)-1)]
def metrics(rows):
    values=list(rows.values());families={}
    for family in ("CMS1500","UB04","UNKNOWN_STRUCTURED","NON_CLAIM"):
      truth=[x for x in values if x["truth"]==family];pred=[x for x in values if x["predicted"]==family];tp=sum(x["truth"]==family and x["predicted"]==family for x in values)
      families[family]={"recall":tp/len(truth) if truth else None,"precision":tp/len(pred) if pred else None}
    return {"accuracy":sum(x["truth"]==x["predicted"] for x in values)/len(values),"families":families,"p50_ms":statistics.median(x["routing_latency_ms"] for x in values),"p95_ms":percentile([x["routing_latency_ms"] for x in values],.95),"false_standard_routes":sum(x["truth"] not in {"CMS1500","UB04"} and x["predicted"] in {"CMS1500","UB04"} for x in values)}
def analyze():
    before=load("before_rem01_rem02"); experiments={"REM-01":load("rem01"),"REM-02":load("rem02")}; bm=metrics(before); out={"baseline":bm,"experiments":{}}
    recoveries={}
    for name,rows in experiments.items():
      current=metrics(rows); recovered={k for k,x in rows.items() if before[k]["truth"]!=before[k]["predicted"] and x["truth"]==x["predicted"]};false={k for k,x in rows.items() if before[k]["truth"]==before[k]["predicted"] and x["truth"]!=x["predicted"]};recoveries[name]=recovered
      profiles=[x["experiment_stage_latency_ms"] for x in rows.values()]
      cms_gain=current["families"]["CMS1500"]["recall"]-bm["families"]["CMS1500"]["recall"];ub_gain=current["families"]["UB04"]["recall"]-bm["families"]["UB04"]["recall"]
      gate=(cms_gain>=.10 and ub_gain>=.10 and current["false_standard_routes"]==0 and all((current["families"][f]["precision"] or 0)>=.99 for f in ("CMS1500","UB04")) and (current["p95_ms"]<=1250 or current["p95_ms"]<=bm["p95_ms"]*1.2))
      out["experiments"][name]={"feature_family":"CONTENT_BOUND_GEOMETRY" if name=="REM-01" else "TOKEN_GROUP_ANCHOR","metrics":current,"CMS_recall_gain":cms_gain,"UB_recall_gain":ub_gain,"true_recoveries":len(recovered),"false_recoveries":len(false),"recovered_document_ids":sorted(recovered),"lost_document_ids":sorted(false),"stage_latency_ms":{"mean":{k:statistics.mean(x[k] for x in profiles) for k in profiles[0]},"p95":{k:percentile([x[k] for x in profiles],.95) for k in profiles[0]}},"accuracy_gain_per_100ms_p95":((current["accuracy"]-bm["accuracy"])/max(current["p95_ms"]-bm["p95_ms"],1)*100),"promotion_gate_pass":gate,"decision":"PROMOTE" if gate else "REJECT"}
    out["overlap"]={"unique_REM_01":len(recoveries["REM-01"]-recoveries["REM-02"]),"unique_REM_02":len(recoveries["REM-02"]-recoveries["REM-01"]),"overlapping_recoveries":len(recoveries["REM-01"]&recoveries["REM-02"])}
    manifest=json.loads((BASE/"remediation_01/manifest.json").read_text("utf-8"));byid={x["document_id"]:x for x in manifest["documents"]};misses=[]
    for key,x in before.items():
      if x["truth"] not in {"CMS1500","UB04"} or x["truth"]==x["predicted"]:continue
      item=byid[key];image=Image.open(BASE/"remediation_01"/item["file"]);g=detect_content_bounds(image);area=g.effective_width*g.effective_height/(image.width*image.height)
      misses.append({"document_id":key,"truth":x["truth"],"useful_text_present":x["observation"]["ocr_token_count"]>=3,"major_form_lines_detected":x["decision"]["grid_score"]>=.15,"form_content_box_plausible":.35<=area<=.98,"normalized_coordinate_contract_valid":g.effective_width>0 and g.effective_height>0,"correct_candidate_eligible":x["decision"]["eligibility"].get(x["truth"],False)})
    out["pre_scoring_diagnostic"]={k:sum(x[k] for x in misses)/len(misses) for k in ("useful_text_present","major_form_lines_detected","form_content_box_plausible","normalized_coordinate_contract_valid","correct_candidate_eligible")};out["pre_scoring_diagnostic"]["standard_miss_count"]=len(misses)
    target=BASE/"remediation_attribution.json";target.write_text(json.dumps(out,indent=2),"utf-8");return out
if __name__=="__main__":print(json.dumps(analyze(),indent=2))
