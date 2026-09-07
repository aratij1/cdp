"""Validate measured target evidence against frozen semantics and governed provenance."""

from __future__ import annotations

import math
from statistics import median

from evaluation.production_latency_governor import compare
from packages.real_data_evaluation.blind_workflow import content_digest


def target_latency_evidence(
    payload: dict,
    baseline: dict,
    configuration_sha256: str | None,
    deployment_id: str | None,
    canary_fingerprints: dict | None = None,
) -> dict:
    """A summary assertion alone cannot qualify a deployment's complete page path."""
    missing: list[str] = []
    failures: list[str] = []
    result: dict = {
        "status": "NOT_AVAILABLE",
        "provenance_valid": False,
        "median_warm_p95_ms": None,
        "run_p95_ms": [],
        "reasons": missing,
    }
    if not payload:
        missing.append("TARGET_HOST_MEASUREMENTS_REQUIRED")
        return result
    provenance = bool(configuration_sha256 and deployment_id and baseline) and (
        payload.get("configuration_sha256") == configuration_sha256
        and payload.get("deployment_id") == deployment_id
        and bool(payload.get("run_id"))
        and payload.get("baseline_sha256") == content_digest(baseline)
        and payload.get("evidence_sha256")
        == content_digest({k: v for k, v in payload.items() if k != "evidence_sha256"})
    )
    result["provenance_valid"] = provenance
    if not provenance:
        missing.append("GOVERNED_TARGET_PROVENANCE_REQUIRED")
        return result
    profile = payload.get("profile", {})
    if (
        payload.get("scope") != "COMPLETE_PRODUCTION_PAGE_PATH"
        or profile.get("scope") != "COMPLETE_PRODUCTION_PAGE_PATH"
    ):
        missing.append("COMPLETE_PRODUCTION_PAGE_PATH_REQUIRED")
    runtime = payload.get("runtime", {})
    if not all(
        runtime.get(k)
        for k in (
            "host_id",
            "cpu_model",
            "logical_cpus",
            "execution_provider",
            "runtime_version",
            "os",
            "gpu_model",
        )
    ):
        missing.append("TARGET_RUNTIME_CHARACTERISTICS_REQUIRED")
    runs = profile.get("experiments", [])
    warm = [r for r in runs if r.get("mode") == "WARM_STEADY_STATE"]
    if not runs or runs[0].get("mode") != "COLD_FIRST_PASS" or len(warm) < 3:
        missing.append("WARMUP_AND_THREE_MEASURED_REPETITIONS_REQUIRED")
    try:
        decision = compare(baseline, profile, minimum_improvement=0)
    except (KeyError, TypeError, ValueError, IndexError):
        missing.append("COMPLETE_MEASUREMENT_PROFILE_REQUIRED")
        decision = {}
    # Relative speed versus a workstation does not define the deployment SLA.
    reasons = set(decision.get("reasons", [])) - {"NO_MATERIAL_P95_IMPROVEMENT"}
    failures.extend(sorted(reasons))
    for run in runs:
        pages = run.get("pages", [])
        values = [p.get("stages", {}).get("total_ms") for p in pages]
        if not values or not all(
            type(v) in (int, float) and math.isfinite(v) and v > 0 for v in values
        ):
            failures.append("INVALID_RUNTIME_MEASUREMENT")
            continue
        values.sort()
        for percentile in (50, 95, 99):
            expected = values[math.ceil(percentile / 100 * len(values)) - 1]
            if run.get("latency", {}).get(f"P{percentile}") != expected:
                failures.append("PERCENTILE_DOES_NOT_MATCH_MEASUREMENTS")
        throughput = run.get("latency", {}).get("throughput_pages_per_second")
        if type(throughput) not in (int, float) or not math.isclose(
            throughput, len(values) * 1000 / sum(values), rel_tol=1e-6
        ):
            failures.append("THROUGHPUT_DOES_NOT_MATCH_MEASUREMENTS")
        for page in pages:
            if page.get("full_claim_context_available") is not True:
                missing.append("COMPLETE_CLAIM_CONTEXT_REQUIRED")
            if (
                page.get("strict_family") in {"OTHER", "UNKNOWN"}
                and page.get("canonical_localization_invoked") is not False
            ):
                failures.append("UNSAFE_UNKNOWN_OR_OTHER_LOCALIZATION")
            memory = page.get("memory_rss_bytes")
            if type(memory) not in (int, float) or not math.isfinite(memory) or memory <= 0:
                failures.append("INVALID_MEMORY_MEASUREMENT")
    canaries = payload.get("ub04_canaries", [])
    if not canary_fingerprints or len(canary_fingerprints) != 3:
        missing.append("GOVERNED_UB04_CANARY_FINGERPRINTS_REQUIRED")
    elif len(canaries) != 3 or {c.get("page_id") for c in canaries} != set(canary_fingerprints):
        failures.append("UB04_CANARIES_INCOMPLETE")
    else:
        for canary in canaries:
            if not (
                canary.get("strict_family") == "UB04"
                and canary.get("identity_confirmed") is True
                and canary.get("canonical_localization_invoked") is True
                and canary.get("critical_safety") == "PASS"
                and canary.get("semantic_sha256") == canary_fingerprints[canary["page_id"]]
            ):
                failures.append("UB04_CANARY_SEMANTIC_OR_SAFETY_FAILURE")
    if decision and warm:
        result["run_p95_ms"] = [r["latency"]["P95"] for r in warm]
        result["median_warm_p95_ms"] = median(result["run_p95_ms"])
        if result["median_warm_p95_ms"] > 5000:
            failures.append("WARM_P95_EXCEEDS_5000_MS")
    result["reasons"] = sorted(set(missing + failures))
    result["status"] = "FAIL" if failures else "NOT_AVAILABLE" if missing else "PASS"
    return result
