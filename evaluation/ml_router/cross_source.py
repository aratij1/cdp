"""Cross-renderer ML eligibility and deterministic-corroboration funnel."""
from __future__ import annotations
import json,statistics,time,yaml
from pathlib import Path
import numpy as np
from packages.document_routing import RoutingEvidence,evaluate_standard_eligibility
from packages.document_routing.eligibility_fusion import EligibilityFusionService
from packages.document_routing.ml import MLEligibilityFeatures,MLEligibilityInference
from evaluation.ml_router.train import CLASSES,DATA,rows
ROOT=Path(__file__).resolve().parents[2];BASE=ROOT/"evaluation_results/router_v4/remediation_01_before_rem01_rem02.jsonl";OUT=DATA/"cross_source_funnel.json"
def _ece(y,p,bins=10):
 total=len(y);value=0
 for lo in np.linspace(0,1,bins,endpoint=False):
  mask=(p>=lo)&(p<lo+1/bins)
  if mask.any():value+=mask.mean()*abs(y[mask].mean()-p[mask].mean())
 return float(value)
def run():
 base={x["document_id"]:x for x in (json.loads(v) for v in BASE.read_text("utf-8").splitlines())};all_runs=[]
 for train_source,test_source in (("ML_DEV_SOURCE_A","ML_DEV_SOURCE_B"),("ML_DEV_SOURCE_B","ML_DEV_SOURCE_A")):
  artifact=ROOT/"models/router_eligibility"/f"lightgbm_{train_source.lower()}_v1";engine=MLEligibilityInference(artifact)
  calibration=rows(train_source,{"calibration"});cal_probs=[]
  for r in calibration:
   evidence,_=engine.predict(MLEligibilityFeatures(**r["features"]));cal_probs.append((r,{x.family:x.probability for x in evidence}))
  thresholds={}
  for family in CLASSES:
   true=sorted(p[family] for r,p in cal_probs if r["label"]==family);thresholds[family]=max(.20,true[max(0,int(len(true)*.1)-1)] if true else .5)
  fusion_config=yaml.safe_load((ROOT/"config/document_routing_ml.yaml").read_text("utf-8"));
  for f in ("CMS1500","UB04"):fusion_config["families"][f]["threshold"]=thresholds[f]
  fusion=EligibilityFusionService(fusion_config);items=rows(test_source,{"validation","adversarial"});records=[];lat=[]
  for r in items:
   evidence,ms=engine.predict(MLEligibilityFeatures(**r["features"]));lat.append(ms);by={x.family:x for x in evidence};d=RoutingEvidence(**base[r["document_id"]]["decision"]);fused={}
   for family in ("CMS1500","UB04"):
    det=evaluate_standard_eligibility(d,family,stage=5);fused[family]=fusion.fuse(det,by[family]).model_dump()
   records.append({"document_id":r["document_id"],"truth":r["label"],"probabilities":{x.family:x.probability for x in evidence},"fused":fused,"final_deterministic_route":base[r["document_id"]]["predicted"]})
  metrics={}
  for family in CLASSES:
   truth=[x for x in records if x["truth"]==family]
   if family in {"CMS1500","UB04"}: eligible=[x for x in records if x["fused"][family]["eligible"]]
   else:eligible=[x for x in records if x["probabilities"][family]>=thresholds[family]]
   metrics[family]={"eligibility_recall":sum(x in eligible for x in truth)/len(truth) if truth else None,"eligibility_precision":sum(x["truth"]==family for x in eligible)/len(eligible) if eligible else None,"eligible_count":len(eligible)}
  standard_eligible=lambda x,f:x["fused"][f]["eligible"]
  y=np.array([x["truth"]=="CMS1500" for x in records]);p=np.array([x["probabilities"]["CMS1500"] for x in records])
  all_runs.append({"train_source":train_source,"test_source":test_source,"thresholds":thresholds,"metrics":metrics,"CMS_false_eligibility_rate":sum(standard_eligible(x,"CMS1500") and x["truth"]!="CMS1500" for x in records)/sum(x["truth"]!="CMS1500" for x in records),"UB_false_eligibility_rate":sum(standard_eligible(x,"UB04") and x["truth"]!="UB04" for x in records)/sum(x["truth"]!="UB04" for x in records),"dual_standard_eligibility_rate":sum(standard_eligible(x,"CMS1500") and standard_eligible(x,"UB04") for x in records)/len(records),"final_CMS_recall":sum(x["truth"]=="CMS1500" and x["final_deterministic_route"]=="CMS1500" for x in records)/max(1,sum(x["truth"]=="CMS1500" for x in records)),"final_UB_recall":sum(x["truth"]=="UB04" and x["final_deterministic_route"]=="UB04" for x in records)/max(1,sum(x["truth"]=="UB04" for x in records)),"final_false_standard_routes":sum(x["truth"] not in {"CMS1500","UB04"} and x["final_deterministic_route"] in {"CMS1500","UB04"} for x in records),"inference_latency_ms":{"p50":statistics.median(lat),"p95":sorted(lat)[max(0,int(len(lat)*.95)-1)]},"CMS_ECE":_ece(y,p),"records":records})
 result={"model":"LightGBM","feature_version":"ml-eligibility-features-v1","runs":all_runs,"development_gate_pass":False,"gate_blockers":["FINAL_ROUTING_RECALL_UNCHANGED","UNKNOWN_UNSTRUCTURED_TRAINING_CLASS_ABSENT","CROSS_SOURCE_SAMPLE_SIZE_INSUFFICIENT"],"decision":"REJECT","frozen_ABCD_rerun":False};OUT.write_text(json.dumps(result,indent=2),"utf-8");return result
if __name__=="__main__":
 r=run();print(json.dumps({"decision":r["decision"],"gate_blockers":r["gate_blockers"],"runs":[{k:v for k,v in x.items() if k!="records"} for x in r["runs"]]},indent=2))
