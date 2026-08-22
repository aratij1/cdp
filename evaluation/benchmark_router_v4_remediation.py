"""Benchmark remediation data separately from observed A/B/C/D regressions."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from evaluation.benchmark_routing_dev_v4 import _one
from packages.document_routing import InvariantRouterV4
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"evaluation_results/router_v4/remediation_01"
def run(label):
    manifest=json.loads((DATA/"manifest.json").read_text("utf-8")); rows=[]
    router=InvariantRouterV4.load()
    if label in {"rem01","rem01_rem02"}:
        router.config["experiments"]["rem01_content_geometry"]=True
    if label in {"rem02","rem01_rem02"}: router.config["experiments"]["rem02_token_groups"]=True
    for n,item in enumerate(manifest["documents"],1):
        rows.append(_one("ROUTING_DEV_V4_REMEDIATION_01",DATA/item["file"],item,router))
        rows[-1]["failure_bucket"]=item["failure_bucket"]
        rows[-1]["experiment_stage_latency_ms"]=dict(router.last_profile)
        if n%25==0:print(f"completed {n}/{len(manifest['documents'])}",flush=True)
    out=ROOT/f"evaluation_results/router_v4/remediation_01_{label}.jsonl"; out.write_text("\n".join(json.dumps(x) for x in rows)+"\n","utf-8"); return rows
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("label");a=p.parse_args();print(json.dumps({"documents":len(run(a.label)),"label":a.label}))
