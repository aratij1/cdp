"""Run one frozen V4 configuration against all development sources."""
from __future__ import annotations
import json,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from PIL import Image
from packages.document_routing import InvariantRouterV4,build_router_observation
from workers.cascade.tesseract_adapter import TesseractTextExtractor
from workers.page_detection.routing_input import prepare_routing_image

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"evaluation_results/router_v4/datasets"; OUT=ROOT/"evaluation_results/router_v4/cross_source"
def _one(partition,path,item,router=None):
    start=time.perf_counter(); raw=Image.open(path); prep_start=time.perf_counter(); image=prepare_routing_image(raw); prep=(time.perf_counter()-prep_start)*1000
    ocr=TesseractTextExtractor(psm=11); ocr_start=time.perf_counter(); lines=ocr.extract(image); ocr_ms=(time.perf_counter()-ocr_start)*1000
    route_start=time.perf_counter(); decision=(router or InvariantRouterV4.load()).route(image,lines); route_ms=(time.perf_counter()-route_start)*1000; total=(time.perf_counter()-start)*1000
    observation=build_router_observation(document_id=item["document_id"],image=image,lines=lines,decision=decision,truth_family=item["truth"],image_quality_bucket=item["quality_bucket"],ocr_latency_ms=ocr_ms,
      stage_latency_ms={"decode_ms":0.0,"image_features_ms":prep,"structure_ms":route_ms,"total_ms":total})
    return {"partition":partition,"truth":item["truth"],"predicted":decision.route.value,"source_family":item["source_family"],"renderer_family":item["renderer_family"],"degradation_family":item["degradation_family"],
      "quality_bucket":item["quality_bucket"],"document_id":item["document_id"],"routing_latency_ms":total,"ocr_calls_page":1,"fallback_calls_page":0,"retry_calls_page":0,
      "decision":decision.model_dump(mode="json"),"observation":observation.model_dump(mode="json")}
def run(workers=4):
    jobs=[]
    for mp in DATA.glob("*/manifest.json"):
      m=json.loads(mp.read_text("utf-8")); jobs += [(m["dataset_id"],mp.parent/d["file"],d) for d in m["documents"]]
    rows=[]; OUT.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
      futures=[pool.submit(_one,*j) for j in jobs]
      for n,f in enumerate(as_completed(futures),1):
        rows.append(f.result())
        if n%50==0: print(f"completed {n}/{len(jobs)}",flush=True)
    rows.sort(key=lambda x:(x["partition"],x["document_id"])); (OUT/"predictions.jsonl").write_text("\n".join(json.dumps(x) for x in rows)+"\n","utf-8"); return rows
if __name__=="__main__": print(json.dumps({"documents":len(run())},indent=2))
