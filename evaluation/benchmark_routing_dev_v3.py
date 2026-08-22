from __future__ import annotations

import json, math, statistics, time
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from packages.document_routing import MultiSignalRoute, MultiSignalRouter
from workers.cascade.tesseract_adapter import TesseractTextExtractor

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"evaluation_data/ROUTING_DEV_V3"


def benchmark():
    rows=[json.loads(x) for x in (DATA/"ground_truth.jsonl").read_text("utf-8").splitlines()]
    router=MultiSignalRouter.load(); ocr=TesseractTextExtractor(psm=11)
    matrix=defaultdict(Counter); details=[]; latency=[]
    for row in rows:
        image=Image.open(DATA/row["path"]).convert("L"); started=time.perf_counter()
        lines=ocr.extract(image); decision=router.route(image,lines); latency.append(time.perf_counter()-started)
        matrix[row["truth_route"]][decision.route.value]+=1
        details.append({**row,"predicted_route":decision.route.value,"correct":decision.route.value==row["truth_route"],
            "decision":decision.model_dump(mode="json"),"ocr_calls":1})
    routes=[x.value for x in MultiSignalRoute]; metrics={}
    for route in routes:
        tp=sum(counts[route] for truth,counts in matrix.items() if truth==route)
        fp=sum(counts[route] for truth,counts in matrix.items() if truth!=route)
        fn=sum(sum(counts.values())-counts[route] for truth,counts in matrix.items() if truth==route)
        precision=tp/(tp+fp) if tp+fp else None; recall=tp/(tp+fn) if tp+fn else None
        metrics[route]={"precision":precision,"recall":recall,"true_positive":tp,"false_positive":fp}
    false_standard=sum(x["predicted_route"] in {"CMS1500","UB04"} and x["truth_route"] not in {"CMS1500","UB04"} for x in details)
    p95=sorted(latency)[math.ceil(.95*len(latency))-1]
    gates={"cms_precision":(metrics["CMS1500"]["precision"] or 0)>=.99,"cms_recall":(metrics["CMS1500"]["recall"] or 0)>=.98,
        "ub_precision":(metrics["UB04"]["precision"] or 0)>=.99,"ub_recall":(metrics["UB04"]["recall"] or 0)>=.98,
        "custom_structured_recall":(metrics["UNKNOWN_STRUCTURED"]["recall"] or 0)>=.95,
        "non_claim_accuracy":(metrics["NON_CLAIM"]["recall"] or 0)>=.99,
        "false_standard_rate":false_standard/len(details)<=.005,"p95_latency":p95<=.750}
    report={"dataset":"ROUTING_DEV_V3","documents":len(rows),"matrix":{k:dict(v) for k,v in matrix.items()},
        "metrics":metrics,"false_standard_routes":false_standard,"false_standard_rate":false_standard/len(details),
        "latency":{"p50":statistics.median(latency),"p95":p95,"mean":statistics.fmean(latency)},
        "ocr_calls_per_document":1.0,"gates":gates,"promotion":"PROMOTE" if all(gates.values()) else "REJECT",
        "false_negative_pareto":[x for x in details if x["truth_route"] in {"CMS1500","UB04"} and not x["correct"]],
        "details":details}
    out=ROOT/"evaluation_results/ROUTING_DEV_V3"; out.mkdir(parents=True,exist_ok=True)
    (out/"benchmark.json").write_text(json.dumps(report,indent=2),"utf-8"); return report


if __name__=="__main__":
    result=benchmark()
    print(json.dumps({key:value for key,value in result.items()
                      if key not in {"details","false_negative_pareto"}},indent=2))
