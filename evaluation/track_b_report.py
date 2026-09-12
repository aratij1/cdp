"""Aggregate-only final Track B report from the authoritative controller."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from evaluation.claim_inventory import _publish
from evaluation.track_b_inputs import CANDIDATE, current_registry, digest, read


def build(root: Path, controller: dict) -> dict:
    private = root / "evaluation_results/qualification_closure"
    out = root / "docs/qualification/track_b_completion"
    if not (out / "track_a_freeze.json").exists():
        return {}
    membership = read(root / "evaluation_results/real_release/track_b_claim_membership_report.json")
    review = controller.get("review", {})
    registry = current_registry(root, private)
    truth = read(private / "release_truth_manifest.json")
    deployment = read(private / "deployment_preflight.json")
    authority_states = {
        "REVIEWER_CONTRACT": registry.get("contract_status", "MISSING"),
        "DEPLOYMENT_CONTRACT": deployment.get("contract", {}).get("status", "INVALID"),
        "CONNECTIVITY": deployment.get("connectivity", "MISSING"),
        "OWNER_APPROVAL": membership.get("owner_approval", "PENDING"),
        "EXECUTOR": {
            phase: (
                "PASS"
                if state.get("status") == "PASS"
                else "FAILED"
                if state.get("status") in {"EXECUTOR_FAILED", "FAIL"}
                else "IN_PROGRESS"
                if state.get("status") == "IN_PROGRESS"
                else "NOT_SUBMITTED"
            )
            for phase, state in controller.get("execution", {}).items()
            if isinstance(state, dict)
        },
    }
    scoring = controller.get("scoring", {})
    raw, final = scoring.get("raw", {}), scoring.get("post_hitl", {})
    freeze = read(out / "track_a_freeze.json")
    verified = sum(digest(root / p) == sha for p, sha in freeze["runtime_hashes"].items())
    metrics = {}
    for title, key in [
        ("Field accuracy", "accuracy"),
        ("Critical-field accuracy", "critical_accuracy"),
        ("Accepted precision", "accepted_precision"),
        ("Critical accepted precision", "critical_accepted_precision"),
        ("Field HITL", "field_hitl"),
        ("Claim HITL", "claim_hitl"),
        ("Declared STP", "stp"),
        ("STP_SAFE", "stp_safe"),
    ]:
        metrics[title] = {
            "numerator": raw.get(key + "_numerator"),
            "denominator": raw.get(key + "_denominator"),
            "value": raw.get(key),
            "percentage": 100 * raw[key] if raw.get(key) is not None else None,
            "status": "MEASURED" if key in raw else "NOT_EVALUABLE",
        }
    for title, key in [("False accepts", "false_accepts"),
                       ("Critical false accepts", "critical_false_accepts")]:
        metrics[title] = {"value": raw.get(key), "numerator": raw.get(key),
                          "denominator": raw.get(key + "_denominator"),
                          "percentage": None,
                          "status": "MEASURED" if raw.get(key) is not None else "NOT_EVALUABLE"}
    cost = controller.get("cost", {})
    measured_cost = cost if (private / "measured_workload.local.json").exists() else {}
    missing = []
    if membership.get("owner_approval") != "PASS":
        missing.append(
            {
                "file/config field": "evaluation_results/real_release/150_cohort_missing_membership.csv and evaluation_results/qualification_closure/membership_owner_approval.local.json: owner_id, owner_role, csv_sha256, approved_at, approval_reference, policy_id; CSV claim_alias_to_fill, document_alias, page_role, claim_page_order, membership_status, owner_confirmation, membership_provenance, owner_approved_at, claim_complete_confirmed",
                "responsible role": "Ashish Singh — source owner",
                "why required": "Complete, authoritative page-to-claim membership; not field truth.",
            }
        )
    if registry.get("identity_verified") is not True:
        missing.append(
            {
                "file/config field": "config/qualification/reviewer_registry.yaml: identity_verified, policy_id, reviewers[] with all documented assignment fields",
                "responsible role": "Authorized reviewer-registration operator",
                "why required": "Two independent reviewers and an independent adjudicator with valid scope/provenance.",
            }
        )
    if truth.get("status") != "FROZEN":
        missing.append(
            {
                "file/config field": "Existing qualification-review UI: two completed source-only reviews/page and independent adjudication reasons/results",
                "responsible role": "Registered reviewers and adjudicator",
                "why required": "Independent governed truth for real scoring.",
            }
        )
    active_deployment = read(private / "deployment_control.local.json")
    required_jobs = {"TARGET_LATENCY", "OPERATIONAL_PREFLIGHT", "RAW", "OPERATIONAL", "HITL_FINAL"}
    if deployment.get("status") != "PASS" or not required_jobs <= set(
        active_deployment.get("jobs", {})
    ):
        missing.append(
            {
                "file/config field": "config/qualification/deployment_control.yaml: qualification_host, environment, execution_provider, governed, deployment_id, approval_reference, cdp_services, jobs; deployment_attestation.local.json",
                "responsible role": "Deployment owner",
                "why required": "Designated pinned-candidate deployment and actual execution/failure-injection controls.",
            }
        )
        missing.append(
            {
                "file/config field": "Runtime variables named by database_url_env, broker_url_env, object_store_*_env, authorization_env, authority_config_env",
                "responsible role": "Deployment owner",
                "why required": "Authenticated access and actual authority-provider configuration; provision secret values outside files/logs.",
            }
        )
    if (
        not (private / "pricing.local.json").exists()
        or cost.get("pricing_status") == "NOT_CONFIGURED"
    ):
        missing.append(
            {
                "file/config field": "evaluation_results/qualification_closure/pricing.local.json and pricing_config_env",
                "responsible role": "Deployment/pricing owner",
                "why required": "Approved rates for measured paid AI and total cost.",
            }
        )
    gates = controller.get("blockers", [])
    status = "EXTERNAL_INPUT_REQUIRED" if missing else "QUALIFICATION_RUNNING"
    if not missing and any(g.get("status") == "FAIL" for g in gates):
        status = "QUALIFICATION_FAILED"
    if controller.get("status") in {"PRODUCTION_READY", "PRODUCTION_CANDIDATE"} and not missing:
        status = controller["status"]
    elif not missing and gates and all(g.get("status") == "PASS" for g in gates):
        status = (
            "PRODUCTION_READY"
            if controller.get("release_authority_enabled")
            else "PRODUCTION_CANDIDATE"
        )
    result = {
        "status": status,
        "authority_states": authority_states,
        "recorded_at": datetime.now(UTC).isoformat(),
        "track_a": {
            "commit": CANDIDATE,
            "status": "FROZEN",
            "runtime_hashes_verified": verified,
            "runtime_hashes_expected": len(freeze["runtime_hashes"]),
        },
        "membership": membership,
        "review": review,
        "truth": truth,
        "raw_metrics": metrics,
        "critical_false_accepts": raw.get("critical_false_accepts"),
        "post_hitl": final,
        "deployment": deployment,
        "latency": controller.get("target_latency", {}),
        "operational": controller.get("operational", {}),
        "cost": measured_cost,
        "field_hitl_ownership": raw.get("hitl_ownership", {}),
        "release_gates": gates,
        "next_required_action": missing,
    }
    _publish(out / "final_qualification.json", result)

    def show(value):
        return "NOT_EVALUABLE" if value is None else str(value)

    lines = [
        "# CDP TRACK-B FINAL QUALIFICATION",
        "",
        f"Final status: **{status}**",
        "",
        f"Track A: **FROZEN** at `{CANDIDATE}`; runtime hashes **{verified}/641** unchanged.",
        "",
        "## Membership",
        "",
        f"Pages: {membership.get('pages', 150)}; exact: {membership.get('exact_pages', 0)}; ambiguous: {membership.get('ambiguous_pages', 0)}; unbound: {membership.get('unbound_pages', 150)}.",
        f"Claims discovered: {membership.get('claims_discovered', 0)}; exact claims: {membership.get('exact_claims', 0)}; excluded known claims: {membership.get('excluded_claims', 0)}. Unbound pages have no inferred claim denominator.",
        f"Owner approval: {membership.get('owner_approval', 'PENDING')}.",
        "",
        "## Reviewers and review",
        "",
        f"Registry: {'CONFIGURED' if registry.get('identity_verified') else 'MISSING'}. Reviewer A/B and adjudicator: {'configured' if registry.get('identity_verified') else 'missing'}.",
        f"Reviewed pages: {review.get('pages_reviewed', 0)}; remaining: {review.get('pages_remaining', 150)}; remaining independent page reviews: {review.get('remaining_independent_page_reviews', 300)}.",
        f"Trusted fields: {review.get('trusted_fields', 0)}; critical dual-reviewed: {review.get('critical_fields_dual_reviewed', 0)}; adjudicated: {review.get('adjudications', 0)}.",
        "",
        "## Truth",
        "",
        f"Frozen: {truth.get('status', 'NOT_FROZEN')}; claims: {0 if truth.get('status') != 'FROZEN' else membership.get('exact_claims')}; pages: {truth.get('pages', 0)}; fields: {truth.get('fields', 0)}; critical fields: {truth.get('critical_fields', 0)}.",
        "Leakage: source/package isolation remains sealed; scored-claim leakage is not yet evaluable.",
        "",
        "## Real raw metrics",
        "",
        "| Metric | Numerator | Denominator | Percentage |",
        "|---|---:|---:|---:|",
    ]
    lines[4:4] = (
        ["## Control-plane authority", "", "| Authority | State |", "|---|---|"]
        + [f"| {name} | {value} |" for name, value in authority_states.items()]
        + [""]
    )
    lines += [
        f"| {name} | {show(m['numerator'])} | {show(m['denominator'])} | {show(m['percentage'])} |"
        for name, m in metrics.items()
    ]
    lines += [
        f"Critical false accepts: {show(raw.get('critical_false_accepts'))}.",
        "",
        "## Post-HITL",
        "",
        f"Final accuracy: {show(final.get('final_accuracy'))}; critical accuracy: {show(final.get('critical_accuracy'))}; HITL-closed claims: {show(final.get('hitl_closed_claims'))}; unresolved: {show(final.get('unresolved'))}.",
        "",
        "## Deployment",
        "",
        f"Control activation/preflight: {deployment.get('status', 'MISSING')}.",
        "| Check | Status |",
        "|---|---|",
    ]
    lines += [f"| {name} | {value} |" for name, value in deployment.get("checks", {}).items()]
    lines += [
        "",
        "## Latency",
        "",
        f"Warm run P95 values (milliseconds; at least three required): {show(controller.get('target_latency', {}).get('run_p95_ms'))}. Target median warm P95 <=5 sec/page. Status: {controller.get('target_latency', {}).get('status', 'NOT_MEASURED')}.",
        "",
        "## Operational",
        "",
        f"Database, broker, retry/dead-letter, restart, outbox, partial-output resume, duplicate protection, load, security and observability: {controller.get('operational', {}).get('status', 'NOT_MEASURED')} on the qualification deployment.",
        "",
        "## Cost",
        "",
        f"Paid AI/page: {measured_cost.get('paid_ai_cost_per_page') or 'NOT_CONFIGURED'}; compute/page: {measured_cost.get('compute_cost_per_page') or 'NOT_CONFIGURED'}; total/page: {measured_cost.get('total_cost_per_page') or 'NOT_CONFIGURED'}. Cached engineering replay costs are excluded.",
        "",
        "## Release gates",
        "",
        "| Gate | Status |",
        "|---|---|",
    ]
    lines += [f"| {g.get('gate', g.get('blocker_id'))} | {g.get('status')} |" for g in gates]
    lines += [
        "",
        "## Next required action",
        "",
        "| File/config field | Responsible role | Why required |",
        "|---|---|---|",
    ]
    lines += ["| " + " | ".join(item.values()) + " |" for item in missing]
    (out / "CDP_TRACK_B_FINAL_QUALIFICATION.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return result
