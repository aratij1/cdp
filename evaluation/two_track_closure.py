"""Refresh two isolated measurement tracks through the existing qualification watcher."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.blind_field_metrics import build as field_metrics
from evaluation.blind_lineage_recovery import build as lineage_recovery
from evaluation.governed_30_reference import build as reference_adapter
from evaluation.governed_30_scorecard import build as engineering_scorecard
from evaluation.real_release import publish
from evaluation.two_track_isolation import assert_disjoint
from evaluation.two_track_isolation import build as isolation_check

ROOT = Path(__file__).resolve().parents[1]


def build(root: Path = ROOT) -> dict:
    out = root / "evaluation_results/real_release"
    if not (out / "governed_30_manifest.json").exists():
        return {"status": "NOT_CONFIGURED"}
    try:
        isolation = isolation_check(root)
        assert_disjoint(isolation)
        reference_adapter(root)
        # The owner-editable request is never regenerated over an existing file.
        if not (out / "150_cohort_missing_membership.csv").exists():
            lineage_recovery(root)
        blind = field_metrics(root)
        raw_path = root / "evaluation_results/governed_30_execution/raw_execution.local.json"
        seal_path = raw_path.with_name("raw_execution_seal.json")
        if not raw_path.exists() or not seal_path.exists():
            engineering = {"status": "EXECUTION_INCOMPLETE"}
        else:
            seal = json.loads(seal_path.read_text())
            if hashlib.sha256(raw_path.read_bytes()).hexdigest() != seal["raw_execution_sha256"]:
                raise ValueError("FROZEN_RAW_ENGINEERING_CAPTURE_CHANGED")
            engineering = engineering_scorecard(root)
        result = {
            "scope": "TWO_TRACK_CLOSURE",
            "track_a": engineering["status"],
            "track_b": blind["status"],
            "isolation": isolation["status"],
            "cohorts_combined": False,
            "final_release_authority": False,
        }
    except (OSError, ValueError, KeyError, TypeError):
        result = {
            "scope": "TWO_TRACK_CLOSURE",
            "status": "INPUT_INVALID_OR_CHANGED",
            "cohorts_combined": False,
            "final_release_authority": False,
        }
        # Withdraw any stale measured values if the seals or isolation no longer hold.
        publish(
            out / "governed_30_engineering_scorecard.json",
            {
                "scope": "GOVERNED_ENGINEERING",
                "status": "NOT_EVALUABLE",
                "gates": ["TWO_TRACK_INPUT_INVALID_OR_CHANGED"],
                "metrics": {},
            },
        )
        publish(
            out / "blind_field_metrics.json",
            {
                "scope": "PARTIAL_FIELD_QUALIFICATION",
                "status": "NOT_EVALUABLE",
                "gates": ["TWO_TRACK_INPUT_INVALID_OR_CHANGED"],
                "metrics": {},
            },
        )
    publish(out / "two_track_status.json", result)
    return result
