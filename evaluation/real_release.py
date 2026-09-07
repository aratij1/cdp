"""Publish real qualification aggregates from the running governed control plane."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from packages.real_data_evaluation.blind_workflow import BlindReviewStore, content_digest
from packages.real_data_evaluation.real_release_integrity import (
    claim_binding_report,
    claim_execution_manifest,
    review_checkpoint_integrity,
)
from packages.real_data_evaluation.real_scorecard import build_scorecard

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path, default=None):
    return json.loads(path.read_text()) if path.is_file() else ({} if default is None else default)


def publish(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def reconcile(scoring: dict, binding: dict) -> dict:
    raw, post = scoring.get("raw", {}), scoring.get("post_hitl", {})
    if not raw:
        return {"status": "NOT_EVALUABLE", "eligible_claims": None, "scored_fields": None}
    claims = raw.get("eligible_claims")
    parts = [raw.get(k) for k in ("stp_claims", "hitl_claims", "unresolved_claims")]
    counts_valid = type(claims) is int and all(type(v) is int and v >= 0 for v in parts)
    raw_equal = counts_valid and sum(parts) == claims
    final_equal = (
        not post
        or sum(post.get(k, -1) for k in ("true_stp_claims", "hitl_closed_claims", "unresolved"))
        == claims
    )
    fields = raw.get("accuracy_denominator")
    field_equal = fields == scoring.get("fields") == raw.get("field_hitl_denominator")
    accepted, hitl = raw.get("accepted_precision_denominator"), raw.get("field_hitl_numerator")
    field_equal = (
        field_equal and type(accepted) is int and type(hitl) is int and accepted + hitl <= fields
    )
    status = (
        "PASS"
        if raw_equal
        and final_equal
        and field_equal
        and binding.get("eligible_claim_denominator") == claims
        else "FAIL"
    )
    return {
        "status": status,
        "pages": scoring.get("pages"),
        "eligible_claims": claims,
        "scored_fields": fields,
        "critical_fields": raw.get("critical_accuracy_denominator"),
        "accepted_fields": accepted,
        "hitl_fields": hitl,
        "other_field_outcomes": fields - accepted - hitl if field_equal else None,
        "stp_claims": parts[0],
        "hitl_claims": parts[1],
        "unresolved_without_human_route": parts[2],
        "excluded_claims": binding.get("claims_excluded"),
        "raw_claim_partition_matches": bool(raw_equal),
        "final_claim_partition_matches": bool(final_equal),
        "field_denominators_match": bool(field_equal),
    }


VALIDATED_MODULES = (
    "evaluation/real_release.py",
    "evaluation/claim_inventory.py",
    "evaluation/owner_sequence_membership.py",
    "evaluation/governed_30_reference.py",
    "evaluation/governed_30_scorecard.py",
    "evaluation/governed_30_execution.py",
    "evaluation/governed_30_revalidation.py",
    "evaluation/blind_field_metrics.py",
    "evaluation/blind_lineage_recovery.py",
    "evaluation/two_track_isolation.py",
    "evaluation/two_track_closure.py",
    "evaluation/annotation_app/qualification_review.py",
    "evaluation/qualification_closure.py",
    "evaluation/deployment_control_executor.py",
    "packages/real_data_evaluation/blind_workflow.py",
    "packages/real_data_evaluation/release_truth.py",
    "packages/real_data_evaluation/release_cohort.py",
    "packages/real_data_evaluation/release_scoring.py",
    "packages/real_data_evaluation/real_release_integrity.py",
    "packages/real_data_evaluation/real_scorecard.py",
)


def validated_machinery(root: Path, private: Path) -> dict:
    evidence = load(private / "measurement_validation.local.json")
    hashes = evidence.get("code_sha256", {})
    if evidence.get("status") != "PASS" or set(hashes) != set(VALIDATED_MODULES):
        return {}
    if any(
        not (root / name).is_file()
        or hashlib.sha256((root / name).read_bytes()).hexdigest() != hashes[name]
        for name in VALIDATED_MODULES
    ):
        return {}
    return evidence.get("checks", {})


def build(root: Path = ROOT) -> dict:
    private = root / "evaluation_results/qualification_closure"
    out = root / "evaluation_results/real_release"
    closure = load(private / "closure_tracker.json")
    candidate = load(private / "candidate_freeze.local.json")
    original_membership = load(private / "claim_membership.local.json")
    cohort = load(private / "release_cohort.local.json")
    membership = cohort or original_membership
    truth = load(private / "scored_release_truth.local.json")
    raw = load(private / "raw_predictions.local.json")
    bindings = load(private / "source_page_bindings.local.json").get("bindings", [])
    binding = claim_binding_report(membership, bindings, truth, raw)
    final = load(private / "post_hitl_predictions.local.json")
    execution_snapshot = final or raw
    if closure.get("qualification_input_status") == "INVALID_OR_INCOMPLETE":
        execution_snapshot = {}
    execution = claim_execution_manifest(
        original_membership or membership,
        bindings,
        truth,
        execution_snapshot,
        candidate,
        excluded=cohort.get("excluded_claims", {}),
        stage="POST_HITL" if final else "RAW",
    )
    publish(out / "claim_execution_manifest.json", execution)
    binding["claims_considered_for_scoring"] = binding["claims_discovered"]
    excluded = len(cohort.get("excluded_claims", {}))
    binding["claims_excluded_before_scoring"] = excluded
    binding["claims_discovered"] += excluded
    binding["claims_excluded"] += excluded
    binding["claim_binding_coverage"] = (
        binding["claims_exactly_bound"] / binding["claims_discovered"]
        if binding["claims_discovered"]
        else None
    )
    if closure.get("qualification_input_status") == "INVALID_OR_INCOMPLETE":
        binding["status"] = "NOT_EVALUABLE"
    card = build_scorecard(closure, binding, candidate)
    scoring = closure.get("scoring", {}) if card["real_metrics_evaluable"] else {}
    reconciliation = reconcile(scoring, binding)
    if reconciliation["status"] == "FAIL":
        card = build_scorecard({**closure, "scoring": {}}, binding, candidate)
        card["integrity_error"] = "DENOMINATOR_RECONCILIATION_FAILED"
        scoring = {}
    progress = dict(closure.get("review", {}))
    progress["pages_remaining"] = progress.get("pages_total", 150) - progress.get(
        "pages_reviewed", 0
    )
    progress["trusted_fields"] = progress.get("trusted_fields", progress.get("trusted_labels", 0))
    progress["trusted_claims"] = binding.get("claims_exactly_bound", 0)
    source_rows = load(private / "blind_source_views.local.json", [])
    sources = {r["page_id"]: r for r in source_rows}
    store = BlindReviewStore(private / "blind_reviews.sqlite3")
    checkpoints = review_checkpoint_integrity(
        progress,
        store.completed(),
        sources,
        load(private / "reviewer_registry.local.json"),
        store.adjudications(),
        machinery=validated_machinery(root, private),
    )
    inventory = load(out / "claim_inventory.json")
    checkpoints.update(
        claim_binding_coverage=(
            inventory.get("claims_exactly_bound", 0) / inventory["claims_discovered"]
            if inventory.get("claims_discovered")
            else None
        ),
        trusted_field_count=progress.get("trusted_fields", 0),
        critical_dual_reviewed=progress.get("critical_fields_dual_reviewed", 0),
        claim_execution_ready=sum(
            c.get("raw_scoring_ready") is True for c in execution.get("claims", [])
        ),
    )
    publish(out / "review_progress.json", progress)
    publish(out / "review_checkpoints.json", checkpoints)
    binding["owner_confirmed_source_membership"] = inventory.get(
        "owner_confirmed_source_membership", {})
    publish(out / "claim_binding_report.json", binding)
    for milestone in checkpoints["milestones_reached"]:
        path = out / f"review_checkpoint_{milestone}.json"
        if not path.exists():
            publish(
                path,
                {
                    **checkpoints,
                    "checkpoint": milestone,
                    "observed_at": datetime.now(UTC).isoformat(),
                },
            )
    raw_metrics, post_metrics = scoring.get("raw", {}), scoring.get("post_hitl", {})
    files = {
        "raw_accuracy.json": ("raw", ("accuracy", "noncritical_accuracy")),
        "critical_accuracy.json": ("raw", ("critical_accuracy",)),
        "accepted_precision.json": ("raw", ("accepted_precision", "critical_accepted_precision")),
        "field_hitl.json": ("raw", ("field_hitl", "critical_field_hitl", "noncritical_field_hitl")),
        "claim_hitl.json": ("raw", ("claim_hitl",)),
        "stp.json": ("raw", ("stp",)),
        "post_hitl_accuracy.json": ("post_hitl", ("final_accuracy", "critical_accuracy")),
        "false_accepts.json": ("raw", ("critical_false_accepts",)),
    }
    for filename, (stage, names) in files.items():
        data = raw_metrics if stage == "raw" else post_metrics
        payload: dict = {"status": "EVALUATED" if data else "NOT_EVALUABLE", "stage": stage}
        for name in names:
            payload[name] = {
                "numerator": data.get(name + "_numerator"),
                "denominator": data.get(name + "_denominator"),
                "value": data.get(name),
            }
        if filename == "field_hitl.json":
            payload["ownership"] = data.get("hitl_ownership", {})
        if filename == "claim_hitl.json":
            payload["blocker_combinations"] = data.get("claim_blocker_combinations", {})
        publish(out / filename, payload)
    publish(out / "field_breakdown.json", scoring.get("breakdowns", {"status": "NOT_EVALUABLE"}))
    publish(
        out / "claim_breakdown.json",
        {
            "raw": {
                k: raw_metrics.get(k)
                for k in ("eligible_claims", "stp_claims", "hitl_claims", "unresolved_claims")
            },
            "post_hitl": post_metrics,
            "excluded_claims": binding.get("claims_excluded"),
            "status": "EVALUATED" if raw_metrics else "NOT_EVALUABLE",
        },
    )
    publish(out / "denominator_reconciliation.json", reconciliation)
    publish(
        out / "confidence_intervals.json",
        {"intervals": card["confidence_intervals"], "scope": card["confidence_interval_scope"]},
    )
    publish(
        out / "error_analysis.json",
        {
            "status": "EVALUATED" if scoring else "NOT_EVALUABLE",
            "categories": scoring.get("error_analysis", {}),
            "tuning_permitted": False,
        },
    )
    frozen = bool(
        truth.get("status") == "FROZEN"
        and cohort
        and candidate
        and closure.get("freeze_integrity", {}).get("status") == "PASS"
    )
    manifest = {
        "status": "FROZEN" if frozen else "NOT_FROZEN",
        "truth_version": "REAL_RELEASE_V1" if frozen else None,
        "commit_sha": candidate.get("candidate_commit_sha"),
        "cohort_hash": cohort.get("cohort_sha256"),
        "binding_sha256": content_digest(bindings) if frozen else None,
        "claim_membership_sha256": content_digest(membership) if frozen else None,
        "truth_sha256": truth.get("truth_sha256") if frozen else None,
        "claims": len(cohort.get("claims", {})) if frozen else 0,
        "pages": len({r["page_id"] for r in truth.get("records", [])}) if frozen else 0,
        "fields": len(truth.get("records", [])) if frozen else 0,
        "critical_fields": sum(r.get("critical") is True for r in truth.get("records", []))
        if frozen
        else 0,
    }
    prior = load(out / "release_truth_manifest.json")
    if frozen:
        manifest.update(
            package_ids=sorted({content_digest(r["package_id"]) for r in truth["records"]}),
            claim_ids=sorted(content_digest(c) for c in cohort["claims"]),
            page_ids=sorted({content_digest(r["page_id"]) for r in truth["records"]}),
            review_provenance=sorted({r["review_digest"] for r in truth["records"]}),
            adjudication_provenance=sorted(
                {r["adjudication_digest"] for r in truth["records"] if r.get("adjudication_digest")}
            ),
        )
        manifest["created_at"] = prior.get("created_at") or datetime.now(UTC).isoformat()
        manifest["content_sha256"] = content_digest(manifest)
        if prior.get("status") == "FROZEN" and prior != manifest:
            raise ValueError("FROZEN_REAL_RELEASE_MANIFEST_CHANGED")
    # Frozen truth is historical immutable evidence even when current inputs fail.
    if prior.get("status") != "FROZEN":
        publish(out / "release_truth_manifest.json", manifest)
    card["frozen_truth_available"] = frozen or prior.get("status") == "FROZEN"
    card["truth_usable_for_current_run"] = bool(frozen and card["real_metrics_evaluable"])
    publish(
        out / "cost_usage.json",
        {
            "production": {
                k: v
                for k, v in load(private / "measured_workload.local.json").items()
                if k
                in {
                    "pages",
                    "claims",
                    "pages_per_busy_hour",
                    "utilization",
                    "gpu_used",
                    "paid_ocr_calls",
                    "llm_input_tokens",
                    "llm_output_tokens",
                    "authority_calls",
                }
            }
            or {"status": "NOT_AVAILABLE"},
            "cost": closure.get("cost", {}),
            "cached_replay": {
                "pages": 100,
                "new_ocr_calls": 0,
                "llm_calls": 0,
                "paid_ai_tokens": 0,
                "paid_ai_cost_per_page": "0",
                "authority_calls_per_claim": None,
                "scope": "ENGINEERING_CACHED_REPLAY_ONLY",
            },
        },
    )
    publish(out / "release_scorecard.json", card)
    lines = [
        "# REAL CDP QUALIFICATION",
        "",
        "STATUS: **" + card["status"] + "**",
        "",
        "Candidate: `" + str(card["candidate_commit_sha"]) + "`",
        "",
        "| Metric | Numerator | Denominator | Value | Target | Status |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in card["rows"]:
        lines.append(
            "| "
            + " | ".join(
                str(row.get(k)) if row.get(k) is not None else "NOT_EVALUABLE"
                for k in ("metric", "numerator", "denominator", "value", "target", "status")
            )
            + " |"
        )
    lines += [
        "",
        "Raw accuracy and critical-field HITL have no separate threshold in the frozen contract; NOT_GATED does not waive a release gate.",
        "",
        card["confidence_interval_scope"],
        "",
        "FINAL DECISION: **" + card["final_decision"] + "**",
        "",
    ]
    (out / "release_scorecard.md").write_text("\n".join(lines))
    from evaluation.two_track_closure import build as refresh_two_tracks

    refresh_two_tracks(root)
    return card


if __name__ == "__main__":
    from evaluation.qualification_closure import refresh

    refresh()
    print(json.dumps(build(), indent=2))
