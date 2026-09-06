"""Rerun existing frozen-cohort checks without replacing historical reports."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation import closure_iteration6 as existing

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation_results/production_closure/engineering"


def run() -> dict:
    baseline = json.loads((ROOT / "docs/closure/iteration6_summary.json").read_text())
    writer = existing.write

    def retained_write(directory, name, value):
        writer(OUT, name, value)

    existing.write = retained_write
    try:
        result = existing.run()
        source_inventory = existing.source_inventory_probe()
        replay = existing.operational_replay()
    finally:
        existing.write = writer
    protected = (
        "claims",
        "fields",
        "technical_blockers",
        "technical_review_fields",
        "technical_field_hitl",
        "technically_clean_claims",
        "technical_stp_capability",
        "evidence_field_hitl",
        "total_observed_field_hitl",
        "canonical_outputs_changed",
        "production_authority",
        "perception_changed",
        "blind_review_changed",
    )
    if any(result[k] != baseline[k] for k in protected):
        raise ValueError("FROZEN_ENGINEERING_REGRESSION")
    summary = {k: result[k] for k in protected}
    summary.update(
        status="ENGINEERING_REGRESSION_PASS",
        authority="FROZEN_REGRESSION_ONLY",
        operational_replay=replay,
        source_inventory=source_inventory,
        release_accuracy=None,
        release_stp=None,
    )
    writer(ROOT / "docs/closure", "production_engineering_replay.json", summary)
    return summary


if __name__ == "__main__":
    run()
