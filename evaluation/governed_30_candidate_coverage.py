"""Separate engineering candidate recall; never extraction accuracy or release truth."""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from evaluation.governed_30_reference import ROOT, digest
from evaluation.governed_30_root_cause import routing_state
from evaluation.governed_30_scorecard import _canonical, metric, score
from packages.claim_intelligence.normalization import comparison_key
from packages.field_policy import FieldPolicyRegistry
from workers.field_candidates.label_token_recovery import generate, labels
from workers.page_detection.text_extraction import TextLine

STAGES = (
    "NO_LOCALIZATION",
    "WRONG_REGION",
    "EMPTY_CROP",
    "OCR_NO_TOKENS",
    "OCR_WRONG_TEXT",
    "TOKEN_FILTERED",
    "ASSEMBLY_FAILED",
    "FIELD_RULE_TOO_NARROW",
    "REFERENCE_NOT_VISIBLE_ON_SOURCE",
    "OTHER",
)


def unique_values(field: str, values: list[str]) -> list[str]:
    result, seen = [], set()
    for value in values:
        if not value.strip():
            continue
        key = comparison_key(field, value)
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result


def ranks(field: str, expected: str, values: list[str]) -> dict:
    key = comparison_key(field, expected)
    return {str(k): any(comparison_key(field, v) == key for v in values[:k]) for k in (1, 3, 5)}


def token_presence(field: str, expected: str, tokens: list[dict]) -> bool:
    # Evaluation only. This never defines a crop, candidate, or runtime choice.
    key = comparison_key(field, expected)
    for token in tokens:
        if comparison_key(field, token["text"]) == key:
            return True
        if field in {"patient_name", "insured_name"}:
            import re

            words = lambda v: sorted(re.findall(r"[A-Z]+", v.upper()))
            if words(token["text"]) == words(expected):
                return True
    return False


def secondary_gate(
    *,
    before: list[str],
    token_present: bool,
    visibility: dict,
    trial: dict,
    candidates: list[dict],
    captures: list[dict],
    token_candidate_match: bool = False,
) -> str | None:
    """Evaluation eligibility only; this function never provides text to OCR."""
    if before:
        return "PRIMARY_CANDIDATE_ALREADY_PRESENT"
    if token_candidate_match:
        return "REFERENCE_ALREADY_RECOVERED_FROM_PRIMARY_TOKENS"
    if token_present:
        return "REFERENCE_ALREADY_IN_PRIMARY_TOKEN_LINE"
    if visibility["visibility"] not in {"VISIBLE_CLEAR", "VISIBLE_LOW_QUALITY", "OVERPRINTED"}:
        return "SOURCE_VALUE_NOT_FULLY_VISIBLE"
    if visibility.get("representation_difference"):
        return "SOURCE_REFERENCE_REPRESENTATION_DIFFERENCE"
    if not any(
        c["page_number"] == trial["page_number"] and c["image_sha256"] == trial["image_sha256"]
        for c in captures
    ):
        return "SOURCE_HASH_MISMATCH"
    if not any(
        c["page_number"] == trial["page_number"] and list(c["bbox"]) == trial["bbox"]
        for c in candidates
    ):
        return "NO_VALID_LABEL_GROUNDED_REGION"
    if trial["mode"] == "trocr" and not visibility.get("handwriting_confirmed"):
        return "HANDWRITING_NOT_CONFIRMED"
    return None


def inferred_stage(
    *,
    missing: bool,
    localized: bool,
    present: bool,
    visibility: dict,
    tokens: list[dict],
    recovered: bool,
) -> str:
    """Explicit replay diagnosis, not an invented original-worker trace."""
    if visibility["visibility"] == "NOT_PRESENT":
        return "REFERENCE_NOT_VISIBLE_ON_SOURCE"
    if visibility.get("representation_difference"):
        return "ASSEMBLY_FAILED"
    if not localized:
        return "NO_LOCALIZATION"
    if present:
        return "FIELD_RULE_TOO_NARROW" if missing and recovered else "ASSEMBLY_FAILED"
    return "OCR_WRONG_TEXT" if tokens else "OCR_NO_TOKENS"


