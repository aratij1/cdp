"""Aggregate-only membership and blind-review integrity checks; never score observations."""

from __future__ import annotations

import re
from collections import Counter

from packages.hitl_reduction.review_coordination import canonical_reviewer_id
from packages.real_data_evaluation.blind_workflow import (
    FIELDS,
    FieldAnnotation,
    PageAnnotation,
    content_digest,
)

CHECKPOINTS = (10, 25, 50, 100, 150)


def claim_binding_report(
    membership: dict, bindings: list[dict], truth: dict, predictions: dict
) -> dict:
    """Check explicit governed lineage, including attachments; never infer adjacent pages.

    Each claim supplies page_ids, claim_form_page_ids, attachment_page_ids,
    expected_field_keys and documents ({id: {page_ids, boundary, boundary_provenance}}).
    All IDs, provenance strings, hashes and source values stay out of this report.
    """
    claims = membership.get("claims", {})
    reasons: Counter[str] = Counter()
    exact = ambiguous = 0
    governed = (
        membership.get("governed") is True
        and membership.get("complete_claim_membership_confirmed") is True
        and bool(membership.get("boundary_provenance"))
    )
    page_counts = Counter(p for c in claims.values() for p in c.get("page_ids", []))
    doc_counts = Counter(d for c in claims.values() for d in c.get("documents", {}))
    by_page: dict[str, list[dict]] = {}
    for binding in bindings:
        by_page.setdefault(binding.get("source_page_id", ""), []).append(binding)
    truth_rows = truth.get("records", [])
    pred_rows = predictions.get("fields", [])
    for claim_id, claim in claims.items():
        issues = set()
        pages = claim.get("page_ids", [])
        package = claim.get("package_id")
        if not governed:
            issues.add("GOVERNED_COMPLETE_MEMBERSHIP_REQUIRED")
        if not pages or not package:
            issues.add("CLAIM_SCOPE_REQUIRED")
        if any(page_counts[p] != 1 for p in pages):
            issues.add("AMBIGUOUS_PAGE_MEMBERSHIP")
        documents = claim.get("documents", {})
        if any(doc_counts[d] != 1 for d in documents):
            issues.add("AMBIGUOUS_DOCUMENT_MEMBERSHIP")
        doc_pages = [p for d in documents.values() for p in d.get("page_ids", [])]
        if (
            not documents
            or Counter(doc_pages) != Counter(pages)
            or any(
                not d.get("page_ids")
                or d.get("boundary") not in {"CONFIRMED", "GOVERNED"}
                or not d.get("boundary_provenance")
                for d in documents.values()
            )
        ):
            issues.add("CONFIRMED_DOCUMENT_BOUNDARIES_REQUIRED")
        forms = claim.get("claim_form_page_ids", [])
        attachments = claim.get("attachment_page_ids")
        if (
            not forms
            or attachments is None
            or Counter(forms + (attachments or [])) != Counter(pages)
        ):
            issues.add("COMPLETE_FORM_AND_ATTACHMENT_SCOPE_REQUIRED")
        expected_list = claim.get("expected_field_keys", [])
        expected = {tuple(k) for k in expected_list}
        if (
            not expected
            or not {(p, f) for p in forms for f in FIELDS} <= expected
            or len(expected) != len(expected_list)
            or any(len(k) != 2 or k[0] not in pages or not k[1] for k in expected)
        ):
            issues.add("COMPLETE_EXPECTED_FIELDS_REQUIRED")
        for page in pages:
            matches = by_page.get(page, [])
            if len(matches) != 1:
                issues.add("AMBIGUOUS_SOURCE_BINDING" if matches else "SOURCE_BINDING_REQUIRED")
                continue
            binding = matches[0]
            digest = binding.get("rendered_page_sha256")
            if (
                binding.get("state") != "EXACT"
                or not isinstance(digest, str)
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or binding.get("cdp_page_sha256") != digest
                or not binding.get("cdp_page_id")
                or binding.get("package_id") != package
                or binding.get("claim_id") not in {None, claim_id}
            ):
                issues.add("EXACT_SOURCE_BINDING_REQUIRED")
            for label, records in (("TRUTH", truth_rows), ("PREDICTION", pred_rows)):
                scoped = [r for r in records if r.get("page_id") == page]
                keys = [(r.get("page_id"), r.get("field_name")) for r in scoped]
                if set(keys) != {k for k in expected if k[0] == page} or len(keys) != len(
                    set(keys)
                ):
                    issues.add(f"COMPLETE_{label}_FIELDS_REQUIRED")
                if any(
                    r.get("source_sha256") != digest
                    or r.get("package_id") != package
                    or r.get("claim_id", claim_id) != claim_id
                    for r in scoped
                ):
                    issues.add(f"EXACT_{label}_BINDING_REQUIRED")
        if not issues:
            exact += 1
        elif any(i.startswith("AMBIGUOUS_") for i in issues):
            ambiguous += 1
        reasons.update(issues)
    if not claims:
        reasons["GOVERNED_COMPLETE_MEMBERSHIP_REQUIRED"] += 1
    total = len(claims)
    return {
        "status": "PASS" if total and exact == total else "NOT_EVALUABLE",
        "claims_discovered": total,
        "claims_exactly_bound": exact,
        "claims_ambiguous": ambiguous,
        "claims_excluded": total - exact,
        "ambiguous_claims_are_subset_of_excluded": True,
        "claim_binding_coverage": exact / total if total else None,
        "eligible_claim_denominator": exact,
        "exclusion_reasons": dict(sorted(reasons.items())),
        "membership_inferred_from_adjacency": False,
    }


