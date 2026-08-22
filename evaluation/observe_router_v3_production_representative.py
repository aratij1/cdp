"""Routing-only regression observation on the previously observed V2 sample.

This is not untouched evidence and must never be used to tune Router V3.
"""

from __future__ import annotations

import hashlib, json, math, statistics, time
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.audit_production_holdout_v2 import DEFAULT_DATASET
from evaluation.run_production_holdout_v2 import TRUTH_ROUTE, _prepare
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from workers.cascade.tesseract_adapter import TesseractTextExtractor
from workers.page_detection.router import PageRoutingService

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"evaluation_results/PRODUCTION_REPRESENTATIVE_V2_ROUTER_V3_OBSERVATION"


def observe(dataset:Path=DEFAULT_DATASET)->dict:
    freeze=json.loads((ROOT/"config/router_v3_freeze.json").read_text("utf-8"))
    config_hash=hashlib.sha256((ROOT/"config/document_routing.yaml").read_bytes()).hexdigest()
    if config_hash!=freeze["router_config_sha256"]: raise ValueError("ROUTER_V3_CONFIG_NOT_FROZEN")
    metadata=[json.loads(x) for x in (dataset/"metadata/document_metadata.jsonl").read_text("utf-8").splitlines()]
    registry=TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    cms,ub=registry.get("cms1500","02-12"),registry.get("ub04","2014")
    router=PageRoutingService(cms,ub,TesseractTextExtractor(psm=11),
        registry.load_reference_image(cms),registry.load_reference_image(ub),enable_router_v3=True)
    predictions=[]; latency=[]
    # Runtime inference is truth-blind. Truth family is joined only below for metrics.
    for row in metadata:
        image=_prepare(dataset/row["path"]); started=time.perf_counter()
        decision=router.route_single_page(image); elapsed=time.perf_counter()-started; latency.append(elapsed)
        predictions.append({"document_id":row["document_id"],"predicted_route":decision.canonical_route.value,
            "route_decision":decision.route_decision.model_dump(mode="json"),"routing_seconds":elapsed})
    truth={row["document_id"]:TRUTH_ROUTE[row["family"]] for row in metadata}
    matrix=defaultdict(Counter)
    for item in predictions: matrix[truth[item["document_id"]]][item["predicted_route"]]+=1
    correct=sum(truth[x["document_id"]]==x["predicted_route"] for x in predictions)
    report={"evidence_class":"PREVIOUSLY_OBSERVED_PRODUCTION_REPRESENTATIVE_REGRESSION",
        "untouched":False,"tuning_permitted":False,"router_freeze_id":"ROUTER_V3",
        "router_git_sha":freeze["router_git_sha"],"documents":len(predictions),
        "routing_accuracy":correct/len(predictions),"matrix":{k:dict(v) for k,v in matrix.items()},
        "latency":{"p50":statistics.median(latency),"p95":sorted(latency)[math.ceil(.95*len(latency))-1],
                   "mean":statistics.fmean(latency)},"extraction_invocations":0,
        "prediction_count":len(predictions)}
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/"predictions.json").write_text(json.dumps(predictions,indent=2),"utf-8")
    (OUTPUT/"report.json").write_text(json.dumps(report,indent=2),"utf-8")
    return report


if __name__=="__main__": print(json.dumps(observe(),indent=2))