def build(root: Path = ROOT, *, require_complete: bool = True) -> dict:
    read = lambda p: json.loads(p.read_text(encoding="utf8"))
    out = root / "evaluation_results/governed_30_candidate_coverage"
    frozen = root / "evaluation_results/governed_30_root_cause/frozen"
    seals = read(frozen / "run_manifest.local.json")
    for original_path, seal in seals.items():
        if digest(frozen / seal["snapshot"]) != seal["sha256"]:
            raise ValueError("FROZEN_INPUT_CHANGED")
        if (
            original_path == "config/field_acceptance_policies.yaml"
            and digest(root / original_path) != seal["sha256"]
        ):
            raise ValueError("ACCEPTANCE_POLICY_CHANGED")
    inputs = read(out / "primary_capture_input.local.json")
    visibility_rows = read(out / "source_visibility.local.json")["fields"]
    visibility_index = {(r["claim_alias"], r["field"]): r for r in visibility_rows}
    trial_rows = [read(p) for p in sorted((out / "secondary_tokens").glob("*.local.json"))]
    mode_order = {"rapid": 0, "rapid_clahe": 1, "paddle": 2, "trocr": 3}
    trial_rows.sort(key=lambda r: (mode_order[r["mode"]], r["claim_alias"], r["field"]))
    trial_audit = []
    baseline = read(
        root / "evaluation_results/governed_30_root_cause/frozen/raw_execution.local.json"
    )
    reference = read(
        root / "evaluation_results/governed_30_root_cause/frozen/governed_30_reference.local.json"
    )
    eligible = read(root / "docs/qualification/governed_30_reconciled_failure_matrix.json")[
        "fields"
    ]
    all_slots = eligible
    eligible = [r for r in eligible if r["eligible"]]
    if len(eligible) != 118:
        raise ValueError("FROZEN_118_SLOT_DENOMINATOR_REQUIRED")
    captures = defaultdict(list)
    recovery: dict[str, list[dict]] = defaultdict(list)
    all_labels: dict[str, list[str]] = defaultdict(list)
    latencies = []
    missing_pages = []
    started = time.perf_counter()
    for page in inputs["pages"]:
        target = (
            out / "primary_tokens" / f"{page['claim_alias']}_P{page['page_number']:03d}.local.json"
        )
        if not target.exists():
            missing_pages.append((page["claim_alias"], page["page_number"]))
            continue
        capture = read(target)
        if (
            capture["claim_alias"] != page["claim_alias"]
            or capture["page_number"] != page["page_number"]
            or capture["engine"] != "paddleocr"
            or capture["model"] != "PP-OCRv4"
            or capture["max_full_page_side"] != 1600
            or capture["scope"] != "NEW_PRIMARY_ENGINE_CAPTURE_NOT_ORIGINAL_RUN_TOKENS"
        ):
            raise ValueError("PRIMARY_CAPTURE_PROVENANCE_MISMATCH")
        if (
            capture["image_sha256"] != page["image_sha256"]
            or digest(Path(page["image_path"])) != page["image_sha256"]
        ):
            raise ValueError("TOKEN_SOURCE_HASH_MISMATCH")
        text_lines = [TextLine(**t) for t in capture["tokens"]]
        with Image.open(page["image_path"]) as image:
            width, height = image.size
        candidates = generate(text_lines, width=width, height=height)
        alias = page["claim_alias"]
        captures[alias].append(capture)
        recovery[alias].extend(
            {**asdict(c), "page_number": page["page_number"]} for c in candidates
        )
        all_labels[alias].extend(f for _, f in labels(text_lines))
        latencies.append(capture["latency_seconds"])
    if require_complete and missing_pages:
        raise ValueError("PRIMARY_CAPTURE_INCOMPLETE")
    ci = {c["claim_alias"]: c for c in baseline["claims"]}
    if len(ci) != 30 or len({(r["claim_alias"], r["cdp_field"]) for r in eligible}) != 118:
        raise ValueError("FROZEN_COHORT_OR_SLOT_SET_CHANGED")
    ri = {c["claim_alias"]: c for c in reference["claims"]}
    policy = FieldPolicyRegistry.load(
        root / "evaluation_results/governed_30_root_cause/frozen/field_acceptance_policies.yaml"
    )
    manifest = read(
        root / "evaluation_results/governed_30_root_cause/frozen/governed_30_manifest.json"
    )
    runtime_metrics, _ = score(manifest, reference, baseline, policy)
    records = []
    private = []
    for slot in eligible:
        alias, field, form = slot["claim_alias"], slot["cdp_field"], slot["form_type"]
        expected = ri[alias]["fields"][field]["value"]
        rows = [
            r
            for r in ci[alias]["fields"]
            if r.get("service_line_number") is None
            and _canonical(policy, form, r["field_name"]) == slot["canonical_field"]
        ]
        before = unique_values(
            field,
            [r["raw_value"] for r in rows if r.get("raw_value")]
            + [a["raw_text"] for r in rows for a in r.get("candidates", []) if a.get("raw_text")],
        )
        added = [c for c in recovery[alias] if c["field_name"] == field]
        after = unique_values(field, before + [c["value"] for c in added])
        tokens = [t for c in captures[alias] for t in c["tokens"]]
        present = token_presence(field, expected, tokens)
        localized = field in all_labels[alias]
        vis = visibility_index[(alias, field)]
        before_r, token_r = ranks(field, expected, before), ranks(field, expected, after)
        secondary = []
        for trial in trial_rows:
            if (trial["claim_alias"], trial["field"]) != (alias, field):
                continue
            rejection = secondary_gate(
                before=before,
                token_present=present,
                visibility=vis,
                trial=trial,
                candidates=added,
                captures=captures[alias],
                token_candidate_match=any(
                    comparison_key(field, c["value"]) == comparison_key(field, expected)
                    for c in added
                ),
            )
            trial_audit.append(
                {
                    "claim_alias": alias,
                    "field": field,
                    "mode": trial["mode"],
                    "eligible": rejection is None,
                    "rejection": rejection,
                    "error_type": trial.get("error_type"),
                    "candidate_match": not rejection
                    and ranks(field, expected, trial["values"])["5"],
                    "seconds": trial["seconds"],
                    "rss_delta_bytes": trial["rss_delta_bytes"],
                    "rss_after_bytes": trial["rss_after_bytes"],
                }
            )
            if rejection is None and not trial.get("error_type"):
                secondary.extend(trial["values"])
        after = unique_values(field, after + secondary)
        after_r = ranks(field, expected, after)
        stage = (
            inferred_stage(
                missing=not before,
                localized=localized,
                present=present,
                visibility=vis,
                tokens=tokens,
                recovered=token_r["5"],
            )
            if not before_r["5"]
            else None
        )
        route, route_evidence = routing_state(
            ci[alias], rows, slot["canonical_field"], form, policy
        )
        if route != slot["routing_state"]:
            raise ValueError("FROZEN_ROUTE_CHANGED")
        record = {
            "claim_alias": alias,
            "form": form,
            "field": field,
            "critical": slot["critical"],
            "reference_available": True,
            "before_candidate_count": len(before),
            "candidate_count": len(after),
            "before_recall": before_r,
            "after_recall": after_r,
            "token_only_recall": token_r,
            "localization_attempted": True,
            "anchor_found": localized,
            "original_localization_trace": "NOT_PERSISTED",
            "crop_available": any(
                t["claim_alias"] == alias
                and t["field"] == field
                and t["eligible"]
                and not t["error_type"]
                for t in trial_audit
            ),
            "region_bbox_available": bool(added),
            "crop_note": "Actual bounded crop only when eligible secondary trial exists",
            "token_evidence_available": bool(tokens),
            "token_evidence_scope": "NEW_PRIMARY_CAPTURE_ACROSS_CLAIM_PAGES",
            "ocr_evidence_available": bool(tokens),
            "assembly_attempted": bool(added),
            "failure_stage": stage,
            "reference_in_new_primary_tokens": present,
            "original_token_availability": "NOT_RECORDED",
            "visibility": vis["visibility"],
            "source_visibility": vis,
            "visibility_status": "ENGINEERING_PIXEL_INSPECTION_COMPLETE",
            "failure_stage_authority": "NEW_CAPTURE_REPLAY_INFERENCE; original worker trace unavailable",
            "wrong_value_classification": None
            if not before or before_r["5"]
            else "ASSEMBLY_ERROR"
            if vis.get("representation_difference")
            else "WRONG_REGION"
            if rows and all(r.get("page_number") not in vis["source_pages"] for r in rows)
            else "CORRECT_VALUE_NOT_IN_CANDIDATES"
            if present
            else "OCR_VALUE_WRONG",
            "ranking_miss": bool(before) and not before_r["1"] and before_r["5"],
            "runtime_route": route,
            "runtime_route_evidence": route_evidence,
            "recovered_candidates_review_only": True,
        }
        records.append(record)
        private.append(
            {
                **record,
                "reference_value": expected,
                "before_candidates": before,
                "after_candidates": after,
                "recovery_evidence": added,
                "secondary_values": secondary,
            }
        )

    def recall(rows, stage):
        return {f"R@{k}": metric(sum(r[stage][str(k)] for r in rows), len(rows)) for k in (1, 3, 5)}

    missing = [r for r in records if not r["before_candidate_count"]]
    if (
        len(missing) != 102
        or sum(r["critical"] for r in records) != 86
        or sum(r["before_recall"]["1"] for r in records) != 1
        or sum(r["before_recall"]["5"] for r in records) != 2
    ):
        raise ValueError("FROZEN_CANDIDATE_BASELINE_CHANGED")
    blockers = defaultdict(list)
    for r in missing:
        blockers[(r["field"], r["failure_stage"])].append(r)
    ranked = sorted(
        (
            {
                "field": f,
                "failure_stage": stage,
                "count": len(rows),
                "critical_count": sum(r["critical"] for r in rows),
                "claims_affected": len({r["claim_alias"] for r in rows}),
                "claim_unlock_potential": "UNPROVEN; candidate coverage alone cannot unlock a claim",
            }
            for (f, stage), rows in blockers.items()
        ),
        key=lambda r: (-r["critical_count"], -r["claims_affected"], -r["count"], r["field"]),
    )
    summary = {
        "scope": "GOVERNED_ENGINEERING_REVIEW_ONLY_CANDIDATES",
        "reference_authority": "ENGINEERING_REFERENCE_ONLY",
        "comparable_fields": 118,
        "original_124_slot_missing": 108,
        "excluded_ambiguous_missing": 6,
        "missing_candidates_before": len(missing),
        "missing_candidates_after": sum(not r["candidate_count"] for r in records),
        "fields_with_new_candidate": sum(
            not r["before_candidate_count"] and bool(r["candidate_count"]) for r in records
        ),
        "before": recall(records, "before_recall"),
        "token_only": recall(records, "token_only_recall"),
        "critical_before": recall([r for r in records if r["critical"]], "before_recall"),
        "after": recall(records, "after_recall"),
        "critical_after": recall([r for r in records if r["critical"]], "after_recall"),
        "milestones": {
            "small_cohort": {
                "claim_alias": "CLM_A_001",
                "before": recall(
                    [r for r in records if r["claim_alias"] == "CLM_A_001"], "before_recall"
                ),
                "after": recall(
                    [r for r in records if r["claim_alias"] == "CLM_A_001"], "after_recall"
                ),
            },
            "all_claims": 30,
            "routing_scope": "Frozen runtime events reconciled; proposals never emitted",
        },
        "original_token_split": {
            "present": None,
            "absent": None,
            "unknown": len(missing),
            "reason": "ORIGINAL_FULL_TOKEN_STREAM_NOT_PERSISTED",
        },
        "new_primary_token_split": {
            "present": sum(r["reference_in_new_primary_tokens"] for r in missing),
            "not_matched_in_individual_line": sum(
                not r["reference_in_new_primary_tokens"] for r in missing
            ),
            "search_limit": "Individual text lines and name word-order equality; not exhaustive cross-token assembly",
            "denominator": len(missing),
            "capture_complete": not missing_pages,
        },
        "failure_counts": {
            stage: sum(r["failure_stage"] == stage for r in missing) for stage in STAGES
        },
        "pixel_visibility_pending": sum(r["visibility"] is None for r in missing),
        "captured_pages": sum(len(v) for v in captures.values()),
        "missing_capture_pages": len(missing_pages),
        "new_primary_ocr_seconds": sum(latencies),
        "candidate_replay_seconds": time.perf_counter() - started,
        "secondary_ocr": {
            "attempts": len(trial_audit),
            "completed_calls": sum(not t["error_type"] for t in trial_audit),
            "excluded_calls": sum(not t["eligible"] for t in trial_audit),
            "rejected_region_calls": sum(
                t["rejection"] == "NO_VALID_LABEL_GROUNDED_REGION" for t in trial_audit
            ),
            "redundant_token_recovery_calls": sum(
                t["rejection"] == "REFERENCE_ALREADY_RECOVERED_FROM_PRIMARY_TOKENS"
                for t in trial_audit
            ),
            "successful_field_recoveries": sum(
                r["after_recall"]["5"] and not r["token_only_recall"]["5"] for r in records
            ),
            "seconds_including_rejected_trials": sum(t["seconds"] for t in trial_audit),
            "maximum_observed_process_rss_bytes": max(
                (t["rss_after_bytes"] for t in trial_audit), default=0
            ),
            "memory_measurement": "Process RSS after calls; not peak or isolated engine memory",
            "trials": trial_audit,
        },
        "visibility_counts": dict(Counter(r["visibility"] for r in missing)),
        "status": "CANDIDATE_COVERAGE_IMPROVED"
        if sum(r["after_recall"]["5"] for r in records)
        > sum(r["before_recall"]["5"] for r in records)
        else "BLOCKED",
        "retention_gates": {
            "recall_at_5_improved": sum(r["after_recall"]["5"] for r in records)
            > sum(r["before_recall"]["5"] for r in records),
            "critical_recall_at_5_not_regressed": all(
                not r["before_recall"]["5"] or r["after_recall"]["5"]
                for r in records
                if r["critical"]
            ),
            "runtime_integration": "NOT_ENABLED; research candidate proposals only",
            "secondary_permanent_enablement": False,
            "latency_gate": "BOUNDED_7_FINAL_ELIGIBLE_REGIONS; production budget not measured or approved",
        },
        "claim_hitl": runtime_metrics["claim_hitl"],
        "true_stp": runtime_metrics["true_stp"],
        "output_failure_types": runtime_metrics["pipeline_failure_types"],
        "production_changes": False,
        "ranking_changes": False,
        "acceptance_changes": False,
        "routing_transitions": {
            "status": "ROUTES_RECONCILED_FROM_FROZEN_EVENTS_AT_BOTH_CANDIDATE_MILESTONES; no worker emission from review-only proposals",
            "NOT_EMITTED_to_HITL": 0,
            "NOT_EMITTED_to_AUTO_ACCEPTED": 0,
            "HITL_to_AUTO_ACCEPTED": 0,
            "field_routes": {
                "AUTO_ACCEPTED": sum(r["runtime_route"] == "AUTO_ACCEPTED" for r in records),
                "HITL": sum(r["runtime_route"] == "HITL" for r in records),
                "NOT_EMITTED": sum(r["runtime_route"] == "NOT_EMITTED" for r in records),
                "NOT_ELIGIBLE": len(all_slots) - len(eligible),
                "UNKNOWN": sum(r["runtime_route"].startswith("UNKNOWN") for r in records),
            },
        },
        "field_results": {
            f: {
                "before": recall([r for r in records if r["field"] == f], "before_recall"),
                "after": recall([r for r in records if r["field"] == f], "after_recall"),
            }
            for f in sorted({r["field"] for r in records})
        },
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, data in {
        "coverage_summary.local.json": summary,
        "coverage_records.local.json": private,
        "candidate_failure_matrix.local.json": {"fields": records},
        "top_candidate_blockers.local.json": ranked,
        "wrong_candidate_values.local.json": [
            r for r in records if r["wrong_value_classification"]
        ],
        "ranking_miss.local.json": [r for r in records if r["ranking_miss"]],
    }.items():
        (out / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf8")
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
