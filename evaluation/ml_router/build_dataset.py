"""Build source-separated PHI-safe ML tables from RouterFeatureBundle-derived evidence."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from packages.document_routing import RoutingEvidence
from packages.document_routing.ml.features import FEATURE_NAMES,FEATURE_SCHEMA_VERSION,features_from_evidence
ROOT=Path(__file__).resolve().parents[2];INPUT=ROOT/"evaluation_results/router_v4/remediation_01_before_rem01_rem02.jsonl";MANIFEST=ROOT/"evaluation_results/router_v4/remediation_01/manifest.json";OUT=ROOT/"evaluation_results/router_ml_eligibility_v1"
def build():
 rows=[json.loads(x) for x in INPUT.read_text("utf-8").splitlines()];meta={x["document_id"]:x for x in json.loads(MANIFEST.read_text("utf-8"))["documents"]};OUT.mkdir(parents=True,exist_ok=True);counts={}
 for source,needle in (("ML_DEV_SOURCE_A","PIL_"),("ML_DEV_SOURCE_B","OPENCV_")):
  values=[]
  for x in rows:
   if not meta[x["document_id"]]["renderer_family"].startswith(needle):continue
   features=features_from_evidence(RoutingEvidence(**x["decision"]),x["observation"]).model_dump();digest=int(hashlib.sha256(x["document_id"].encode()).hexdigest()[:8],16)%10
   split="adversarial" if x["truth"] not in {"CMS1500","UB04"} and digest<4 else "calibration" if digest==4 else "validation" if digest in {5,6} else "train"
   values.append({"document_id":x["document_id"],"label":x["truth"],"source":source,"renderer_family":meta[x["document_id"]]["renderer_family"],"split":split,"features":features})
  path=OUT/f"{source}.jsonl";path.write_text("\n".join(json.dumps(x) for x in values)+"\n","utf-8");counts[source]={"documents":len(values),"hash":hashlib.sha256(path.read_bytes()).hexdigest(),"splits":{s:sum(x["split"]==s for x in values) for s in ("train","validation","calibration","adversarial")}}
 manifest={"dataset_id":"ROUTING_DEV_ML_ELIGIBILITY_V1","feature_schema_version":FEATURE_SCHEMA_VERSION,"feature_names":FEATURE_NAMES,"contains_phi":False,"raw_ocr_text_persisted":False,"frozen_abcd_used":False,"sources":counts,"limitation":"UNKNOWN_UNSTRUCTURED is absent from remediation_01; five-class promotion is therefore blocked pending new independent examples."};(OUT/"manifest.json").write_text(json.dumps(manifest,indent=2),"utf-8");return manifest
if __name__=="__main__":print(json.dumps(build(),indent=2))
