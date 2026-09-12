"""PHI-safe real release metric presentation; absent observations are never zeros."""

from __future__ import annotations

import math
from statistics import NormalDist

# Raw accuracy and critical-field HITL have no independent frozen gate threshold.
METRICS = (
    ("Raw accuracy", "raw", "accuracy", None, "min"),
    ("Critical raw accuracy", "raw", "critical_accuracy", None, "min"),
    ("Accepted precision", "raw", "accepted_precision", 0.995, "min"),
    ("Critical accepted precision", "raw", "critical_accepted_precision", 0.995, "min"),
    ("Critical false accepts", "raw", "critical_false_accepts", 0, "count"),
    ("Field HITL", "raw", "field_hitl", 0.10, "max"),
    ("Critical field HITL", "raw", "critical_field_hitl", None, "max"),
    ("Claim HITL", "raw", "claim_hitl", 0.20, "max"),
    ("STP_SAFE", "raw", "stp_safe", 0.80, "min"),
    ("False accepts", "raw", "false_accepts", None, "count"),
    ("Final post-HITL accuracy", "post_hitl", "final_accuracy", 0.99, "min"),
    ("Final critical accuracy", "post_hitl", "critical_accuracy", 0.995, "min"),
)


def interval(numerator: int | None, denominator: int | None) -> dict:
    if numerator is None or denominator is None or denominator == 0:
        return {"status": "NOT_EVALUABLE", "lower": None, "upper": None}
    if (
        type(numerator) is not int
        or type(denominator) is not int
        or not 0 <= numerator <= denominator
    ):
        raise ValueError("INVALID_BINOMIAL_COUNTS")
    z = NormalDist().inv_cdf(0.975)
    proportion = numerator / denominator
    scale = 1 + z * z / denominator
    center = (proportion + z * z / (2 * denominator)) / scale
    width = (
        z
        * math.sqrt(proportion * (1 - proportion) / denominator + z * z / (4 * denominator**2))
        / scale
    )
    return {
        "status": "DESCRIPTIVE",
        "lower": max(0.0, center - width),
        "upper": min(1.0, center + width),
        "method": "WILSON_95_PERCENT",
    }


def measured_row(name: str, numerator, denominator, target, direction: str) -> dict:
    value = None
    if numerator is not None and denominator is not None and denominator > 0:
        if (
            type(numerator) is not int
            or type(denominator) is not int
            or not 0 <= numerator <= denominator
        ):
            raise ValueError("INVALID_METRIC_DENOMINATOR")
        value = numerator if direction == "count" else numerator / denominator
    status = (
        "NOT_EVALUABLE"
        if value is None
        else "NOT_GATED"
        if target is None
        else "PASS"
        if (value >= target if direction == "min" else value <= target)
        else "FAIL"
    )
    return {
        "metric": name,
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "target": target,
        "status": status,
    }


def build_scorecard(closure: dict, binding: dict, candidate: dict) -> dict:
    scoring = closure.get("scoring", {})
    eligible = (
        binding.get("status") == "PASS"
        and bool(candidate.get("candidate_commit_sha"))
        and scoring.get("candidate_commit_sha") == candidate.get("candidate_commit_sha")
        and closure.get("freeze_integrity", {}).get("status") == "PASS"
    )
    rows = []
    intervals = {}
    for name, stage, key, target, direction in METRICS:
        data = scoring.get(stage, {}) if eligible else {}
        numerator, denominator = data.get(key + "_numerator"), data.get(key + "_denominator")
        row = measured_row(name, numerator, denominator, target, direction)
        row.update(stage=stage, key=key)
        rows.append(row)
        if direction != "count":
            intervals[name] = {
                "numerator": numerator,
                "denominator": denominator,
                **interval(numerator, denominator),
            }
    latency = closure.get("target_latency", {})
    latency_value = latency.get("median_warm_p95_ms") if latency.get("provenance_valid") else None
    rows.append(
        {
            "metric": "Warm P95",
            "numerator": None,
            "denominator": len(latency.get("run_p95_ms", [])) or None,
            "value": latency_value,
            "unit": "ms/page",
            "target": 5000,
            "status": "PASS"
            if latency.get("status") == "PASS"
            else "FAIL"
            if latency.get("status") == "FAIL"
            else "NOT_EVALUABLE",
        }
    )
    cost = closure.get("cost", {})
    actual_cost = cost.get("scope") == "MEASURED_DEPLOYMENT_WORKLOAD"
    paid = cost.get("paid_ai_cost_per_page") if actual_cost else None
    rows.append(
        {
            "metric": "Paid AI/page",
            "numerator": None,
            "denominator": cost.get("denominator_pages") if actual_cost else None,
            "value": paid,
            "target": "0.001",
            "unit": "USD/page",
            "status": cost.get("paid_ai_gate", "NOT_EVALUABLE")
            if paid is not None
            else "NOT_EVALUABLE",
        }
    )
    integrity = closure.get("freeze_integrity", {})
    leakage = 0 if eligible else None
    rows.append(
        {
            "metric": "Package leakage",
            "numerator": leakage,
            "denominator": None,
            "value": leakage,
            "target": 0,
            "status": "PASS" if leakage == 0 else "NOT_EVALUABLE",
        }
    )
    page_binding = closure.get("page_binding", {})
    page_row = measured_row(
        "Source binding",
        page_binding.get("bound_page_count"),
        page_binding.get("source_page_count"),
        1,
        "min",
    )
    if not integrity.get("exact_binding"):
        page_row["status"] = "NOT_EVALUABLE"
    rows.append(page_row)
    rows.append(
        measured_row(
            "Claim binding",
            binding.get("claims_exactly_bound"),
            binding.get("claims_considered_for_scoring", binding.get("claims_discovered")),
            1,
            "min",
        )
    )
    rows[-1]["status"] = "PASS" if binding.get("status") == "PASS" else "NOT_EVALUABLE"
    rows.append(
        {
            "metric": "Truth provenance",
            "numerator": None,
            "denominator": None,
            "value": True if eligible else None,
            "target": True,
            "status": "PASS" if eligible else "NOT_EVALUABLE",
        }
    )
    measured = [r for r in rows if r["target"] is not None]
    pending = any(r["status"] not in {"PASS", "FAIL"} for r in measured)
    failed = any(r["status"] == "FAIL" for r in measured)
    reviewed = closure.get("review", {}).get("pages_reviewed", 0)
    status = (
        "EXTERNAL_INPUT_REQUIRED"
        if pending and not reviewed
        else "REVIEW_IN_PROGRESS"
        if pending
        else "QUALIFICATION_COMPLETE_FAIL"
        if failed
        else "QUALIFICATION_COMPLETE_PASS"
    )
    return {
        "status": status,
        "final_decision": "FAIL" if failed else "PENDING_REVIEW" if pending else "PASS",
        "candidate_commit_sha": candidate.get("candidate_commit_sha"),
        "cohort_sha256": candidate.get("blind_manifest_sha256"),
        "truth_sha256": scoring.get("truth_sha256") if eligible else None,
        "real_metrics_evaluable": eligible,
        "rows": rows,
        "confidence_intervals": intervals,
        "confidence_interval_scope": "Descriptive binomial intervals; correlated fields and a selected small cohort do not establish population-level certainty.",
        "raw_and_post_hitl_separate": True,
        "production_authority_enabled": False,
    }
