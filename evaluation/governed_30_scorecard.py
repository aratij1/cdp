"""Measure isolated engineering execution against sealed fixed-width references."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from evaluation.governed_30_reference import AUTHORITY, ROOT, digest, seal
from packages.claim_intelligence.normalization import comparison_key
from packages.field_policy import DEFAULT_FIELD_POLICY_PATH, FieldPolicyRegistry

AUTO = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"}
HUMAN = {"HUMAN_REVIEW_REQUIRED", "HUMAN_CONFIRMED"}
CLAIM_REVIEW = {"FIELD_REVIEW_REQUIRED", "CLAIM_REVIEW_REQUIRED"}


def metric(numerator: int, denominator: int, *, complete: bool = True) -> dict:
    return {
        "numerator": numerator if complete else None,
        "denominator": denominator,
        "percentage": 100 * numerator / denominator if complete and denominator else None,
        "status": "MEASURED" if complete and denominator else "NOT_EVALUABLE",
    }


def _decisions(claim: dict) -> dict:
    result = {}
    for event in claim.get("events", []):
        payload = event.get("envelope", {}).get("payload", {})
        for decision in payload.get("field_decisions", []):
            if decision.get("field_id"):
                result[str(decision["field_id"])] = decision
    return result


def _canonical(policy: FieldPolicyRegistry, form: str, name: str) -> str:
    return policy.canonical_name("UB04" if form == "UB" else form, name)


def _route(
    claim: dict, rows: list[dict], canonical: str, form: str, policy: FieldPolicyRegistry
) -> bool | None:
    names = lambda name: _canonical(policy, form, name)
    if any(names(t.get("field_name", "")) == canonical for t in claim.get("tasks", [])):
        return True
    if any(r.get("disposition") in HUMAN for r in rows):
        return True
    for event in claim.get("events", []):
        if event.get("topic") == "human.review.requested":
            payload = event.get("envelope", {}).get("payload", {})
            if names(payload.get("field_name", "")) == canonical:
                return True
    decision = claim.get("claim_decision", {})
    blockers = decision.get("blocking_unresolved_fields", []) + decision.get(
        "nonblocking_unresolved_fields", []
    )
    if decision.get("disposition") in CLAIM_REVIEW and canonical in {names(n) for n in blockers}:
        return True
    if rows and all(
        r.get("disposition") in AUTO | {"UNRESOLVED_NON_BLOCKING", "REJECTED"} for r in rows
    ):
        return False
    return None


def _accepted(rows: list[dict], decisions: dict, routed: bool | None) -> bool:
    if not rows or routed is not False:
        return False
    for row in rows:
        decision = decisions.get(str(row.get("field_id")), {})
        if row.get("disposition") not in AUTO or row.get("validation_status") != "VALID":
            return False
        if (
            decision.get("disposition") != row["disposition"]
            or decision.get("next_action") != "NONE"
        ):
            return False
        if not (
            decision.get("supporting_evidence")
            or decision.get("available_evidence")
            or decision.get("evidence_bundle")
        ):
            return False
        if decision.get("conflicting_evidence") or decision.get("missing_evidence"):
            return False
        if row.get("extraction_method") in {"HUMAN", "HUMAN_REVIEW"}:
            return False
    return True


def score(
    manifest: dict, reference: dict, execution: dict, policy: FieldPolicyRegistry | None = None
) -> tuple[dict, dict]:
    policy = policy or FieldPolicyRegistry.load()
    cohort = manifest["cohort_hash"]
    if execution.get("cohort_hash") != cohort or reference.get("cohort_hash") != cohort:
        raise ValueError("COHORT_HASH_MISMATCH")
    if (
        execution.get("scope") != "GOVERNED_ENGINEERING"
        or execution.get("reference_values_used_for_inference") is not False
    ):
        raise ValueError("REFERENCE_CONTAMINATED_EXECUTION")
    if reference.get("authority") != AUTHORITY:
        raise ValueError("REFERENCE_AUTHORITY_NOT_ESTABLISHED")
    manifest_index = {c["claim_alias"]: c for c in manifest["claims"]}
    reference_index = {c["claim_alias"]: c for c in reference["claims"]}
    actual = execution.get("claims", [])
    index = {c["claim_alias"]: c for c in actual}
    if (
        len(index) != len(actual)
        or len(manifest_index) != len(manifest["claims"])
        or len(reference_index) != len(reference["claims"])
    ):
        raise ValueError("DUPLICATE_CLAIM_ALIAS")
    if set(reference_index) != set(manifest_index) or not set(index) <= set(manifest_index):
        raise ValueError("CLAIM_COHORT_MISMATCH")
    for alias, c in index.items():
        if c.get("source_sha256") != manifest_index[alias]["source_hash"]:
            raise ValueError("EXECUTION_SOURCE_MISMATCH")
    complete = len(index) == len(manifest_index) and all(
        c.get("execution_complete") is True for c in actual
    )
    raw_ready = len(index) == len(manifest_index) and all(
        c.get("execution_complete") is True
        or any(e.get("topic") == "extraction.completed" for e in c.get("events", []))
        or (
            c.get("document_status") == "NEEDS_REVIEW"
            and any(
                e.get("topic") == "page.selected"
                and e.get("envelope", {}).get("payload", {}).get("needs_review") is True
                and "NO_AUTOMATED_EXTRACTION_ROUTE"
                in e.get("envelope", {}).get("payload", {}).get("reason_codes", [])
                for e in c.get("events", [])
            )
        )
        for c in actual
    )
    slots, failures = [], []
    for alias, reference_claim in reference_index.items():
        form = reference_claim["form_type"]
        claim = index.get(alias, {})
        decisions = _decisions(claim)
        for name, expected in reference_claim["fields"].items():
            status = expected["status"]
            if status != "REFERENCE_AVAILABLE":
                failures.append(
                    {
                        "claim_alias": alias,
                        "field_name": name,
                        "reference_status": status,
                        "category": "SOURCE_AMBIGUITY"
                        if status == "REFERENCE_AMBIGUOUS"
                        else "AUTHORITY_MISSING",
                        "eligible_for_accuracy": False,
                    }
                )
                continue
            canonical = _canonical(policy, form, name)
            rows = [
                r
                for r in claim.get("fields", [])
                if r.get("service_line_number") is None
                and _canonical(policy, form, r.get("field_name", "")) == canonical
            ]
            values = [r.get("raw_value") for r in rows]
            keys = [comparison_key(name, v) for v in values if isinstance(v, str) and v.strip()]
            expected_key = comparison_key(name, expected["value"])
            correct = (
                bool(rows)
                and len(keys) == len(rows)
                and len(set(keys)) == 1
                and keys[0] == expected_key
            )
            effective = [
                r.get("normalized_value")
                if r.get("normalized_value") is not None
                else r.get("raw_value")
                for r in rows
            ]
            effective_keys = [
                comparison_key(name, value)
                for value in effective
                if isinstance(value, str) and value.strip()
            ]
            accepted_correct = (
                bool(rows)
                and len(effective_keys) == len(rows)
                and len(set(effective_keys)) == 1
                and effective_keys[0] == expected_key
            )
            routed = _route(claim, rows, canonical, form, policy)
            is_accepted = _accepted(rows, decisions, routed)
            is_critical = policy.for_field(
                "UB04" if form == "UB" else form, name
            ).criticality.value in {"C2", "C3"}
            slot = {
                "claim_alias": alias,
                "field_name": name,
                "correct": correct,
                "critical": is_critical,
                "accepted": is_accepted,
                "accepted_correct": accepted_correct,
                "review_required": routed,
                "candidate_occurrences": len(rows),
            }
            slots.append(slot)
            if not correct or routed is True or (is_accepted and not accepted_correct):
                if not keys:
                    category = "CANDIDATE_MISSING"
                elif len(set(keys)) > 1 or not correct:
                    category = "WRONG_CANDIDATE"
                elif any(r.get("validation_status") not in {"VALID", None} for r in rows):
                    category = "VALIDATION"
                elif any(
                    decisions.get(str(r.get("field_id")), {}).get("missing_evidence") for r in rows
                ):
                    category = "EVIDENCE_MISSING"
                elif is_accepted and not accepted_correct:
                    category = "NORMALIZATION"
                elif routed is True and claim.get("claim_decision", {}).get("reason_codes"):
                    category = "BUSINESS_POLICY"
                else:
                    category = "OTHER"
                failures.append({**slot, "category": category, "eligible_for_accuracy": True})
    critical = [s for s in slots if s["critical"]]
    accepted = [s for s in slots if s["accepted"]]
    critical_accepted = [s for s in accepted if s["critical"]]
    claim_routes = []
    safe = []
    for alias in manifest_index:
        c = index.get(alias, {})
        d = c.get("claim_decision", {})
        disposition = d.get("disposition")
        routed = (
            True
            if c.get("document_status") == "NEEDS_REVIEW"
            or c.get("tasks")
            or c.get("actual_human_intervention") is True
            or disposition in CLAIM_REVIEW
            else False
            if disposition in {"STP_SAFE", "STP_STANDARD", "DOCUMENT_REJECTED"}
            else None
        )
        claim_routes.append(routed)
        safe.append(
            disposition == "STP_SAFE"
            and d.get("stp_eligible") is True
            and c.get("output_completed") is True
            and c.get("actual_human_intervention") is False
            and routed is False
        )
    result = {
        "scope": "GOVERNED_ENGINEERING",
        "evidence_authority": AUTHORITY,
        "release_qualification": False,
        "cohort_hash": cohort,
        "candidate_commit_sha": execution.get("candidate_commit_sha"),
        "criticality_contract": "CURRENT_FIELD_ACCEPTANCE_POLICY_C2_C3",
        "candidate_comparison": "RAW_HEADER_VALUE_ALL_OCCURRENCES_MUST_AGREE",
        "claims": len(manifest_index),
        "execution_attempted": len(actual),
        "execution_complete": sum(c.get("execution_complete") is True for c in actual),
        "available_reference_fields": len(slots),
        "critical_reference_fields": len(critical),
        "canonical_claim_decisions_observed": sum(bool(c.get("claim_decision")) for c in actual),
        "field_hitl_bounds": {
            "status": "BOUNDS_ONLY_NOT_FULL_RATE",
            "denominator": len(slots),
            "observed_routed": sum(s["review_required"] is True for s in slots),
            "unknown_routing": sum(s["review_required"] is None for s in slots),
            "lower_numerator": sum(s["review_required"] is True for s in slots),
            "upper_numerator": sum(s["review_required"] is not False for s in slots),
            "lower_percentage": 100 * sum(s["review_required"] is True for s in slots) / len(slots)
            if slots
            else None,
            "upper_percentage": 100
            * sum(s["review_required"] is not False for s in slots)
            / len(slots)
            if slots
            else None,
        },
        "field_routing_observed": sum(s["review_required"] is not None for s in slots),
        "claim_routing_observed": sum(r is not None for r in claim_routes),
        "reference_status_counts": dict(
            Counter(f["status"] for c in reference["claims"] for f in c["fields"].values())
        ),
        "raw_accuracy": metric(sum(s["correct"] for s in slots), len(slots), complete=raw_ready),
        "critical_accuracy": metric(
            sum(s["correct"] for s in critical), len(critical), complete=raw_ready
        ),
        "accepted_precision": metric(
            sum(s["accepted_correct"] for s in accepted), len(accepted), complete=raw_ready
        ),
        "critical_accepted_precision": metric(
            sum(s["accepted_correct"] for s in critical_accepted),
            len(critical_accepted),
            complete=raw_ready,
        ),
        "critical_false_accepts": metric(
            sum(not s["accepted_correct"] for s in critical_accepted),
            len(critical_accepted),
            complete=raw_ready,
        ),
        "field_hitl": metric(
            sum(s["review_required"] is True for s in slots),
            len(slots),
            complete=raw_ready and all(s["review_required"] is not None for s in slots),
        ),
        "claim_hitl": metric(
            sum(r is True for r in claim_routes),
            len(manifest_index),
            complete=len(index) == len(manifest_index) and all(r is not None for r in claim_routes),
        ),
        "true_stp": metric(
            sum(safe),
            len(manifest_index),
            complete=len(index) == len(manifest_index) and all(r is not None for r in claim_routes),
        ),
        "actual_human_reviews": execution.get("actual_human_reviews"),
        "failure_categories": dict(Counter(f["category"] for f in failures)),
        "status": "MEASURED"
        if complete
        else "MEASURED_WITH_EXECUTION_FAILURES"
        if raw_ready
        else "EXECUTION_INCOMPLETE",
        "raw_measurement_stage_complete": raw_ready,
        "pipeline_failure_types": dict(
            Counter(f.get("error_type", "UNKNOWN") for c in actual for f in c.get("failures", []))
        ),
    }
    return result, {
        "scope": "GOVERNED_ENGINEERING",
        "cohort_hash": cohort,
        "authority": AUTHORITY,
        "execution_complete": complete,
        "failures": failures,
    }


def build(root: Path = ROOT) -> dict:
    manifest_path = root / "evaluation_results/real_release/governed_30_manifest.json"
    reference_path = (
        root / "evaluation_results/qualification_closure/governed_30_reference.local.json"
    )
    execution_path = root / "evaluation_results/governed_30_execution/raw_execution.local.json"
    read = lambda p: json.loads(p.read_text(encoding="utf8"))
    manifest, reference, execution = [
        read(p) for p in (manifest_path, reference_path, execution_path)
    ]
    unhashed = {k: v for k, v in manifest.items() if k != "cohort_hash"}
    if seal(unhashed) != manifest["cohort_hash"]:
        raise ValueError("MANIFEST_SEAL_MISMATCH")
    isolation = root / "evaluation_results/real_release/cohort_isolation.json"
    if not isolation.exists():
        raise ValueError("COHORT_ISOLATION_REQUIRED")
    check = read(isolation)
    blind_path = root / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    if (
        check.get("status") != "PASS"
        or check.get("source_seals_verified") is not True
        or check.get("governed_cohort_hash") != manifest["cohort_hash"]
        or check.get("blind_manifest_sha256") != digest(blind_path)
    ):
        raise ValueError("COHORT_ISOLATION_NOT_PASSED")
    input_path = root / "evaluation_results/governed_30_execution/execution_input.local.json"
    if not input_path.exists():
        raise ValueError("FROZEN_EXECUTION_INPUT_REQUIRED")
    frozen_input = read(input_path)
    if (
        frozen_input.get("candidate_commit_sha") != execution.get("candidate_commit_sha")
        or frozen_input.get("cohort_hash") != manifest["cohort_hash"]
    ):
        raise ValueError("FROZEN_EXECUTION_IDENTITY_MISMATCH")
    expected_policy_hash = frozen_input.get("field_policy_sha256")
    if expected_policy_hash is not None and expected_policy_hash != digest(
        root / DEFAULT_FIELD_POLICY_PATH.relative_to(ROOT)
    ):
        raise ValueError("FROZEN_FIELD_POLICY_MISMATCH")
    raw_seal_path = execution_path.parent / "raw_execution_seal.json"
    if not raw_seal_path.exists():
        raise ValueError("FROZEN_RAW_EXECUTION_SEAL_REQUIRED")
    raw_seal = read(raw_seal_path)
    if (
        raw_seal.get("raw_execution_sha256") != digest(execution_path)
        or raw_seal.get("candidate_commit_sha") != execution.get("candidate_commit_sha")
        or raw_seal.get("cohort_hash") != manifest["cohort_hash"]
    ):
        raise ValueError("FROZEN_RAW_EXECUTION_SEAL_MISMATCH")
    result, failures = score(manifest, reference, execution)
    result["input_seals"] = {
        "manifest_sha256": digest(manifest_path),
        "reference_sha256": digest(reference_path),
        "execution_sha256": digest(execution_path),
        "field_policy_sha256": digest(root / DEFAULT_FIELD_POLICY_PATH.relative_to(ROOT)),
    }
    out = root / "evaluation_results/real_release"
    for path, value in [
        (out / "governed_30_engineering_scorecard.json", result),
        (out / "governed_30_failure_cohort.json", failures),
    ]:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf8")
        temporary.replace(path)
    return result


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
