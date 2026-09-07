"""Finite closure queue; refresh on review completion and watch for governed inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from evaluation.qualification_latency import target_latency_evidence
from packages.real_data_evaluation.blind_workflow import (
    BlindReviewStore,
    content_digest,
    review_progress,
)
from packages.real_data_evaluation.closure_control import deployment_evidence, freeze_prerequisites
from packages.real_data_evaluation.qualification_cost import Rates, Workload, calculate
from packages.real_data_evaluation.qualification_jobs import advance
from packages.real_data_evaluation.release_cohort import build_release_cohort
from packages.real_data_evaluation.release_scoring import score_release
from packages.real_data_evaluation.release_truth import (
    finalize_reviews,
    freeze_truth,
    trusted_review_counts,
)

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
    from evaluation.claim_inventory import build as build_claim_inventory
    from evaluation.track_b_inputs import prepare

    inputs = prepare(ROOT)
    inventory = build_claim_inventory(ROOT)
    binding = load(OUT / "source_binding_summary.json")
    source_rows = load(OUT / "blind_source_views.local.json", [])
    sources = {r["page_id"]: r for r in source_rows}
    rows = BlindReviewStore(OUT / "blind_reviews.sqlite3").completed()
    registry = inputs["registry"]
    progress = review_progress(
        rows,
        {p: r["rendered_page_sha256"] for p, r in sources.items()},
        frozenset(registry.get("authorized_reviewers", [])),
    )
    adjudications = BlindReviewStore(OUT / "blind_reviews.sqlite3").adjudications()
    from evaluation.track_b_review_provenance import verify as verify_review_provenance

    if (
        ROOT / "config/qualification/reviewer_registry.yaml"
    ).exists() and not verify_review_provenance(OUT, rows, adjudications):
        raise ValueError("GOVERNED_REVIEW_VERSION_PROVENANCE_REQUIRED")
    reservation = load(
        ROOT / "evaluation_results/production_closure/release/package_reservation.local.json"
    )
    all_binding_payload = load(OUT / "source_page_bindings.local.json")
    manifest_path = ROOT / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    manifest_hash = (
        hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path.exists() else ""
    )
    integrity = freeze_prerequisites(
        sources,
        all_binding_payload,
        reservation,
        manifest_hash,
        load(manifest_path) if manifest_path.exists() else None,
    )
    write("freeze_prerequisites.json", integrity)
    if integrity["status"] == "PASS":
        write_immutable(
            "binding_reservation_freeze.local.json",
            {
                "bindings_sha256": content_digest(all_binding_payload),
                "reservation_sha256": content_digest(reservation),
                "manifest_sha256": manifest_hash,
            },
        )
    truth = (
        finalize_reviews(rows, sources, registry, adjudications)
        if integrity["status"] == "PASS" and inventory.get("membership_ready") is True
        else {
            "status": "NOT_FROZEN",
            "reason": "EXACT_MEMBERSHIP_BINDING_AND_PACKAGE_RESERVATION_REQUIRED",
            "records": [],
        }
    )
    progress["adjudications"] = len(adjudications)
    progress.update(trusted_review_counts(rows, sources, registry, adjudications))
    if truth["status"] == "FROZEN":
        freeze_truth(OUT / "release_truth_manifest.local.json", truth)
        write_immutable(
            "track_b_truth_freeze_receipt.json",
            {
                "candidate_commit_sha": load(OUT / "candidate_freeze.local.json").get(
                    "candidate_commit_sha"
                ),
                "cohort_hash": manifest_hash,
                "membership_hash": content_digest(load(OUT / "claim_membership.local.json")),
                "truth_hash": truth["truth_sha256"],
                "claims": inventory["claims_exactly_bound"],
                "pages": len(sources),
                "fields": len(truth["records"]),
                "critical_fields": len(truth["records"]),
                "review_provenance_hash": content_digest(rows),
                "adjudication_provenance_hash": content_digest(adjudications),
                "package_leakage": 0,
            },
        )
        progress["trusted_labels"] = len(truth["records"])
        progress["truth_status"] = "FROZEN"
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
    deployment_config = inputs["deployment"]
    candidate_freeze = load(OUT / "candidate_freeze.local.json")
    execution_status = {
        "TARGET_LATENCY": advance(
            OUT, "TARGET_LATENCY", {"baseline": "retained_frozen_12_page_cohort"}, deployment_config
        ),
        "OPERATIONAL_PREFLIGHT": advance(
            OUT,
            "OPERATIONAL_PREFLIGHT",
            {"blind_manifest_sha256": manifest_hash, "scope": "PRE_TRUTH_DEPLOYMENT_CHECKS"},
            deployment_config,
        ),
        "OPERATIONAL": {"status": "NOT_AVAILABLE", "reason": "GOVERNED_RELEASE_COHORT_REQUIRED"},
        "RAW": {"status": "NOT_AVAILABLE", "reason": "TRUTH_AND_COMPLETE_MEMBERSHIP_REQUIRED"},
        "HITL_FINAL": {"status": "NOT_AVAILABLE", "reason": "RAW_EXECUTION_REQUIRED"},
    }
    raw = load(OUT / "raw_predictions.local.json")
    final = load(OUT / "post_hitl_predictions.local.json")
    scoring: dict = {"status": "NOT_EVALUABLE", "raw": {}, "post_hitl": {}}
    if (
        truth["status"] == "FROZEN"
        and integrity["status"] == "PASS"
        and membership
        and (not candidate_freeze or inventory.get("membership_ready") is True)
    ):
        scoped, cohort = build_release_cohort(
            truth, all_binding_payload["bindings"], membership, reservation["assignments"]
        )
        freeze_truth(OUT / "scored_release_truth.local.json", scoped)
        write_immutable("release_cohort.local.json", cohort)
        execution_inputs = {
            "truth_sha256": scoped["truth_sha256"],
            "cohort_sha256": cohort["cohort_sha256"],
        }
        execution_status["RAW"] = advance(OUT, "RAW", execution_inputs, deployment_config)
        execution_status["OPERATIONAL"] = advance(
            OUT, "OPERATIONAL", execution_inputs, deployment_config
        )
        raw = load(OUT / "raw_predictions.local.json")
        if raw:
            if candidate_freeze:
                from packages.real_data_evaluation.real_release_integrity import (
                    claim_binding_report,
                )

                if raw.get("candidate_commit_sha") != candidate_freeze["candidate_commit_sha"]:
                    raise ValueError("FROZEN_CANDIDATE_EXECUTION_REQUIRED")
                if (
                    claim_binding_report(cohort, all_binding_payload["bindings"], scoped, raw)[
                        "status"
                    ]
                    != "PASS"
                ):
                    raise ValueError("EXACT_COMPLETE_CLAIM_BINDING_REQUIRED")
            scoring = score_release(scoped, raw, None, cohort)
            scoring["candidate_commit_sha"] = raw.get("candidate_commit_sha")
            write_immutable(
                "raw_execution_ledger.local.json",
                {**execution_inputs, "raw_sha256": raw["snapshot_sha256"]},
            )
            execution_status["HITL_FINAL"] = advance(
                OUT,
                "HITL_FINAL",
                {**execution_inputs, "raw_sha256": raw["snapshot_sha256"]},
                deployment_config,
            )
            final = load(OUT / "post_hitl_predictions.local.json")
            if final:
                if (
                    candidate_freeze
                    and final.get("candidate_commit_sha")
                    != candidate_freeze["candidate_commit_sha"]
                ):
                    raise ValueError("FINAL_FROZEN_CANDIDATE_EXECUTION_REQUIRED")
                scoring = score_release(scoped, raw, final, cohort)
                scoring["candidate_commit_sha"] = raw.get("candidate_commit_sha")
                write_immutable(
                    "holdout_execution_ledger.local.json",
                    {
                        **execution_inputs,
                        "raw_sha256": raw["snapshot_sha256"],
                        "final_sha256": final["snapshot_sha256"],
                    },
                )
            write("release_scores.json", scoring)
    write("execution_status.json", execution_status)
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
    operational_payload = load(OUT / "deployment_operational_evidence.local.json")
    operational = deployment_evidence(
        operational_payload, raw.get("configuration_sha256"), scoring.get("truth_sha256"), OUT
    )
    if (ROOT / "docs/qualification/track_b_completion/track_a_freeze.json").exists():
        from evaluation.track_b_preflight import operational_extensions

        operational = operational_extensions(operational_payload, operational, OUT)
    operational_pass = operational["status"] == "PASS"
    write("deployment_status.json", operational)
    target_latency = load(OUT / "deployment_latency.local.json")
    latency_validation = target_latency_evidence(
        target_latency,
        load(ROOT / "evaluation_results/production_closure/latency/qualification.local.json"),
        deployment_config.get("cdp_services", {}).get("pipeline_configuration_sha256")
        or raw.get("configuration_sha256"),
        deployment_config.get("deployment_id"),
        deployment_config.get("cdp_services", {}).get("ub04_canary_fingerprints", {}),
    )
    write("target_latency_status.json", latency_validation)
    latency_pass = latency_validation["status"] == "PASS"
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
            progress["pages_reviewed"] == len(sources) and truth["status"] == "FROZEN",
        ),
        (
            "B2",
            "SOURCE_CDP_PAGE_BINDING",
            binding.get("binding_coverage", 0),
            1,
            "CDP",
            "Verified source hashes/frame lineage; establish complete claim membership through governed boundary review.",
            integrity["exact_binding"],
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
    requirements.extend(
        [
            (
                "B14",
                "SECURITY",
                operational["security_status"],
                "PASS",
                "DEPLOYMENT_SECURITY",
                "Supply governed authorization, secrets, audit logging and PHI-control evidence.",
                operational["security_status"] == "PASS",
            ),
            (
                "B15",
                "PACKAGE_LEAKAGE",
                integrity["package_leakage"],
                0,
                "QUALIFICATION",
                "Keep the frozen package reservation and whole-claim release cohort disjoint.",
                integrity["status"] == "PASS",
            ),
        ]
    )
    requirements.append(
        (
            "B16",
            "CRITICAL_ACCEPTED_PRECISION",
            scoring["raw"].get("critical_accepted_precision"),
            0.995,
            "QUALIFICATION",
            "Score raw critical accepted fields against independently frozen truth.",
            False,
        )
    )
    blockers = []
    for identifier, gate, current, target, owner, action, closed in requirements:
        if identifier in {"B4", "B5", "B6", "B10", "B16"} and current is not None:
            closed = current >= target
        if identifier in {"B7", "B8", "B9"} and current is not None:
            closed = current <= target
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
                "status": "PASS"
                if closed
                else "FAIL"
                if (
                    identifier in {"B4", "B5", "B6", "B7", "B8", "B9", "B10", "B16"}
                    and current is not None
                    or identifier in {"B13", "B14"}
                    and current == "FAIL"
                    or identifier == "B11"
                    and latency_validation["status"] == "FAIL"
                    or identifier == "B12"
                    and bool(measured_workload)
                    and cost["paid_ai_gate"] == "FAIL"
                    or identifier in {"B2", "B15"}
                    and bool(sources)
                    and bool(all_binding_payload)
                    and integrity["status"] == "FAIL"
                )
                else "NOT_EVALUABLE"
                if identifier in {"B4", "B5", "B6", "B7", "B8", "B9", "B10", "B16"}
                else "IN_PROGRESS"
                if identifier == "B1" and progress["pages_reviewed"]
                else "EXTERNAL_INPUT_REQUIRED",
                "evidence_artifact": "source_binding_summary.json"
                if identifier == "B2"
                else "review_completion_status.json"
                if identifier == "B1"
                else "release_truth_manifest.json"
                if identifier == "B3"
                else "cost_model_report.json"
                if identifier == "B12"
                else "deployment_status.json"
                if identifier in {"B13", "B14"}
                else "freeze_prerequisites.json"
                if identifier == "B15"
                else "target_latency_status.json"
                if identifier == "B11"
                else "release_scores.json",
            }
        )
    all_closed = all(b["status"] == "PASS" for b in blockers)
    measured_failure = any(b["status"] == "FAIL" for b in blockers)
    deployment_approval = load(OUT / "deployment_approval.local.json")
    approved = (
        all_closed
        and deployment_approval.get("approved") is True
        and bool(deployment_approval.get("approval_reference"))
        and deployment_approval.get("truth_sha256") == scoring.get("truth_sha256")
        and deployment_approval.get("configuration_sha256") == raw.get("configuration_sha256")
    )
    report = {
        "status": "PRODUCTION_READY"
        if approved
        else "PRODUCTION_CANDIDATE"
        if all_closed
        else "NO_GO"
        if measured_failure
        else "EXTERNAL_INPUT_REQUIRED",
        "release_decision": "GO" if all_closed else "NO_GO",
        "blockers": blockers,
        "page_binding": binding,
        "review": progress,
        "execution": execution_status,
        "operational": operational,
        "freeze_integrity": integrity,
        "scoring": scoring,
        "cost": cost,
        "latency_status": latency_validation["status"],
        "target_latency": latency_validation,
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
    from evaluation.track_b_report import build as build_track_b_report

    build_track_b_report(ROOT, report)
    write("closure_tracker.json", report)
    write("release_blocker_board.json", {"status": report["status"], "gates": blockers})
    from evaluation.final_qualification import build

    build()
    from evaluation.real_release import build as build_real_release

    build_real_release(ROOT)
    return report


def invalidate() -> None:
    """Withdraw stale passing reports when a governed input becomes invalid."""
    previous = load(OUT / "closure_tracker.json")
    if not previous:
        return
    previous["status"] = "EXTERNAL_INPUT_REQUIRED"
    previous["release_decision"] = "NO_GO"
    previous["scoring"] = {"status": "NOT_EVALUABLE", "raw": {}, "post_hitl": {}}
    previous["operational"] = {"status": "NOT_AVAILABLE", "reason": "INPUT_VALIDATION_FAILED"}
    previous["execution"] = {"status": "NOT_AVAILABLE", "reason": "INPUT_VALIDATION_FAILED"}
    previous["latency_status"] = "NOT_AVAILABLE"
    previous["target_latency"] = {"status": "NOT_AVAILABLE"}
    previous["qualification_input_status"] = "INVALID_OR_INCOMPLETE"
    for blocker in previous["blockers"]:
        blocker["status"] = "NOT_EVALUABLE"
        blocker["current_value"] = None
        blocker["next_action"] = "Repair invalid governed input; qualification will retry."
    write("release_scores.json", previous["scoring"])
    write("closure_tracker.json", previous)
    write(
        "release_blocker_board.json", {"status": previous["status"], "gates": previous["blockers"]}
    )
    from evaluation.final_qualification import build

    build()
    from evaluation.real_release import build as build_real_release

    build_real_release(ROOT)


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
            invalidate()
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
