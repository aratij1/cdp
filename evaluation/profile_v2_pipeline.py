"""Profile the immutable rejected baseline without rerunning V2."""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from evaluation.audit_production_holdout_v2 import DEFAULT_DATASET


ROOT=Path(__file__).resolve().parents[1]; RESULTS=ROOT/"evaluation_results/production_holdout_v2"


def _summary(values):
    ordered=sorted(values); return {"mean":statistics.fmean(values),"p50":statistics.median(values),
        "p95":ordered[math.ceil(.95*len(values))-1],"p99":ordered[math.ceil(.99*len(values))-1]}


def profile() -> dict:
    predictions=json.loads((RESULTS/"predictions.json").read_text("utf-8"))
    metadata={item["document_id"]:item for item in
              (json.loads(line) for line in (DEFAULT_DATASET/"metadata/document_metadata.jsonl").read_text("utf-8").splitlines())}
    stages=defaultdict(list); routes=defaultdict(list); families=defaultdict(list); cpu=[]
    for item in predictions:
        for name,value in item["stage_seconds"].items(): stages[name].append(value)
        routes[item["route"]].append(item["wall_seconds"])
        families[metadata[item["document_id"]]["family"]].append(item["wall_seconds"])
        cpu.append(item["cpu_seconds"])
    ranked=sorted(({"stage":name,"total_seconds":sum(values),**_summary(values)}
                   for name,values in stages.items()),key=lambda item:item["total_seconds"],reverse=True)
    report={"baseline":"PRODUCTION_HOLDOUT_V2_BASELINE_REJECTED","documents":len(predictions),
        "end_to_end":_summary([item["wall_seconds"] for item in predictions]),"cpu":_summary(cpu),
        "stages_ranked":ranked,"by_predicted_route":{key:_summary(value) for key,value in routes.items()},
        "by_truth_family":{key:_summary(value) for key,value in families.items()},
        "historical_instrumentation_limit":"Per-call cache/crop telemetry was added after this frozen run; historical duplicate-crop counts are not inferable.",
        "ocr_calls":{"rapidocr":sum(x["counters"].get("rapidocr_calls",0) for x in predictions),
                     "paddleocr":sum(x["counters"].get("paddleocr_calls",0) for x in predictions)}}
    out=ROOT/"evaluation_results/PRODUCTION_HOLDOUT_V2_BASELINE_REJECTED/performance_profile.json"
    out.write_text(json.dumps(report,indent=2),"utf-8"); return report
if __name__=="__main__": print(json.dumps(profile(),indent=2))
