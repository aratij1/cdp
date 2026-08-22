from __future__ import annotations
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image
from packages.document_routing.visual import VisualEvidenceInference
ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/"evaluation_results/visual_safety_dev_v1"
def work_det(item):
 from evaluation.benchmark_routing_dev_v4 import _one
 return _one("VISUAL_SAFETY_DEV_V1",Path(item["path"]),item)
def work_visual(item):
 predictions={};lat={}
 for source in ("a","b"):
  engine=VisualEvidenceInference(ROOT/"models/router_visual"/f"hog_logistic_visual_source_{source}_v1");e,ms=engine.predict(Image.open(item["path"]));predictions[source]=[x.model_dump() for x in e];lat[source]=ms
 return predictions,lat
def run_det():
 docs=json.loads((DATA/"manifest.json").read_text())["documents"]
 with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(work_det,docs))
 (DATA/"benchmark.jsonl").write_text("\n".join(json.dumps(x) for x in rows)+"\n","utf-8");return rows
def enrich():
 docs=json.loads((DATA/"manifest.json").read_text())["documents"];rows=[json.loads(x) for x in (DATA/"benchmark.jsonl").read_text().splitlines()]
 for row,item in zip(rows,docs):row["visual_evidence"],row["visual_latency_ms"]=work_visual(item)
 (DATA/"benchmark.jsonl").write_text("\n".join(json.dumps(x) for x in rows)+"\n","utf-8");return rows
if __name__=="__main__":
 import sys;print(len(enrich() if len(sys.argv)>1 and sys.argv[1]=="enrich" else run_det()))
