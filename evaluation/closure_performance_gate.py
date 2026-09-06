"""Exact same-page semantic gate for performance-only experiments."""

SEMANTIC_KEYS = (
    "token_evidence_sha256",
    "candidate_semantics_sha256",
    "strict_family",
    "identity_confirmed",
    "canonical_localization_invoked",
)


def compare_runs(baseline: dict, candidate: dict) -> dict:
    before = {p["page_id"]: p for p in baseline["pages"]}
    after = {p["page_id"]: p for p in candidate["pages"]}
    if (
        not before
        or before.keys() != after.keys()
        or len(before) != len(baseline["pages"])
        or len(after) != len(candidate["pages"])
    ):
        raise ValueError("PERFORMANCE_COHORT_MISMATCH")
    changed = {
        key: sum(
            before[p].get(key) != after[p].get(key) or key not in before[p] or key not in after[p]
            for p in before
        )
        for key in SEMANTIC_KEYS
    }
    identical = not any(changed.values())
    speedup = baseline["latency"]["P95"] - candidate["latency"]["P95"]
    return {
        "pages": len(before),
        "semantic_changes": changed,
        "identical_semantics": identical,
        "p95_reduction_ms": speedup,
        "status": "ENGINEERING_EVIDENCE_PASS"
        if identical and speedup > 0
        else "ENGINEERING_EVIDENCE_FAIL",
        "release_qualified": False,
    }
