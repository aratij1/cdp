"""Select complete reviewed claims from a pre-reserved package holdout."""

from __future__ import annotations

from packages.real_data_evaluation.blind_workflow import content_digest


def build_release_cohort(
    truth: dict, bindings: list[dict], membership: dict, assignments: dict[str, str]
) -> tuple[dict, dict]:
    if truth.get("truth_sha256") != content_digest(
        {k: v for k, v in truth.items() if k != "truth_sha256"}
    ):
        raise ValueError("TRUTH_SEAL_MISMATCH")
    if (
        truth.get("status") != "FROZEN"
        or membership.get("governed") is not True
        or membership.get("complete_claim_membership_confirmed") is not True
        or not membership.get("boundary_provenance")
    ):
        raise ValueError("TRUTH_AND_GOVERNED_COMPLETE_BOUNDARIES_REQUIRED")
    if not assignments or set(assignments.values()) - {"DEVELOPMENT", "HOLDOUT"}:
        raise ValueError("INVALID_PRE_RESERVED_PACKAGE_SPLIT")
    exact = {b["source_page_id"]: b for b in bindings if b["state"] == "EXACT"}
    truth_pages = {r["page_id"] for r in truth["records"]}
    selected = {}
    excluded = {}
    seen: set[str] = set()
    for claim, row in membership["claims"].items():
        pages = set(row["page_ids"])
        if not pages or seen & pages:
            raise ValueError("AMBIGUOUS_CLAIM_MEMBERSHIP")
        seen.update(pages)
        if assignments.get(row["package_id"]) != "HOLDOUT":
            excluded[claim] = "NOT_RESERVED_HOLDOUT"
            continue
        if not pages <= truth_pages or not pages <= set(exact):
            excluded[claim] = "INCOMPLETE_REVIEWED_OR_BOUND_CLAIM"
            continue
        if any(exact[p]["package_id"] != row["package_id"] for p in pages):
            raise ValueError("CLAIM_PACKAGE_BINDING_MISMATCH")
        selected[claim] = row
    if not selected:
        raise ValueError("NO_COMPLETE_RELEASE_CLAIMS")
    selected_pages = {p for r in selected.values() for p in r["page_ids"]}
    scoped = {k: v for k, v in truth.items() if k != "truth_sha256"}
    scoped["parent_truth_sha256"] = truth["truth_sha256"]
    scoped["records"] = [r for r in truth["records"] if r["page_id"] in selected_pages]
    scoped["truth_sha256"] = content_digest(scoped)
    result = {
        "status": "FROZEN_RELEASE_COHORT",
        "claims": selected,
        "excluded_claims": excluded,
        "package_assignments": assignments,
        "package_leakage": 0,
        "source_binding_coverage": 1.0,
        "truth_sha256": scoped["truth_sha256"],
        "boundary_provenance": membership["boundary_provenance"],
        "governed": True,
        "complete_claim_membership_confirmed": True,
        "shadow_holdout_promoted": False,
    }
    result["cohort_sha256"] = content_digest(result)
    return scoped, result
