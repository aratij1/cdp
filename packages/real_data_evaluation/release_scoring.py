"""Same-denominator raw and post-HITL scoring for complete governed claims."""

from __future__ import annotations

from collections import Counter

from packages.claim_intelligence.normalization import comparison_key
from packages.real_data_evaluation.blind_workflow import content_digest


def score_release(truth: dict, raw: dict, final: dict | None, membership: dict) -> dict:
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

    for claim in claims.values():
        claim_keys = [tuple(key) for key in claim.get("expected_field_keys", [])]
        actual_keys = {key for key in keys if key[0] in claim["page_ids"]}
        if len(claim_keys) != len(set(claim_keys)) or set(claim_keys) != actual_keys:
            raise ValueError("COMPLETE_EXPECTED_CLAIM_FIELD_DENOMINATOR_REQUIRED")

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
        if any(
            type(row.get(flag)) is not bool
            for row in index.values()
            for flag in ("accepted", "review_required")
        ) or any(
            flag in claim and type(claim[flag]) is not bool
            for claim in snapshot["claims"].values()
            for flag in (
                "human_corrected",
                "human_reviewed",
                "review_required",
                "revalidation_completed",
                "output_completed",
                "required_fields_pass",
                "required_evidence_pass",
                "human_intervention_required",
                "automatic_output_safely_generated",
            )
        ):
            raise ValueError("BOOLEAN_EXECUTION_FLAGS_REQUIRED")
        if any(
            flag in row and type(row[flag]) is not bool
            for row in index.values()
            for flag in ("human_corrected", "human_reviewed", "human_intervention_required")
        ):
            raise ValueError("BOOLEAN_EXECUTION_FLAGS_REQUIRED")
        return index

    before = checked(raw)
    after = checked(final) if final is not None else None
    if final is not None and raw["configuration_sha256"] != final["configuration_sha256"]:
        raise ValueError("RAW_FINAL_CONFIGURATION_MISMATCH")

    def correct(row, prediction):
        if row["state"] != prediction["state"]:
            return False
        if row["state"] != "VALUE":
            return row.get("value") is None and prediction.get("value") is None
        return comparison_key(row["field_name"], row["value"]) == comparison_key(
            row["field_name"], prediction["value"]
        )

    def human(value):
        return (
            any(
                value.get(flag) is True
                for flag in ("human_corrected", "human_reviewed", "human_intervention_required")
            )
            or value.get("authority") == "HUMAN_CONFIRMED"
        )

    def routed(value):
        return value["review_required"] is True or human(value)

    def completed(value):
        return value.get("decision") == "STP_SAFE" and all(
            value.get(flag) is True
            for flag in ("output_completed", "required_fields_pass", "required_evidence_pass")
        )

    def add_metric(result, name, numerator, denominator):
        result[name] = numerator / denominator if denominator else None
        result[name + "_numerator"] = numerator
        result[name + "_denominator"] = denominator

    critical = [r for r in rows if r["critical"]]

    def accuracy(subset, index):
        return (
            sum(correct(r, index[(r["page_id"], r["field_name"])]) for r in subset) / len(subset)
            if subset
            else None
        )

    hitl = {
        c
        for c, v in claims.items()
        if raw["claims"][c].get("decision") in {"FIELD_REVIEW_REQUIRED", "CLAIM_REVIEW_REQUIRED"}
        or raw["claims"][c].get("review_required") is True
        or human(raw["claims"][c])
        or raw["claims"][c].get("human_reviewed") is True
        or any(
            routed(before[(r["page_id"], r["field_name"])])
            for r in rows
            if r["page_id"] in v["page_ids"]
        )
    }
    stp_claims = {
        c
        for c in claims
        if completed(raw["claims"][c])
        and raw["claims"][c].get("automatic_output_safely_generated") is True
        and all(
            raw["claims"][c].get(flag) is False for flag in ("human_corrected", "human_reviewed")
        )
        and raw["claims"][c].get("human_corrected") is not True
        and c not in hitl
    }

    declared_stp_claims = {
        c for c in claims if raw["claims"][c].get("decision") in {"STP_SAFE", "STP_STANDARD"}
    }
    safe_stp_claims = {
        c
        for c in stp_claims
        if all(
            before[(r["page_id"], r["field_name"])]["accepted"] is True
            and correct(r, before[(r["page_id"], r["field_name"])])
            for r in rows
            if r["page_id"] in claims[c]["page_ids"]
        )
    }

    def field_metrics(subset, index):
        eligible = [
            r
            for r in subset
            if index[(r["page_id"], r["field_name"])]["accepted"] is True
            and not routed(index[(r["page_id"], r["field_name"])])
        ]
        critical_rows = [r for r in subset if r["critical"]]
        noncritical = [r for r in subset if not r["critical"]]
        critical_eligible = [r for r in eligible if r["critical"]]
        result = {
            "fields": len(subset),
            "critical_fields": len(critical_rows),
            "noncritical_fields": len(noncritical),
            "accepted_fields": len(eligible),
            "critical_accepted_fields": len(critical_eligible),
        }
        for name, group in (
            ("accuracy", subset),
            ("critical_accuracy", critical_rows),
            ("noncritical_accuracy", noncritical),
            ("accepted_precision", eligible),
            ("critical_accepted_precision", critical_eligible),
        ):
            add_metric(
                result,
                name,
                sum(correct(r, index[(r["page_id"], r["field_name"])]) for r in group),
                len(group),
            )
        false_accepts = len(critical_eligible) - result["critical_accepted_precision_numerator"]
        result.update(
            false_accepts=len(eligible) - result["accepted_precision_numerator"],
            false_accepts_numerator=len(eligible) - result["accepted_precision_numerator"],
            false_accepts_denominator=len(eligible),
            critical_false_accepts=false_accepts,
            critical_false_accepts_numerator=false_accepts,
            critical_false_accepts_denominator=len(critical_eligible),
        )
        for name, group in (
            ("field_hitl", subset),
            ("critical_field_hitl", critical_rows),
            ("noncritical_field_hitl", noncritical),
        ):
            add_metric(
                result,
                name,
                sum(routed(index[(r["page_id"], r["field_name"])]) for r in group),
                len(group),
            )
        result["hitl_ownership"] = dict(
            Counter(
                owner(index[(r["page_id"], r["field_name"])])
                for r in subset
                if routed(index[(r["page_id"], r["field_name"])])
            )
        )
        result["cdp_controlled_field_hitl"] = None
        result["cdp_controlled_field_hitl_status"] = "NOT_EVALUABLE_OWNERSHIP_POLICY_REQUIRED"
        return result

    def owner(value):
        category = value.get("hitl_owner")
        allowed = {
            "TECHNICAL",
            "SOURCE_REVIEW",
            "MEMBER_AUTHORITY",
            "PROVIDER_AUTHORITY",
            "IDENTITY_AUTHORITY",
            "SOURCE_EVIDENCE",
            "BUSINESS_POLICY",
            "REAL_CONFLICT",
        }
        return category if category in allowed else "UNKNOWN"

    def claim_metrics(subset):
        group_pages = {row["page_id"] for row in subset}
        group_claims = {
            c for c, value in claims.items() if group_pages.intersection(value["page_ids"])
        }
        result = {
            "claims": len(group_claims),
            "eligible_claims": len(group_claims),
            "stp_claims": len(group_claims & stp_claims),
            "hitl_claims": len(group_claims & hitl),
            "unresolved_claims": len(group_claims - hitl - stp_claims),
            "excluded_claims": 0,
        }
        add_metric(result, "claim_hitl", result["hitl_claims"], len(group_claims))
        add_metric(result, "stp", result["stp_claims"], len(group_claims))
        safe = group_claims & safe_stp_claims
        add_metric(
            result, "declared_stp", len(group_claims & declared_stp_claims), len(group_claims)
        )
        add_metric(result, "stp_safe", len(safe), len(group_claims))
        result["false_stp_claims"] = len((group_claims & declared_stp_claims) - safe)
        return result

    breakdowns = {}
    for dimension in ("form", "field", "criticality", "quality", "source_class"):
        groups: dict[str, list] = {}
        for row in rows:
            group = (
                row["field_name"]
                if dimension == "field"
                else ("CRITICAL" if row["critical"] else "NON_CRITICAL")
                if dimension == "criticality"
                else row.get("page_metadata", {}).get(dimension, "UNKNOWN")
            )
            groups.setdefault(group, []).append(row)
        breakdowns[dimension] = {
            name: {**field_metrics(group, before), **claim_metrics(group)}
            for name, group in groups.items()
        }
    post = {}
    if final is not None and after is not None:
        pending_review = {
            c
            for c, claim in claims.items()
            if final["claims"][c].get("review_required") is True
            or any(after[key]["review_required"] for key in keys if key[0] in claim["page_ids"])
        }
        true_stp = {
            c
            for c in safe_stp_claims
            if completed(final["claims"][c])
            and final["claims"][c].get("automatic_output_safely_generated") is True
            and not human(final["claims"][c])
            and all(
                final["claims"][c].get(flag) is False
                for flag in ("human_corrected", "human_reviewed")
            )
            and not any(human(after[key]) for key in keys if key[0] in claims[c]["page_ids"])
            and final["claims"][c].get("human_corrected") is not True
            and final["claims"][c].get("human_reviewed") is not True
            and c not in pending_review
            and all(
                after[(r["page_id"], r["field_name"])]["accepted"] is True
                and correct(r, after[(r["page_id"], r["field_name"])])
                for r in rows
                if r["page_id"] in claims[c]["page_ids"]
            )
        }
        hitl_closed = {
            c
            for c in claims
            if c not in true_stp
            and c not in pending_review
            and completed(final["claims"][c])
            and final["claims"][c].get("revalidation_completed") is True
            and (
                c in hitl
                or final["claims"][c].get("human_corrected") is True
                or final["claims"][c].get("human_reviewed") is True
                or any(human(after[key]) for key in keys if key[0] in claims[c]["page_ids"])
            )
        }
        post = {
            "final_accuracy": accuracy(rows, after),
            "critical_accuracy": accuracy(critical, after),
            "claims_corrected": sum(
                c.get("human_corrected") is True for c in final["claims"].values()
            ),
            "claims_closed_after_revalidation": len(hitl_closed),
            "true_stp_claims": len(true_stp),
            "hitl_closed_claims": len(hitl_closed),
            "claims_successfully_closed": len(true_stp | hitl_closed),
            "unresolved": len(claims) - len(true_stp | hitl_closed),
        }
        for name, group in (("final_accuracy", rows), ("critical_accuracy", critical)):
            add_metric(
                post,
                name,
                sum(correct(r, after[(r["page_id"], r["field_name"])]) for r in group),
                len(group),
            )
        post["claims_denominator"] = len(claims)
        post["claims_successfully_revalidated"] = sum(
            value.get("revalidation_completed") is True and (c in hitl or human(value))
            for c, value in final["claims"].items()
        )
    errors: Counter[str] = Counter()
    categories = {
        "TRUTH_NOT_IN_CANDIDATES",
        "WRONG_RANK",
        "NORMALIZATION",
        "VALIDATION",
        "ROUTING",
        "SOURCE_AMBIGUITY",
        "AUTHORITY",
        "REFERENCE/TRUTH ISSUE",
        "OTHER",
    }
    for row in rows:
        prediction = before[(row["page_id"], row["field_name"])]
        if not correct(row, prediction):
            category = prediction.get("error_classification")
            errors[
                category
                if category in categories and prediction.get("error_evidence")
                else "UNCLASSIFIED"
            ] += 1
    combinations: Counter[str] = Counter()
    for c in hitl:
        owners = {
            owner(before[key])
            for key in keys
            if key[0] in claims[c]["page_ids"] and routed(before[key])
        }
        if raw["claims"][c].get("review_required") or human(raw["claims"][c]) or not owners:
            owners.add(owner(raw["claims"][c]))
        combinations["+".join(sorted(owners))] += 1
    return {
        "error_analysis": dict(errors),
        "status": "EVALUATED" if final is not None else "RAW_EVALUATED_FINAL_PENDING",
        "truth_sha256": truth["truth_sha256"],
        "pages": len(pages),
        "fields": len(rows),
        "claims": len(claims),
        "raw": {
            **field_metrics(rows, before),
            **claim_metrics(rows),
            "claim_blocker_combinations": dict(combinations),
        },
        "breakdowns": breakdowns,
        "post_hitl": post,
    }
