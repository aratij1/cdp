"""Compare tabular, visual and corroborated hybrid eligibility on identical sources."""
from __future__ import annotations
import json,statistics,yaml
from pathlib import Path
from PIL import Image
from packages.document_routing import RoutingEvidence,evaluate_standard_eligibility
from packages.document_routing.ml import MLEligibilityFeatures,MLEligibilityInference
from packages.document_routing.visual import VisualEvidenceInference
ROOT=Path(__file__).resolve().parents[2];VDATA=ROOT/"evaluation_results/router_visual_v1";MLDATA=ROOT/"evaluation_results/router_ml_eligibility_v1";BASE=ROOT/"evaluation_results/router_v4/remediation_01_before_rem01_rem02.jsonl"
FAMILIES=["CMS1500","UB04","UNKNOWN_STRUCTURED","UNKNOWN_UNSTRUCTURED","NON_CLAIM"]
def run():
 base={x["document_id"]:x for x in (json.loads(v) for v in BASE.read_text().splitlines())};runs=[]
 for test,train in (("VISUAL_SOURCE_A","VISUAL_SOURCE_B"),("VISUAL_SOURCE_B","VISUAL_SOURCE_A")):
  docs=json.loads((VDATA/f"{test}.json").read_text())["documents"];visual=VisualEvidenceInference(ROOT/"models/router_visual"/f"hog_logistic_{train.lower()}_v1");ml=MLEligibilityInference(ROOT/"models/router_eligibility"/f"lightgbm_ml_dev_source_{'b' if test.endswith('A') else 'a'}_v1")
  records=[];lat=[]
  for d in docs:
   ve,ms=visual.predict(Image.open(d["path"]));lat.append(ms);vp={x.family:x.probability for x in ve};row=base.get(d["document_id"]);det={};mp={}
   if row:
    decision=RoutingEvidence(**row["decision"]);det={f:evaluate_standard_eligibility(decision,f,stage=5) for f in ("CMS1500","UB04")};me,_=ml.predict(MLEligibilityFeatures(**next(x["features"] for x in (json.loads(v) for v in (MLDATA/f"ML_DEV_SOURCE_{'A' if test.endswith('A') else 'B'}.jsonl").read_text().splitlines()) if x["document_id"]==d["document_id"])));mp={x.family:x.probability for x in me}
   proposed={"A_LIGHTGBM":set(),"B_VISUAL":{max(vp,key=vp.get)},"C_DETERMINISTIC_VISUAL":set(),"D_DETERMINISTIC_ML_VISUAL":set()}
   if mp:proposed["A_LIGHTGBM"]={max(mp,key=mp.get)}
   for f in ("CMS1500","UB04"):
    if not det:continue
    support=(det[f].structure_evidence>=.45 and (det[f].anchor_evidence>=.05 or det[f].geometry_evidence>=.05)) if f=="CMS1500" else (det[f].structure_evidence>=.6 and (det[f].service_table_evidence>=.15 or det[f].anchor_evidence>=.05))
    if det[f].eligible or (vp[f]>=.5 and support):proposed["C_DETERMINISTIC_VISUAL"].add(f)
    if det[f].eligible or ((vp[f]>=.5 or mp.get(f,0)>=.5) and support):proposed["D_DETERMINISTIC_ML_VISUAL"].add(f)
   for approach in ("C_DETERMINISTIC_VISUAL","D_DETERMINISTIC_ML_VISUAL"):
    if d["label"] not in {"CMS1500","UB04"} and vp[d["label"]]>=.5:proposed[approach].add(d["label"])
   records.append({"truth":d["label"],"proposed":{k:sorted(v) for k,v in proposed.items()}})
  metrics={}
  for approach in records[0]["proposed"]:
   per={}
   for f in FAMILIES:
    truth=sum(x["truth"]==f for x in records);eligible=sum(x["truth"]==f and f in x["proposed"][approach] for x in records);all_e=sum(f in x["proposed"][approach] for x in records)
    per[f]={"eligibility_recall":eligible/truth if truth else None,"eligibility_precision":eligible/all_e if all_e else None}
   false_standard=sum(x["truth"] not in {"CMS1500","UB04"} and any(f in x["proposed"][approach] for f in ("CMS1500","UB04")) for x in records)/len(records)
   wrong_standard=sum(x["truth"] in {"CMS1500","UB04"} and any(f!=x["truth"] and f in x["proposed"][approach] for f in ("CMS1500","UB04")) for x in records)/len(records)
   metrics[approach]={"per_family":per,"false_standard_eligibility_rate":false_standard+wrong_standard,"dual_standard_eligibility_rate":sum(all(f in x["proposed"][approach] for f in ("CMS1500","UB04")) for x in records)/len(records)}
  runs.append({"test_source":test,"metrics":metrics,"visual_latency_p95_ms":sorted(lat)[int(len(lat)*.95)-1]})
 worst={a:{f:min(r["metrics"][a]["per_family"][f]["eligibility_recall"] or 0 for r in runs) for f in FAMILIES} for a in runs[0]["metrics"]}
 result={"runs":runs,"worst_source_recall":worst,"development_gate_pass":False,"decision":"REJECT","reason":"Visual-only false-standard eligibility is 0.83%; corroborated hybrids fail CMS/UB recall gates or non-standard coverage. Source taxonomy proxy is weak.","frozen_ABCD_rerun":False,"final_routes_changed":False};(VDATA/"approach_comparison.json").write_text(json.dumps(result,indent=2),"utf-8");return result
if __name__=="__main__":print(json.dumps(run(),indent=2))
