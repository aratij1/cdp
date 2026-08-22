from __future__ import annotations
import json,statistics,time
from pathlib import Path
from packages.document_routing import RoutingEvidence
from packages.document_routing.visual.contracts import VisualRouteEvidence
from packages.document_routing.visual.contradiction import VisualContradictionService
ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/"evaluation_results/visual_safety_dev_v1"
LABELS=["CMS1500","UB04","UNKNOWN_STRUCTURED","UNKNOWN_UNSTRUCTURED","NON_CLAIM"]
def run():
 rows=[json.loads(x) for x in (DATA/"benchmark.jsonl").read_text().splitlines()];result={"dataset":"VISUAL_SAFETY_DEV_V1","models":{}}
 for model in ("a","b"):
  stages={}
  for stage in range(1,6):
   outputs=[];lat=[];audits=[]
   for x in rows:
    ev=[VisualRouteEvidence(**v) for v in x["visual_evidence"][model]];rank=max(ev,key=lambda v:v.probability);pred=rank.family
    if stage>1 and pred in {"CMS1500","UB04"}:
     start=time.perf_counter();audit=VisualContradictionService(stage=stage).evaluate(ev,RoutingEvidence(**x["decision"]));lat.append((time.perf_counter()-start)*1000)
     if audit.contradiction_detected:pred="UNKNOWN_STRUCTURED"
     audits.append(audit.model_dump())
    outputs.append((x["truth"],pred))
   per={f:sum(t==f and p==f for t,p in outputs)/sum(t==f for t,p in outputs) for f in LABELS}
   cross=sum(t in {"CMS1500","UB04"} and p in {"CMS1500","UB04"} and t!=p for t,p in outputs);nonstd=sum(t not in {"CMS1500","UB04"} and p in {"CMS1500","UB04"} for t,p in outputs)
   stages[f"VC-0{stage}"]={"recall":per,"standard_to_other_standard":cross,"non_standard_to_standard":nonstd,"false_standard_rate":(cross+nonstd)/len(outputs),"abstentions":sum(p=="UNKNOWN_STRUCTURED" and t in {"CMS1500","UB04"} for t,p in outputs),"contradiction_latency_p95_ms":sorted(lat)[int(len(lat)*.95)-1] if lat else 0,"visual_latency_p95_ms":sorted(x["visual_latency_ms"][model] for x in rows)[int(len(rows)*.95)-1],"audits":audits}
  result["models"][model]=stages
 result["development_gate_pass"]=all(any(stage["recall"]["CMS1500"]>=.95 and stage["recall"]["UB04"]>=.98 and all(stage["recall"][f]>=.98 for f in LABELS[2:]) and stage["false_standard_rate"]<=.005 and stage["visual_latency_p95_ms"]+stage["contradiction_latency_p95_ms"]<=75 for stage in stages.values()) for stages in result["models"].values())
 result["decision"]="PROMOTE" if result["development_gate_pass"] else "REJECT";result["frozen_ABCD_rerun"]=False
 (DATA/"contradiction_report.json").write_text(json.dumps(result,indent=2),"utf-8");return result
if __name__=="__main__":
 r=run();print(json.dumps({"decision":r["decision"],"development_gate_pass":r["development_gate_pass"],"models":{m:{s:{k:v for k,v in x.items() if k!="audits"} for s,x in stages.items()} for m,stages in r["models"].items()}},indent=2))
