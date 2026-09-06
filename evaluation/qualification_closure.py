"""Finite closure queue; refresh on review completion and watch for governed inputs."""

from __future__ import annotations

import argparse
import json
import os
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from packages.real_data_evaluation.blind_workflow import (
    BlindReviewStore,
    content_digest,
    review_progress,
)
from packages.real_data_evaluation.qualification_cost import Rates, Workload, calculate
from packages.real_data_evaluation.release_cohort import build_release_cohort
from packages.real_data_evaluation.release_scoring import score_release
from packages.real_data_evaluation.release_truth import finalize_reviews, freeze_truth

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation_results/qualification_closure"


def load(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else ({} if default is None else default)


def write(name: str, payload: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    temporary = OUT / (name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(OUT / name)


def write_immutable(name: str, payload: dict) -> None:
    """Publish a complete file without replacing another refresh's frozen input."""
    path = OUT / name
    temporary = OUT / (name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            if load(path) != payload:
                raise ValueError("IMMUTABLE_QUALIFICATION_INPUT_CHANGED") from None
    finally:
        temporary.unlink(missing_ok=True)


def refresh() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    binding = load(OUT / "source_binding_summary.json")
    source_rows = load(OUT / "blind_source_views.local.json", [])
    sources = {r["page_id"]: r for r in source_rows}
    rows = BlindReviewStore(OUT / "blind_reviews.sqlite3").completed()
    registry = load(OUT / "reviewer_registry.local.json")
    progress = review_progress(
        rows,
        {p: r["rendered_page_sha256"] for p, r in sources.items()},
        frozenset(registry.get("authorized_reviewers", [])),
    )
    adjudications = BlindReviewStore(OUT / "blind_reviews.sqlite3").adjudications()
    truth = finalize_reviews(rows, sources, registry, adjudications)
    if truth["status"] == "FROZEN":
        freeze_truth(OUT / "release_truth_manifest.local.json", truth)
        progress["trusted_labels"] = len(truth["records"])
        progress["adjudications"] = sum(r["authority"] == "ADJUDICATED" for r in truth["records"])
    write("review_completion_status.json", progress)
    write(
        "release_truth_manifest.json",
        {
            "status": truth["status"],
            "truth_sha256": truth.get("truth_sha256"),
            "pages": len(sources) if truth["status"] == "FROZEN" else 0,
            "fields": len(truth["records"]),
            "critical_fields": len(truth["records"]),
            "pending_review_or_adjudication": len(truth.get("pending", [])),
            "reason": truth.get("reason"),
            "release_authority_activated": False,
        },
    )
    membership = load(OUT / "claim_membership.local.json")
    raw = load(OUT / "raw_predictions.local.json")
    final = load(OUT / "post_hitl_predictions.local.json")
    scoring: dict = {"status": "NOT_EVALUABLE", "raw": {}, "post_hitl": {}}
    if (
        truth["status"] == "FROZEN"
        and binding.get("binding_coverage") == 1
        and membership
        and raw
        and final
    ):
        all_bindings = load(OUT / "source_page_bindings.local.json")["bindings"]
        assignments = load(
            ROOT / "evaluation_results/production_closure/release/package_reservation.local.json"
        )["assignments"]
        # Reservation IDs are already the blind-view package IDs.
        scoped, cohort = build_release_cohort(truth, all_bindings, membership, assignments)
        freeze_truth(OUT / "scored_release_truth.local.json", scoped)
        cohort_path = OUT / "release_cohort.local.json"
        if cohort_path.exists() and load(cohort_path) != cohort:
            raise ValueError("IMMUTABLE_RELEASE_COHORT_CHANGED")
        write_immutable("release_cohort.local.json", cohort)
        execution = {
            "truth_sha256": scoped["truth_sha256"],
            "raw_sha256": raw.get("snapshot_sha256"),
            "final_sha256": final.get("snapshot_sha256"),
            "cohort_sha256": cohort["cohort_sha256"],
        }
        ledger = OUT / "holdout_execution_ledger.local.json"
        if ledger.exists() and load(ledger) != execution:
            raise ValueError("FROZEN_HOLDOUT_EXECUTION_CHANGED")
        scoring = score_release(scoped, raw, final, cohort)
        write_immutable("holdout_execution_ledger.local.json", execution)
        write("release_scores.json", scoring)
    latency = load(ROOT / "docs/closure/production_latency_results.json").get(
        "fresh_qualification", {}
    )
    cost_config = load(OUT / "pricing.local.json")
    rates = Rates(
        **{
            k: Decimal(str(v)) if v is not None else None
            for k, v in cost_config.get("rates", {}).items()
        }
    )
    measured_workload = load(OUT / "measured_workload.local.json")
    if measured_workload:
        for key in ("pages_per_busy_hour", "utilization"):
            if measured_workload.get(key) is not None:
                measured_workload[key] = Decimal(str(measured_workload[key]))
        workload = Workload(**measured_workload)
    else:
        workload = Workload(
            pages=100, claims=0
        )  # Measured cached replay, no invented claim denominator.
    cost = calculate(workload, rates)
    cost["scope"] = (
        "MEASURED_DEPLOYMENT_WORKLOAD"
        if measured_workload
        else "MEASURED_100_PAGE_CACHED_REPLAY_NOT_RELEASE_WORKLOAD"
    )
    write("cost_model_report.json", cost)
    operational = load(OUT / "deployment_operational_evidence.local.json", {"status": "INCOMPLETE"})
    operational_pass = (
        operational.get("scope") == "PRODUCTION_DEPLOYMENT"
        and operational.get("status") == "PASS"
        and bool(operational.get("run_id"))
        and operational.get("truth_sha256") == scoring.get("truth_sha256")
        and scoring.get("status") == "EVALUATED"
        and truth.get("status") == "FROZEN"
        and all(
            operational.get(k) is True
            for k in (
                "database_and_events_passed",
                "load_and_keda_passed",
                "failure_injection_passed",
                "security_passed",
                "outbox_idempotency_passed",
                "revalidation_passed",
                "no_duplicate_output",
                "restart_resume_passed",
            )
        )
    )
    target_latency = load(OUT / "deployment_latency.local.json")
    latency_pass = (
        target_latency.get("scope") == "COMPLETE_PRODUCTION_PAGE_PATH"
        and target_latency.get("semantic_equality") is True
        and target_latency.get("warm_repetitions", 0) >= 3
        and type(target_latency.get("median_warm_p95_ms")) in (int, float)
        and 0 < target_latency["median_warm_p95_ms"] <= 5000
    )
    if target_latency:
        latency = {**latency, **target_latency}
    cost_pass = (
        bool(measured_workload)
        and cost["pricing_status"] == "CONFIGURED"
        and cost["paid_ai_gate"] == "PASS"
    )
    requirements = [
        (
            "B1",
            "BLIND_REVIEW",
            progress["pages_reviewed"],
            150,
            "HUMAN_REVIEW",
            "Complete both independent source-only reviews and adjudicate disagreements.",
            progress["pages_reviewed"] == 150,
        ),
        (
            "B2",
            "SOURCE_CDP_PAGE_BINDING",
            binding.get("binding_coverage", 0),
            1,
            "CDP",
            "Verified source hashes/frame lineage; establish complete claim membership through governed boundary review.",
            binding.get("binding_coverage") == 1,
        ),
        (
            "B3",
            "TRUTH_FREEZE",
            truth["status"],
            "FROZEN",
            "QUALIFICATION",
            "Supply verified reviewer registry and independent review conclusions.",
            truth["status"] == "FROZEN",
        ),
        (
            "B4",
            "FINAL_ACCURACY",
            scoring["post_hitl"].get("final_accuracy"),
            0.99,
            "QUALIFICATION",
            "Score frozen same-denominator actual canonical outputs after HITL/revalidation.",
            False,
        ),
        (
            "B5",
            "CRITICAL_ACCURACY",
            scoring["post_hitl"].get("critical_accuracy"),
            0.995,
            "QUALIFICATION",
            "Complete governed truth and post-HITL execution.",
            False,
        ),
        (
            "B6",
            "ACCEPTED_PRECISION",
            scoring["raw"].get("accepted_precision"),
            0.995,
            "QUALIFICATION",
            "Score raw accepted and critical accepted fields against independent truth.",
            False,
        ),
        (
            "B7",
            "CRITICAL_FALSE_ACCEPTS",
            scoring["raw"].get("critical_false_accepts"),
            0,
            "QUALIFICATION",
            "Score raw critical accepts against independent truth.",
            False,
        ),
        (
            "B8",
            "FIELD_HITL",
            scoring["raw"].get("field_hitl"),
            0.1,
            "QUALIFICATION",
            "Measure raw review-required fields; do not substitute post-HITL accuracy.",
            False,
        ),
        (
            "B9",
            "CLAIM_HITL",
            scoring["raw"].get("claim_hitl"),
            0.2,
            "QUALIFICATION",
            "Supply complete governed claim membership; score all claim pages.",
            False,
        ),
        (
            "B10",
            "STP",
            scoring["raw"].get("stp"),
            0.8,
            "QUALIFICATION",
            "Score raw STP_SAFE claims without human corrections.",
            False,
        ),
        (
            "B11",
            "LATENCY",
            latency.get("median_warm_p95_ms"),
            5000,
            "DEPLOYMENT_RUNTIME",
            "Run production_latency_qualification --target-output on target hardware, then complete production path qualification.",
            latency_pass,
        ),
        (
            "B12",
            "COST",
            cost["pricing_status"],
            "CONFIGURED",
            "INFRA_FINOPS",
            "Supply actual compute/GPU, storage/IO and used provider rates plus observed utilization.",
            cost_pass,
        ),
        (
            "B13",
            "OPERATIONAL_EVIDENCE",
            operational.get("status"),
            "PASS",
            "DEPLOYMENT",
            "Run reviewed claims on the governed deployment: database/broker, authority, load, failure recovery and security evidence.",
            operational_pass,
        ),
    ]
    blockers = []
    for identifier, gate, current, target, owner, action, closed in requirements:
        if identifier in {"B4", "B5", "B6", "B10"} and current is not None:
            closed = current >= target
        if identifier in {"B7", "B8", "B9"} and current is not None:
            closed = current <= target
        if identifier == "B6":
            critical = scoring["raw"].get("critical_accepted_precision")
            closed = closed and critical is not None and critical >= 0.995
        blockers.append(
            {
                "blocker_id": identifier,
                "gate": gate,
                "current_value": current,
                "target": target,
                "owner": owner,
                "internal_or_external": "INTERNAL" if identifier == "B2" else "EXTERNAL",
                "automatable": identifier not in {"B1", "B12"},
                "next_action": action,
                "status": "CLOSED" if closed else "EXTERNAL_INPUT_REQUIRED",
                "evidence_artifact": "source_binding_summary.json"
                if identifier == "B2"
                else "review_completion_status.json"
                if identifier == "B1"
                else "release_truth_manifest.json"
                if identifier == "B3"
                else "cost_model_report.json"
                if identifier == "B12"
                else "operational_readiness.json"
                if identifier == "B13"
                else "docs/closure/production_latency_results.json"
                if identifier == "B11"
                else "release_scores.json",
            }
        )
    all_closed = all(b["status"] == "CLOSED" for b in blockers)
    report = {
        "status": "PRODUCTION_CANDIDATE" if all_closed else "EXTERNAL_INPUT_REQUIRED",
        "release_decision": "GO" if all_closed else "NO_GO",
        "blockers": blockers,
        "page_binding": binding,
        "review": progress,
        "scoring": scoring,
        "cost": cost,
        "latency_status": "PASS" if latency_pass else "HOST_LATENCY_LIMIT_MEASURED",
        "latency": latency,
        "release_authority_enabled": False,
        "shadow_500_holdout_promoted": False,
        "automatic_refresh": True,
        "input_digest": content_digest(
            {
                "reviews": rows,
                "registry": registry,
                "binding": binding,
                "membership": membership,
                "raw": raw,
                "final": final,
            }
        ),
    }
    write("closure_tracker.json", report)
    from evaluation.final_qualification import build

    build()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            result = refresh()
        except (ValueError, KeyError, OSError, TypeError):
            if not args.watch:
                raise
            previous = load(OUT / "closure_tracker.json")
            if previous:
                previous["status"] = "EXTERNAL_INPUT_REQUIRED"
                previous["release_decision"] = "NO_GO"
                for blocker in previous["blockers"]:
                    blocker["status"] = "IN_PROGRESS"
                    blocker["next_action"] = (
                        "Repair invalid or incomplete governed input; qualification will retry."
                    )
                write("closure_tracker.json", previous)
                from evaluation.final_qualification import build

                build()
            # Do not emit source values, reviewer identities or partially written inputs.
            print("QUALIFICATION_INPUT_INVALID_OR_INCOMPLETE; retrying", flush=True)
            time.sleep(5)
            continue
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "binding": result["page_binding"].get("binding_coverage"),
                    "reviewed": result["review"]["pages_reviewed"],
                }
            ),
            flush=True,
        )
        if not args.watch:
            break
        time.sleep(5)