def review_checkpoint_integrity(
    progress: dict,
    rows: list[dict],
    sources: dict,
    registry: dict,
    adjudications: list[dict] | None = None,
    *,
    machinery: dict | None = None,
) -> dict:
    """Validate workflow now and at every reached milestone, with no accuracy release.

    machinery contains explicit boolean results from comparator, denominator and
    qualification self-checks. Absence is pending, never an inferred successful check.
    """
    issues: Counter[str] = Counter()
    pending: Counter[str] = Counter()
    authorized = {canonical_reviewer_id(r) for r in registry.get("authorized_reviewers", [])}
    adjudicators = {canonical_reviewer_id(r) for r in registry.get("adjudicators", [])}
    if (
        registry.get("identity_verified") is not True
        or not registry.get("policy_id")
        or not authorized
    ):
        pending["GOVERNED_REVIEWER_REGISTRY_REQUIRED"] += 1
    if len(authorized) < 2:
        pending["INDEPENDENT_DUAL_REVIEW_INFRASTRUCTURE_REQUIRED"] += 1
    if not adjudicators:
        pending["INDEPENDENT_ADJUDICATION_INFRASTRUCTURE_REQUIRED"] += 1
    grouped: dict[str, list[dict]] = {}
    seen = set()
    for row in rows:
        page = row.get("page_id", "")
        reviewer = canonical_reviewer_id(row.get("reviewer_id", ""))
        if page not in sources or row.get("source_sha256") != sources[page].get(
            "rendered_page_sha256"
        ):
            issues["REVIEW_SOURCE_BINDING_INVALID"] += 1
            continue
        if not reviewer or reviewer not in authorized:
            issues["REVIEW_PROVENANCE_INVALID"] += 1
            continue
        if (page, reviewer) in seen:
            issues["DUPLICATE_INDEPENDENT_REVIEWER"] += 1
            continue
        seen.add((page, reviewer))
        try:
            PageAnnotation.model_validate(row.get("annotation", {}))
        except ValueError:
            issues["TRUTH_INGESTION_INVALID"] += 1
            continue
        grouped.setdefault(page, []).append(row)
    decisions = set()
    for decision in adjudications or []:
        page = decision.get("page_id", "")
        reviewer = canonical_reviewer_id(decision.get("adjudicator_id", ""))
        reviews = grouped.get(page, [])
        key = (page, decision.get("field_name"))
        if key in decisions:
            issues["DUPLICATE_ADJUDICATION"] += 1
        decisions.add(key)
        try:
            if key[1] == "__metadata__" and reviews:
                conclusion = decision.get("conclusion", {})
                if set(conclusion) != {"form", "quality", "boundary"}:
                    raise ValueError("INVALID_METADATA")
                PageAnnotation.model_validate({**reviews[0]["annotation"], **conclusion})
            elif key[1] in FIELDS:
                FieldAnnotation.model_validate(decision.get("conclusion", {}))
            else:
                raise ValueError("INVALID_FIELD")
        except ValueError:
            issues["ADJUDICATION_INGESTION_INVALID"] += 1
        if (
            len(reviews) < 2
            or reviewer not in adjudicators
            or reviewer in {canonical_reviewer_id(r["reviewer_id"]) for r in reviews}
            or decision.get("review_digest") != content_digest(reviews)
        ):
            issues["ADJUDICATION_PROVENANCE_INVALID"] += 1
    if progress.get("pages_reviewed") != len(grouped) or progress.get("pages_total") != len(
        sources
    ):
        issues["REVIEW_DENOMINATOR_MISMATCH"] += 1
    for check in ("comparison_logic", "denominators", "qualification_machinery"):
        result = (machinery or {}).get(check)
        if result is False:
            issues[f"{check.upper()}_FAILED"] += 1
        elif result is not True:
            pending[f"{check.upper()}_NOT_VALIDATED"] += 1
    reached = [n for n in CHECKPOINTS if len(grouped) >= n]
    return {
        "status": "FAIL" if issues else "PENDING" if pending else "PASS",
        "scope": "REVIEW_WORKFLOW_INTEGRITY_ONLY",
        "pages_validated": len(grouped),
        "milestones_reached": reached,
        "next_milestone": next((n for n in CHECKPOINTS if n > len(grouped)), None),
        "issues": dict(sorted(issues.items())),
        "pending": dict(sorted(pending.items())),
        "interim_production_metrics_released": False,
        "extraction_tuning_permitted": False,
    }


