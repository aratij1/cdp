from __future__ import annotations
import hashlib,json,subprocess
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/"evaluation_results/router_visual_v1/baseline_freeze.json"
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def freeze():
 models={}
 for p in sorted((ROOT/"models/router_visual").glob("*/metadata.json")):
  m=json.loads(p.read_text());models[p.parent.name]={"metadata_hash":sha(p),"weights_hash":m["model_sha256"],"model_size":m["model_size_bytes"],"training_source":m["training_source"]}
 value={"freeze_id":"VISUAL_ROUTER_BASELINE_V1","created_at":datetime.now(timezone.utc).isoformat(),"git_sha":subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,text=True,capture_output=True).stdout.strip(),"architecture":"HOG_LOGISTIC_224_CPU","models":models,"source_A_hash":json.loads((ROOT/"evaluation_results/router_visual_v1/manifest.json").read_text())["sources"]["VISUAL_SOURCE_A"]["hash"],"source_B_hash":json.loads((ROOT/"evaluation_results/router_visual_v1/manifest.json").read_text())["sources"]["VISUAL_SOURCE_B"]["hash"],"input_dimensions":[224,224],"normalization":"grayscale+histogram_equalization","class_mapping":["CMS1500","NON_CLAIM","UB04","UNKNOWN_STRUCTURED","UNKNOWN_UNSTRUCTURED"],"random_seed":7417,"model_version":"1.0.0","inference_version":"visual-evidence-v1","golden_metrics":{"cross_source_accuracy":.9916666666666667,"UB_recall":1.0,"UNKNOWN_STRUCTURED_recall":1.0,"UNKNOWN_UNSTRUCTURED_recall":1.0,"NON_CLAIM_recall":1.0},"status":"EVALUATION_ONLY","production_authority":False,"shadow_authority":False,"route_authority":False}
 OUT.write_text(json.dumps(value,indent=2),"utf-8");return value
if __name__=="__main__":print(json.dumps(freeze(),indent=2))
