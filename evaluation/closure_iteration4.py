"""Bounded anchor experiment and blind-review handoff; publish aggregates only."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.cdp2_comparison import write
from evaluation.closure_iteration2 import ROOT
from evaluation.closure_iteration2 import run as replay
from evaluation.closure_noncanonical_probe import run as operational_replay
from evaluation.closure_performance_gate import compare_runs
from packages.claim_intelligence.document import fingerprint

LOCAL = ROOT / "evaluation_results/closure/iteration4"


def prepare_review_handoff(manifest: dict, output: Path) -> dict:
    if set(manifest) != {"cohort_sha256", "creates_labels", "pages"}:
        raise ValueError("BLIND_MANIFEST_METADATA_NOT_ALLOWLISTED")
    pages = manifest["pages"]
    keys = {(p["package_id"], p["page_id"]) for p in pages}
    if len(pages) != 150 or len(keys) != 150 or len({p["page_id"] for p in pages}) != 150:
        raise ValueError("FROZEN_150_PAGE_COHORT_REQUIRED")
    if any(set(p) != {"package_id", "page_id"} for p in pages):
        raise ValueError("BLIND_REVIEW_VIEW_MUST_NOT_CONTAIN_PREDICTIONS")
    if manifest.get("creates_labels") is not False:
        raise ValueError("REVIEW_SELECTION_MUST_NOT_CREATE_LABELS")
    write(output, "blind_manifest.json", manifest)
    # Schema only, no populated answers or automatic authority designation.
    write(
        output,
        "review_response_schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["reviewer_id", "page_id", "package_id", "source_sha256", "fields"],
            "properties": {
                "reviewer_id": {"type": "string", "minLength": 1},
                "page_id": {"type": "string", "minLength": 1},
                "package_id": {"type": "string", "minLength": 1},
                "source_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["field_name", "visibility", "observed_value"],
                        "properties": {
                            "field_name": {"type": "string", "minLength": 1},
                            "visibility": {"enum": ["READABLE", "PARTIAL", "UNREADABLE", "ABSENT"]},
                            "observed_value": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    )
    (output / "REVIEW_INSTRUCTIONS.md").write_text(
        "Review the existing source pages in the approved local viewer.\n"
        "Do not inspect model predictions or frozen reference answers.\n"
        "Two reviewers should work independently; preserve each original response.\n"
        "Record only visible source values; use null for unreadable or absent values.\n"
        "Bind every response to the exact source hash and page/package identifiers.\n"
        "An independent adjudicator must resolve disagreements without replacing original responses.\n"
        "Document extraction and external member/provider identity verification are separate.\n"
        "Responses contain sensitive data: keep them in the approved local review store, outside Git.\n"
        "This packet grants no release-truth authority. Use the existing governed ingestion and qualification gates.\n",
        encoding="utf-8",
    )
    return {
        "pages": len(pages),
        "packages": len({p["package_id"] for p in pages}),
        "predictions_in_review_view": False,
        "labels_created": 0,
        "status": "AWAITING_INDEPENDENT_HUMAN_REVIEW",
    }


def run() -> dict:
    prior_path = ROOT / "evaluation_results/closure/iteration2/iteration3_atomic_fields.json"
    prior = json.loads(prior_path.read_text())
    current = replay("iteration4_anchor_final")
    for key in ("cohort_sha256", "evidence_sha256", "canonical_outputs_sha256"):
        if prior[key] != current[key]:
            raise ValueError("BASELINE_COHORT_EVIDENCE_OR_CANONICAL_OUTPUT_CHANGED")
    before = {(r["claim"], r["field"]): r for r in prior["governed_candidate"]["fields"]}
    after = current["governed_candidate"]["fields"]
    coverage_regressions = sum(
        before[r["claim"], r["field"]]["reference_rank"] is not None and r["reference_rank"] is None
        for r in after
    )
    selection_regressions = sum(
        before[r["claim"], r["field"]]["top1_correct"] and not r["top1_correct"] for r in after
    )
    if coverage_regressions or selection_regressions:
        raise ValueError("PROTECTED_FROZEN_METRIC_REGRESSION")
    manifest_path = ROOT / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    handoff = prepare_review_handoff(json.loads(manifest_bytes), LOCAL / "human_review")
    assert manifest_path.read_bytes() == manifest_bytes
    operational = operational_replay()
    write(LOCAL, "operational_replay.json", operational)
    write(LOCAL, "claim_distances.json", current["claim_distances"])
    write(LOCAL, "remaining_review_fields.json", current["review_fields"])
    blind_packages = {p["package_id"] for p in json.loads(manifest_bytes)["pages"]}
    assert not blind_packages.intersection(p["package_id"] for p in operational["results"])
    base_runtime = json.loads((LOCAL.parent / "iteration3/repeat_3.json").read_text())[
        "experiments"
    ][0]
    pilot = json.loads((LOCAL / "opencv_single_pilot.json").read_text())["experiments"][0]
    performance = compare_runs(base_runtime, pilot)
    performance.update(
        {
            "retained": False,
            "pilot_latency": pilot["latency"],
            "scope": "FRESH_OCR_ROUTING_SPATIAL_SHADOW_NOT_COMPLETE_CLAIM_PROCESSING",
            "experiment": "OPENCV_THREADS_16_TO_1_ORT_THREADS_UNCHANGED",
            "three_run_promotion_attempted": False,
        }
    )
    write(LOCAL, "performance_candidate_gate.json", performance)
    summary = {
        "iteration": 4,
        "status": "CONTINUE",
        "authority": "ENGINEERING_FROZEN_REGRESSION",
        "fields": 200,
        "claims": 20,
        "exact_missing_before": prior["candidate"]["summary"]["buckets"]["TRUTH_NOT_IN_CANDIDATES"],
        "exact_missing_after": current["candidate"]["summary"]["buckets"][
            "TRUTH_NOT_IN_CANDIDATES"
        ],
        "exact_recall": current["candidate"]["summary"]["recall"],
        "governed_recall_before": prior["governed_candidate"]["summary"]["recall"],
        "governed_recall_after": current["governed_candidate"]["summary"]["recall"],
        "governed_missing_after": current["governed_candidate"]["summary"]["buckets"][
            "TRUTH_NOT_IN_CANDIDATES"
        ],
        "critical_c3_fields": current["governed_candidate"]["by_dimension"]["criticality"]["C3"][
            "fields"
        ],
        "critical_c3_recall_at_5": current["governed_candidate"]["by_dimension"]["criticality"][
            "C3"
        ]["recall"]["R@5"],
        "selected_value_correct_fields": sum(r["top1_correct"] for r in after),
        "coverage_regressions": coverage_regressions,
        "selection_regressions": selection_regressions,
        "technical_blockers": current["technical_blockers_after"],
        "technical_review_fields": current["technical_review_after"],
        "technical_stp_capable_claims": current["engineering_claims_unlocked"],
        "canonical_outputs_changed": False,
        "production_authority": False,
        "operational": {
            k: operational[k]
            for k in (
                "pages",
                "pages_with_candidates",
                "candidate_counts",
                "candidate_field_pairs",
                "ambiguous_field_pairs",
                "no_candidate_pages",
                "new_ocr_calls",
                "regional_ocr_calls",
                "vlm_calls",
                "canonical_localizations",
                "package_leakage",
                "elapsed_ms",
                "candidate_generation_latency",
                "observed_rss_bytes",
                "runtime_scope",
            )
        },
        "review_handoff": handoff,
        "performance_experiment": performance,
        "retained_runtime_reference": "ITERATION3_THREE_RUN_MEDIAN_P95_5581_MS_NO_NEW_RUNTIME_WIN",
        "latency_target_met": False,
        "technical_ceiling_proven": False,
        "release_metrics": {
            k: {"value": None, "status": "NOT_EVALUABLE"}
            for k in (
                "accuracy",
                "critical_accuracy",
                "accepted_precision",
                "critical_false_accepts",
                "field_hitl",
                "claim_hitl",
                "stp",
            )
        },
    }
    write(ROOT / "docs/closure", "iteration4_summary.json", summary)
    write(
        LOCAL,
        "input_binding.json",
        {
            "blind_manifest_sha256": fingerprint(json.loads(manifest_bytes)),
            "cohort_sha256": current["cohort_sha256"],
            "evidence_sha256": current["evidence_sha256"],
        },
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
