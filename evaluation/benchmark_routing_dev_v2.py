from __future__ import annotations

import json
import math
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from packages.document_routing import MultiSignalRouter
from workers.cascade.tesseract_adapter import TesseractTextExtractor


ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"evaluation_data/ROUTING_DEV_V2"


def benchmark() -> dict:
    rows=[json.loads(line) for line in (DATA/"ground_truth.jsonl").read_text("utf-8").splitlines()]
    router=MultiSignalRouter.load(); ocr=TesseractTextExtractor(psm=11)
    truth_map={"CUSTOM_STRUCTURED":"UNKNOWN_STRUCTURED","ATTACHMENT":"UNKNOWN_UNSTRUCTURED"}
    matrix=defaultdict(Counter); latencies=[]; decisions=[]
    for row in rows:
        image=Image.open(DATA/row["path"]).convert("L"); start=time.perf_counter()
        decision=router.route(image,ocr.extract(image)); latencies.append(time.perf_counter()-start)
        matrix[row["truth_route"]][decision.route.value]+=1
        decisions.append({"document_id":row["document_id"],"condition":row["condition"],
            "truth_route":row["truth_route"],"predicted_route":decision.route.value,
            "correct":decision.route.value==truth_map.get(row["truth_route"],row["truth_route"]),
            "scores":decision.scores,"matched_anchors":decision.matched_anchors,
            "reason_codes":decision.reason_codes})
    routes=("CMS1500","UB04","UNKNOWN_STRUCTURED","UNKNOWN_UNSTRUCTURED","NON_CLAIM")
    metrics={}
    for route in routes:
        tp=fp=fn=0
        for truth,row in matrix.items():
            expected=truth_map.get(truth,truth)
            tp += row[route] if expected==route else 0
            fp += row[route] if expected!=route else 0
            fn += sum(row.values())-row[route] if expected==route else 0
        precision=tp/(tp+fp) if tp+fp else None; recall=tp/(tp+fn) if tp+fn else None
        metrics[route]={"precision":precision,"recall":recall,
                        "f1":2*precision*recall/(precision+recall) if precision and recall else 0}
    ub=metrics["UB04"]
    report={"documents":len(rows),"matrix":{key:dict(value) for key,value in matrix.items()},
            "metrics":metrics,"latency":{"p50":statistics.median(latencies),
            "p95":sorted(latencies)[math.ceil(.95*len(latencies))-1],"mean":statistics.fmean(latencies)},
            "gates":{"ub04_recall_at_least_98pct":bool(ub["recall"] is not None and ub["recall"]>=.98),
                     "ub04_precision_100pct":ub["precision"]==1.0},
            "errors":[item for item in decisions if not item["correct"]]}
    out=ROOT/"evaluation_results/ROUTING_DEV_V2"; out.mkdir(parents=True,exist_ok=True)
    (out/"benchmark.json").write_text(json.dumps(report,indent=2),"utf-8"); return report


if __name__=="__main__": print(json.dumps(benchmark(),indent=2))
