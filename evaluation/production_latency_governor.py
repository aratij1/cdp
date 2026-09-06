"""Fail-closed comparison of complete, fresh performance benchmark repetitions."""

from __future__ import annotations

import math
from statistics import median

SEMANTIC_KEYS = (
    "token_evidence_sha256",
    "text_geometry_sha256",
    "candidate_semantics_sha256",
    "downstream_semantics_sha256",
    "candidate_ids_sha256",
    "claim_graph_decisions_sha256",
    "canonical_routing_decisions_sha256",
    "strict_family",
    "identity_confirmed",
    "canonical_localization_invoked",
    "candidate_counts",
    "effective_fields",
)


def compare(
    baseline: dict,
    candidate: dict,
    *,
    minimum_improvement: float = 0.05,
    memory_budget_bytes: int = 2_500_000_000,
) -> dict:
    """This governor qualifies measured shadow semantics, never production SLA."""
    if not 0 <= minimum_improvement < 1 or memory_budget_bytes <= 0:
        raise ValueError("INVALID_GOVERNOR_BUDGET")
    reasons = []
    if candidate.get("aggregate_peak_rss_upper_bound_bytes", 0) > memory_budget_bytes:
        reasons.append("MEMORY_BUDGET_EXCEEDED")
    base_runs, runs = baseline["experiments"], candidate["experiments"]
    expected = [p["page_id"] for p in base_runs[0]["pages"]]
    if not expected or len(set(expected)) != len(expected):
        reasons.append("INVALID_BASELINE_COHORT")
    reference = {p["page_id"]: p for p in base_runs[0]["pages"]}
    warm = [r for r in runs if r["mode"] == "WARM_STEADY_STATE"]
    base_warm = [r for r in base_runs if r["mode"] == "WARM_STEADY_STATE"]
    if len(warm) < 3 or len(base_warm) < 3:
        reasons.append("INSUFFICIENT_WARM_REPETITIONS")
    for run in base_runs + runs:
        values = [p.get("stages", {}).get("total_ms") for p in run["pages"]]
        valid = bool(values) and all(
            type(v) in (int, float) and math.isfinite(v) and v > 0 for v in values
        )
        if not valid:
            reasons.append("INVALID_RUNTIME_MEASUREMENT")
        elif run.get("latency", {}).get("P95") != sorted(values)[math.ceil(0.95 * len(values)) - 1]:
            reasons.append("P95_DOES_NOT_MATCH_PAGE_MEASUREMENTS")
        if [p["page_id"] for p in run["pages"]] != expected:
            reasons.append("INCOMPLETE_OR_DIFFERENT_COHORT")
        for page in run["pages"]:
            original = reference.get(page["page_id"], {})
            if any(
                k not in page or k not in original or page[k] != original[k] for k in SEMANTIC_KEYS
            ):
                reasons.append("SEMANTIC_MISMATCH")
            if page.get("cache_hit") is not False or page.get("full_page_ocr_calls") != 1:
                reasons.append("INVALID_FRESH_OCR_PATH")
            if page.get("memory_rss_bytes", memory_budget_bytes + 1) > memory_budget_bytes:
                reasons.append("MEMORY_BUDGET_EXCEEDED")
    before = median(r["latency"]["P95"] for r in base_warm) if base_warm else None
    after = median(r["latency"]["P95"] for r in warm) if warm else None
    if before is None or after is None or after > before * (1 - minimum_improvement):
        reasons.append("NO_MATERIAL_P95_IMPROVEMENT")
    return {
        "status": "KEEP_ELIGIBLE_PENDING_SAFETY" if not reasons else "REJECT",
        "reasons": sorted(set(reasons)),
        "baseline_median_warm_p95_ms": before,
        "candidate_median_warm_p95_ms": after,
        "semantic_equality": "SEMANTIC_MISMATCH" not in reasons,
        "target_met_on_measured_path": after is not None and after <= 5000 and not reasons,
        "production_sla_qualified": False,
        "scope": candidate["scope"],
    }
