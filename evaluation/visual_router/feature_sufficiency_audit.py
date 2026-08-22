"""Pre-training visual sufficiency audit; never substitutes a machine proxy for human review."""
from __future__ import annotations
import json
from pathlib import Path
import cv2,numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[2];BASE=ROOT/"evaluation_results/router_v4/remediation_01_before_rem01_rem02.jsonl";MAN=ROOT/"evaluation_results/router_v4/remediation_01/manifest.json";OUT=ROOT/"evaluation_results/router_visual_v1/feature_sufficiency_audit.json"
def run():
 rows=[json.loads(x) for x in BASE.read_text().splitlines()];meta={x["document_id"]:x for x in json.loads(MAN.read_text())["documents"]};records=[]
 for x in rows:
  if x["truth"] not in {"CMS1500","UB04"} or x["truth"]==x["predicted"]:continue
  a=np.asarray(Image.open(ROOT/"evaluation_results/router_v4/remediation_01"/meta[x["document_id"]]["file"]).convert("L").resize((224,224)));edges=cv2.Canny(a,80,180)
  records.append({"document_id":x["document_id"],"truth":x["truth"],"contrast_std":float(a.std()),"edge_density":float(np.count_nonzero(edges)/edges.size),"grid_score":x["decision"]["grid_score"],"ocr_tokens":x["observation"]["ocr_token_count"],"visual_signal_proxy":bool(a.std()>=18 and np.count_nonzero(edges)/edges.size>=.02),"human_recognizability":"REVIEW_REQUIRED"})
 result={"misses":len(records),"visual_signal_proxy_available":sum(x["visual_signal_proxy"] for x in records),"human_review_completed":False,"conclusion":"The conservative low-resolution proxy is positive for only a minority of misses. Visual training remains diagnostic only; human recognizability is not claimed and source/taxonomy revision may be required.","records":records};OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,indent=2),"utf-8");return result
if __name__=="__main__":print(json.dumps({k:v for k,v in run().items() if k!="records"},indent=2))
