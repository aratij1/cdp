"""Promote repeated route values only when cross-engine evidence anchors the population."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ALLOWED_ROUTES = {
    ("UB04", "description"),
    ("UB04", "hcpcs_rate_hipps_code"),
}


def _value(row: dict) -> str:
    return str(row.get("normalized_value") or row.get("selected_value") or "").strip().upper()


def tune(rows: list[dict], *, minimum_documents: int = 3) -> tuple[list[dict], dict]:
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        identity = row.get("field_identity") or {}
        key = (str(identity.get("document_family")), str(identity.get("semantic_field")), _value(row))
        if key[:2] in ALLOWED_ROUTES and key[2]:
            groups[key].append(row)
    qualified = set()
    for key, group in groups.items():
        documents = {(row.get("field_identity") or {}).get("document_id") for row in group}
        anchored = any("CROSS_FAMILY_AGREEMENT" in (row.get("validation_results") or []) for row in group)
        if len(documents) >= minimum_documents and anchored:
            qualified.add(key)
    promoted = 0
    for row in rows:
        if not row.get("review_required"):
            continue
        identity = row.get("field_identity") or {}
        key = (str(identity.get("document_family")), str(identity.get("semantic_field")), _value(row))
        if key not in qualified:
            continue
        row["review_required"] = False
        row["automatically_acceptable"] = True
        row["candidate_status"] = "AUTO_ACCEPTED_CURRENT_SAMPLE_POPULATION_CONSENSUS"
        row.setdefault("validation_results", []).extend([
            "CROSS_DOCUMENT_VALUE_AGREEMENT",
            "CROSS_ENGINE_ANCHORED_POPULATION",
        ])
        row["population_consensus"] = {
            "document_support": len({
                (item.get("field_identity") or {}).get("document_id") for item in groups[key]
            }),
            "cross_engine_anchor": True,
            "scope": "CURRENT_SAMPLE_REPLAY_HOLDOUT_PENDING",
        }
        promoted += 1
    remaining = sum(bool(row.get("review_required")) for row in rows)
    return rows, {
        "total_fields": len(rows),
        "population_promoted_fields": promoted,
        "remaining_review_fields": remaining,
        "qualified_population_values": len(qualified),
        "scope": "CURRENT_SAMPLE_REPLAY_HOLDOUT_PENDING",
        "production_generalization_claim": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.predictions.read_text(encoding="utf-8"))
    tuned, metrics = tune(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "predictions.json").write_text(json.dumps(tuned, indent=2), encoding="utf-8")
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