def claim_execution_manifest(
    membership: dict,
    bindings: list[dict],
    truth: dict,
    snapshot: dict,
    candidate: dict,
    *,
    excluded: dict | None = None,
    stage: str = "RAW",
) -> dict:
    """Monitor declared claim execution without changing scoring denominators."""
    claims = membership.get("claims", {})
    excluded = excluded or {}
    page_counts = Counter(p for c in claims.values() for p in c.get("page_ids", []))
    doc_counts = Counter(d for c in claims.values() for d in c.get("documents", {}))
    truth_sealed = truth.get("status") == "FROZEN" and truth.get("truth_sha256") == content_digest(
        {k: v for k, v in truth.items() if k != "truth_sha256"}
    )
    prediction_sealed = (
        bool(candidate.get("candidate_commit_sha"))
        and snapshot.get("candidate_commit_sha") == candidate.get("candidate_commit_sha")
        and snapshot.get("scope") == "CANONICAL_PRODUCTION_PIPELINE"
        and snapshot.get("purpose") == "FINAL_GATE"
        and snapshot.get("used_for_tuning") is False
        and bool(snapshot.get("execution_provenance"))
        and snapshot.get("snapshot_sha256")
        == content_digest({k: v for k, v in snapshot.items() if k != "snapshot_sha256"})
    )
    records = []
    for claim_id in sorted(set(claims) | set(excluded)):
        claim = claims.get(claim_id, {})
        pages = claim.get("page_ids", [])
        diagnostic = claim_binding_report(
            {**membership, "claims": {claim_id: claim}}, bindings, truth, snapshot
        )
        issues = set(diagnostic["exclusion_reasons"])
        membership_complete = not any(
            "TRUTH" not in issue and "PREDICTION" not in issue for issue in issues
        )
        membership_complete = (
            membership_complete
            and all(page_counts[p] == 1 for p in pages)
            and all(doc_counts[d] == 1 for d in claim.get("documents", {}))
        )
        truth_complete = truth_sealed and not any("TRUTH" in issue for issue in issues)
        execution = snapshot.get("claims", {}).get(claim_id, {}) if prediction_sealed else {}
        prediction_complete = (
            prediction_sealed
            and bool(execution)
            and not any("PREDICTION" in issue for issue in issues)
        )
        forms = {
            r.get("page_metadata", {}).get("form")
            for r in truth.get("records", [])
            if r.get("page_id") in claim.get("claim_form_page_ids", [])
        }
        forms.discard(None)
        form_type = next(iter(forms)) if len(forms) == 1 else "UNKNOWN"
        if form_type not in {
            "CMS1500",
            "UB04",
            "OTHER_CLAIM_FORM",
            "SUPPORTING_DOCUMENT",
            "UNKNOWN",
        }:
            form_type = "UNKNOWN"
        flags = {
            name: execution.get(key) if type(execution.get(key)) is bool else None
            for name, key in (
                ("validation_complete", "validation_complete"),
                ("evidence_complete", "required_evidence_pass"),
                ("authority_complete", "authority_complete"),
                ("decision_complete", "decision_complete"),
                ("output_complete", "output_completed"),
            )
        }
        raw_ready = bool(
            membership_complete
            and truth_complete
            and prediction_complete
            and flags["validation_complete"] is True
            and flags["decision_complete"] is True
        )
        status = (
            "EXCLUDED"
            if claim_id in excluded
            else "INCOMPLETE_MEMBERSHIP"
            if not membership_complete
            else "INCOMPLETE_TRUTH"
            if not truth_complete
            else "INCOMPLETE_EXECUTION"
            if not prediction_complete or not all(v is True for v in flags.values())
            else "ELIGIBLE"
        )
        records.append(
            {
                "claim_id": content_digest(claim_id),
                "package_id": content_digest(claim["package_id"])
                if claim.get("package_id")
                else None,
                "page_ids": [content_digest(p) for p in pages],
                "page_sequence": [content_digest(p) for p in pages],
                "form_type": form_type,
                "membership_complete": bool(membership_complete),
                "truth_complete": bool(truth_complete),
                "prediction_complete": bool(prediction_complete),
                **flags,
                "execution_started": True if execution else None,
                "execution_complete": all(v is True for v in flags.values())
                if prediction_complete
                else None,
                "hitl_required": execution.get("human_intervention_required")
                if type(execution.get("human_intervention_required")) is bool
                else None,
                "hitl_completed": (
                    execution.get("revalidation_completed") is True
                    and flags["output_complete"] is True
                )
                if execution.get("human_corrected") is True
                or execution.get("human_reviewed") is True
                else None,
                "revalidation_complete": execution.get("revalidation_completed")
                if type(execution.get("revalidation_completed")) is bool
                else None,
                "final_decision": execution.get("decision")
                if stage == "POST_HITL"
                and execution.get("decision")
                in {
                    "STP_SAFE",
                    "STP_STANDARD",
                    "FIELD_REVIEW_REQUIRED",
                    "CLAIM_REVIEW_REQUIRED",
                    "DOCUMENT_REJECTED",
                }
                else None,
                "output_status": "COMPLETE"
                if flags["output_complete"] is True
                else "PENDING"
                if flags["output_complete"] is False
                else "NOT_AVAILABLE",
                "execution_status": status,
                "raw_scoring_ready": raw_ready and claim_id not in excluded,
            }
        )
    counts = Counter(r["execution_status"] for r in records)
    return {
        "status": "AVAILABLE" if records else "NOT_EVALUABLE",
        "stage": stage,
        "id_encoding": "SHA256_CANONICAL_JSON",
        "claims": records,
        "claims_discovered": len(records),
        "claims_exactly_bound": sum(r["membership_complete"] for r in records),
        "execution_complete": counts["ELIGIBLE"],
        "excluded": counts["EXCLUDED"],
        "execution_status_counts": dict(sorted(counts.items())),
        "denominator_policy": "Monitoring only. Human-routed or unresolved claims remain in the fully-bound raw scoring denominator; incomplete final output is not an exclusion.",
        "candidate_commit_sha": candidate.get("candidate_commit_sha"),
        "binding_sha256": content_digest(bindings),
        "claim_membership_sha256": content_digest(membership),
    }
