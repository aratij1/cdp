"""Merge completed truth-blind inference shards, then score exactly once."""

import json
import argparse
from pathlib import Path

from evaluation.audit_production_holdout_v2 import DEFAULT_DATASET, DEFAULT_OUTPUT
from evaluation.run_production_holdout_v2 import score


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", type=int, default=200)
    parser.add_argument("--shards-dir", type=Path, default=DEFAULT_OUTPUT / "sample200_shards")
    args = parser.parse_args()
    shards = sorted(args.shards_dir.glob("*/predictions_*.json"))
    predictions = [item for shard in shards for item in json.loads(shard.read_text("utf-8"))]
    ids = [item["document_id"] for item in predictions]
    if len(ids) != args.expected or len(set(ids)) != args.expected:
        raise SystemExit(f"expected {args.expected} unique predictions, got {len(ids)}/{len(set(ids))}")
    predictions.sort(key=lambda item: item["document_id"])
    (DEFAULT_OUTPUT / "predictions.json").write_text(json.dumps(predictions, indent=2), "utf-8")
    report = score(DEFAULT_DATASET, DEFAULT_OUTPUT, predictions)
    print(json.dumps({key: report[key] for key in
                      ("routing", "extraction", "decision", "claim", "latency", "cost")}, indent=2))
