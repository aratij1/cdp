"""Same-denominator raw and post-HITL scoring for complete governed claims."""

from __future__ import annotations

from packages.real_data_evaluation.blind_workflow import content_digest


def score_release(truth: dict, raw: dict, final: dict, membership: dict) -> dict:
    sealed = {k: v for k, v in truth.items() if k != "truth_sha256"}
    if truth.get("status") != "FROZEN" or truth.get("truth_sha256") != content_digest(sealed):
        raise ValueError("TRUSTED_TRUTH_FREEZE_REQUIRED")
    rows = truth["records"]
    keys = {(r["page_id"], r["field_name"]) for r in rows}
    if (
        not keys
        or len(keys) != len(rows)
        or any(r["authority"] not in {"DUAL_REVIEW_AGREED", "ADJUDICATED"} for r in rows)
    ):
        raise ValueError("INVALID_RELEASE_TRUTH")
    if membership.get("governed") is not True or not membership.get("boundary_provenance"):
        raise ValueError("GOVERNED_COMPLETE_CLAIM_MEMBERSHIP_REQUIRED")
    claims = membership["claims"]
    pages = [p for c in claims.values() for p in c["page_ids"]]
    if len(pages) != len(set(pages)) or set(pages) != {r["page_id"] for r in rows}:
        raise ValueError("CLAIM_PAGE_COVERAGE_MISMATCH")
    packages = {r["page_id"]: r["package_id"] for r in rows}
    for claim in claims.values():
        if not claim["page_ids"] or {packages[p] for p in claim["page_ids"]} != {
            claim["package_id"]
        }:
            raise ValueError("CLAIM_PACKAGE_LINEAGE_MISMATCH")

    expected_keys = {
        tuple(key) for claim in claims.values() for key in claim.get("expected_field_keys", [])
    }
    if expected_keys != keys:
        raise ValueError("COMPLETE_EXPECTED_CLAIM_FIELD_DENOMINATOR_REQUIRED")

    def checked(snapshot):
        if snapshot.get("used_for_tuning") is not False or snapshot.get("purpose") != "FINAL_GATE":
            raise ValueError("UNTOUCHED_FINAL_HOLDOUT_EXECUTION_REQUIRED")
        if (
            snapshot.get("scope") != "CANONICAL_PRODUCTION_PIPELINE"
            or not snapshot.get("configuration_sha256")
            or not snapshot.get("execution_provenance")
        ):
            raise ValueError("ACTUAL_CANONICAL_EXECUTION_REQUIRED")
        if snapshot.get("snapshot_sha256") != content_digest(
            {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
        ):
            raise ValueError("PREDICTION_SNAPSHOT_SEAL_MISMATCH")
        index = {(r["page_id"], r["field_name"]): r for r in snapshot["fields"]}
        if set(index) != keys or len(index) != len(snapshot["fields"]):
            raise ValueError("PREDICTION_DENOMINATOR_MISMATCH")
        if set(snapshot["claims"]) != set(claims):
            raise ValueError("PREDICTION_CLAIM_DENOMINATOR_MISMATCH")
        return index

    before, after = checked(raw), checked(final)
    if raw["configuration_sha256"] != final["configuration_sha256"]:
        raise ValueError("RAW_FINAL_CONFIGURATION_MISMATCH")

    def correct(row, prediction):
        return (row["state"], row["value"]) == (prediction["state"], prediction["value"])

    accepted = [r for r in rows if before[(r["page_id"], r["field_name"])]["accepted"] is True]
    critical = [r for r in rows if r["critical"]]
    critical_accepted = [r for r in accepted if r["critical"]]

    def accuracy(subset, index):
        return (
            sum(correct(r, index[(r["page_id"], r["field_name"])]) for r in subset) / len(subset)
            if subset
            else None
        )

    hitl = {
        c
        for c, v in claims.items()
        if any(
            before[(r["page_id"], r["field_name"])]["review_required"]
            for r in rows
            if r["page_id"] in v["page_ids"]
        )
    }
    closed = sum(
        c.get("decision") == "STP_SAFE" and c.get("revalidation_completed") is True
        for c in final["claims"].values()
    )
    stp = sum(raw["claims"][c].get("decision") == "STP_SAFE" and c not in hitl for c in claims)
    return {
        "status": "EVALUATED",
        "truth_sha256": truth["truth_sha256"],
        "fields": len(rows),
        "claims": len(claims),
        "raw": {
            "accuracy": accuracy(rows, before),
            "critical_accuracy": accuracy(critical, before),
            "accepted_precision": accuracy(accepted, before),
            "critical_accepted_precision": accuracy(critical_accepted, before),
            "critical_false_accepts": sum(
                not correct(r, before[(r["page_id"], r["field_name"])]) for r in critical_accepted
            ),
            "field_hitl": sum(before[k]["review_required"] is True for k in keys) / len(keys),
            "claim_hitl": len(hitl) / len(claims),
            "stp": stp / len(claims),
        },
        "post_hitl": {
            "final_accuracy": accuracy(rows, after),
            "critical_accuracy": accuracy(critical, after),
            "claims_corrected": sum(
                c.get("human_corrected") is True for c in final["claims"].values()
            ),
            "claims_closed_after_revalidation": closed,
            "unresolved": len(claims) - closed,
        },
    }
