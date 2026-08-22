"""Cross-source V4 gate evaluator. It never reads the observed representative corpus."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

STANDARD={"CMS1500","UB04"}
PARTITIONS={"ROUTING_DEV_V4_A_STANDARD","ROUTING_DEV_V4_B_STANDARD_ALTERNATE",
            "ROUTING_DEV_V4_C_CUSTOM_NEGATIVE","ROUTING_DEV_V4_D_DEGRADATION"}


def _ratio(n:int,d:int)->float: return n/d if d else 0.0


def evaluate(rows:list[dict])->dict:
    found={x["partition"] for x in rows}
    missing=PARTITIONS-found
    if missing: raise ValueError(f"missing V4 partitions: {sorted(missing)}")
    report={"evidence_class":"MULTI_SOURCE_DEVELOPMENT_ONLY","representative_data_used":False,"partitions":{}}
    gate_values=[]
    for partition in sorted(PARTITIONS):
        items=[x for x in rows if x["partition"]==partition]
        metrics={"count":len(items),"by_family":{},"by_degradation":{}}
        for family in sorted({x["truth"] for x in items}|STANDARD):
            tp=sum(x["truth"]==family and x["predicted"]==family for x in items)
            truth=sum(x["truth"]==family for x in items); predicted=sum(x["predicted"]==family for x in items)
            metrics["by_family"][family]={"recall":_ratio(tp,truth),"precision":_ratio(tp,predicted),"support":truth}
        for bucket in sorted({x["degradation_family"] for x in items}):
            bucket_rows=[x for x in items if x["degradation_family"]==bucket and x["truth"] in STANDARD]
            metrics["by_degradation"][bucket]={"standard_recall":_ratio(sum(x["truth"]==x["predicted"] for x in bucket_rows),len(bucket_rows)),"support":len(bucket_rows)}
        nonstandard=[x for x in items if x["truth"] not in STANDARD]
        metrics["false_standard_rate"]=_ratio(sum(x["predicted"] in STANDARD for x in nonstandard),len(nonstandard))
        report["partitions"][partition]=metrics
        if partition.endswith("A_STANDARD") or "B_STANDARD" in partition:
            gate_values.extend(metrics["by_family"][f][k] for f in STANDARD for k in ("precision","recall"))
        elif "C_CUSTOM" in partition:
            gate_values += [metrics["by_family"]["UNKNOWN_STRUCTURED"]["recall"],
                metrics["by_family"]["NON_CLAIM"]["recall"],1-metrics["false_standard_rate"]]
        else:
            degradation=[v["standard_recall"] for v in metrics["by_degradation"].values() if v["support"]]
            gate_values += degradation
    latency=sorted(float(x["routing_latency_ms"]) for x in rows)
    p95=latency[max(0,int(len(latency)*.95)-1)] if latency else None
    report["latency"]={"p95_ms":p95,"normal_ocr_calls_max":max((x.get("ocr_calls_page",1) for x in rows),default=0)}
    # Deliberately dominated by the weakest observed source/family/bucket, with an explicit safety penalty.
    false_rate=max(x["false_standard_rate"] for x in report["partitions"].values())
    report["ROUTER_GENERALIZATION_SCORE"]=max(0.0,min(gate_values,default=0.0)-2*false_rate)
    report["promotion_gate"]={
        "v4_a_pass":all(report["partitions"]["ROUTING_DEV_V4_A_STANDARD"]["by_family"][f]["precision"]>=.99 and report["partitions"]["ROUTING_DEV_V4_A_STANDARD"]["by_family"][f]["recall"]>=.98 for f in STANDARD),
        "v4_b_pass":all(report["partitions"]["ROUTING_DEV_V4_B_STANDARD_ALTERNATE"]["by_family"][f]["precision"]>=.99 and report["partitions"]["ROUTING_DEV_V4_B_STANDARD_ALTERNATE"]["by_family"][f]["recall"]>=.98 for f in STANDARD),
        "v4_c_pass":report["partitions"]["ROUTING_DEV_V4_C_CUSTOM_NEGATIVE"]["by_family"]["UNKNOWN_STRUCTURED"]["recall"]>=.95 and report["partitions"]["ROUTING_DEV_V4_C_CUSTOM_NEGATIVE"]["by_family"]["NON_CLAIM"]["recall"]>=.99 and report["partitions"]["ROUTING_DEV_V4_C_CUSTOM_NEGATIVE"]["false_standard_rate"]<=.005,
        "v4_d_pass":all(v["standard_recall"]>=.95 for v in report["partitions"]["ROUTING_DEV_V4_D_DEGRADATION"]["by_degradation"].values() if v["support"]),
        "latency_pass":p95 is not None and p95<=750,
        "ocr_budget_pass":report["latency"]["normal_ocr_calls_max"]<=1,
    }
    report["promotion_gate"]["all_development_gates_pass"]=all(report["promotion_gate"].values())
    return report


def main(path:Path,output:Path)->None:
    rows=[json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(evaluate(rows),indent=2),"utf-8")


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument("manifest",type=Path); parser.add_argument("output",type=Path)
    args=parser.parse_args(); main(args.manifest,args.output)

