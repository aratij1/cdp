"""Closure accounting: detailed evidence stays local; publish aggregates only.

Visibility annotations are inspection evidence, never extraction input or labels.
No absence of recorded technical blockers grants release qualification.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from statistics import median

from evaluation.cdp2_comparison import latency_summary, legacy_and_graph, write
from evaluation.closure_iteration2 import INPUT, OBS, ROOT
from evaluation.closure_performance_gate import compare_runs
from packages.candidate_reconciliation import EvidenceReconciler
from packages.claim_intelligence.document import fingerprint
from packages.claim_intelligence.normalization import comparison_key

LOCAL = ROOT / "evaluation_results/closure/iteration3"
VISIBILITY = frozenset(
    {
        "VISIBLE_IN_EXISTING_TOKENS",
        "VISIBLE_IN_PIXELS_BUT_NOT_OCR",
        "PARTIALLY_VISIBLE",
        "NOT_VISIBLE",
        "REFERENCE_CONFLICT",
        "UNKNOWN",
    }
)


def external_categories(field: str, blockers: list[str]) -> list[str]:
    result = set()
    for blocker in blockers:
        if blocker == "AUTHORITATIVE_DATA_REQUIRED":
            result.add(
                {
                    "member_id": "MEMBER_AUTHORITY_REQUIRED",
                    "subscriber_id": "MEMBER_AUTHORITY_REQUIRED",
                    "provider_name": "PROVIDER_AUTHORITY_REQUIRED",
                    "patient_name": "PATIENT_IDENTITY_AUTHORITY_REQUIRED",
                    "insured_name": "PATIENT_IDENTITY_AUTHORITY_REQUIRED",
                }.get(field, "OTHER_EXTERNAL")
            )
        elif blocker == "EVIDENCE_REQUIRED":
            result.add("SOURCE_EVIDENCE_REQUIRED")
        else:
            # Unknown blocker reasons must remain visible rather than disappearing.
            result.add("OTHER_EXTERNAL")
    return sorted(result)


def hitl_summary(fields: list[dict]) -> dict:
    if not fields or len({(r["claim_id"], r["field"]) for r in fields}) != len(fields):
        raise ValueError("UNIQUE_NONEMPTY_FIELD_DENOMINATOR_REQUIRED")
    technical = sum(bool(r["technical"]) for r in fields)
    external = sum(bool(r["external"]) for r in fields)
    union = sum(bool(r["technical"] or r["external"]) for r in fields)
    return {
        "scope": "ENGINEERING_FROZEN_COHORT",
        "fields": len(fields),
        "technical_review_fields": technical,
        "external_review_fields": external,
        "total_observed_review_fields": union,
        "technical_hitl_rate": technical / len(fields),
        "external_hitl_rate": external / len(fields),
        "total_observed_hitl_rate": union / len(fields),
        "external_blocker_field_counts": dict(
            Counter(category for r in fields for category in set(r["external"]))
        ),
        "production_measured": False,
    }


def audited_visibility(row: dict, observation: dict, annotation: dict | None) -> str:
    expected = comparison_key(row["field_name"], row["truth"])
    if any(
        comparison_key(row["field_name"], t["text"]) == expected for t in observation["ocr_tokens"]
    ):
        return "VISIBLE_IN_EXISTING_TOKENS"
    if annotation is None:
        return "UNKNOWN"
    if annotation.get("page_sha256") != observation["page_sha256"]:
        raise ValueError("VISIBILITY_SOURCE_BINDING_MISMATCH")
    state = annotation["visibility"]
    if state not in VISIBILITY or state == "VISIBLE_IN_EXISTING_TOKENS":
        raise ValueError("INVALID_PIXEL_VISIBILITY_ANNOTATION")
    return state


def ceiling_status(items: list[dict]) -> str:
    remaining = [r for r in items if not r["governed_recovered_after"]]
    # A visual impression of absence alone is insufficient to prove a ceiling.
    return (
        "PROVEN_SOURCE_CEILING"
        if remaining
        and all(
            r["visibility"] == "NOT_VISIBLE" and r.get("independently_adjudicated")
            for r in remaining
        )
        else "NOT_PROVEN"
    )


def run() -> dict:
    prior = json.loads((LOCAL.parent / "iteration2/final_candidate.json").read_text())
    current = json.loads((LOCAL.parent / "iteration2/iteration3_atomic_fields.json").read_text())
    if any(
        prior[k] != current[k]
        for k in (
            "cohort_sha256",
            "evidence_sha256",
            "canonical_outputs_sha256",
        )
    ):
        raise ValueError("FROZEN_BASELINE_OR_CANONICAL_OUTPUT_CHANGED")
    rows = [json.loads(line) for line in INPUT.read_text().splitlines() if line]
    by_field = {(fingerprint(r["document_id"]), r["field_name"]): r for r in rows}
    annotations = json.loads((LOCAL / "pixel_visibility_review.json").read_text())
    annotations = {(r["claim_id"], r["field"]): r for r in annotations}
    after = {(r["claim_id"], r["field"]): r for r in current["missing_candidate_root_causes"]}
    distances = {r["claim_id"]: r for r in current["claim_distances"]}
    audit = []
    for old in prior["missing_candidate_root_causes"]:
        if old["recovered"]:
            continue
        key = old["claim_id"], old["field"]
        row = by_field[key]
        observation = json.loads((OBS / (row["document_id"] + ".json")).read_text())
        state = audited_visibility(row, observation, annotations.get(key))
        cause = annotations.get(key, {}).get("root_cause", old["primary_root_cause"])
        distance = distances[key[0]]["technical_distance_after"]
        criticality = {"C1": 1, "C2": 2, "C3": 3}.get(old["criticality"], 1)
        fixability = 1 if state == "VISIBLE_IN_EXISTING_TOKENS" else 0.25
        audit.append(
            {
                **old,
                "visibility": state,
                "primary_root_cause": cause,
                "page_id": fingerprint(observation["page_id"]),
                "source_sha256": observation["page_sha256"],
                "exact_recovered_after": after[key]["recovered"],
                "governed_recovered_after": after[key]["governed_recovered"],
                "technical_unlock_distance": distance,
                "inspection_authority": "ENGINEERING_VISUAL_INSPECTION_NOT_TRUTH",
                "independently_adjudicated": False,
                "required_missing_evidence": "SOURCE_BOUND_FIELD_ASSOCIATION_OR_INDEPENDENT_REVIEW",
                "attempted_fixes": [
                    "LITERAL_LABEL_DISCOVERY",
                    "GOVERNED_COMPARISON",
                    "BOUNDED_ATOMIC_FIELD_DISCOVERY",
                ],
                "unsafe_recovery_rejected": "NO_FUZZY_CHARACTERS_OR_REFERENCE_DRIVEN_CROPS",
                "priority_score": criticality * fixability / max(1, distance),
            }
        )
    volumes = Counter((r["primary_root_cause"], r["field"]) for r in audit)
    for item in audit:
        item["blocker_volume"] = volumes[item["primary_root_cause"], item["field"]]
        item["priority_score"] *= item["blocker_volume"]
    if len(audit) != 29:
        raise ValueError("ITERATION3_STARTING_MISSING_DENOMINATOR_CHANGED")
    write(
        LOCAL,
        "missing_candidate_root_causes.json",
        sorted(audit, key=lambda r: (-r["priority_score"], r["claim_id"], r["field"])),
    )
    groups = defaultdict(list)
    for row in rows:
        groups[row["document_id"]].append(
            {k: v for k, v in row.items() if k not in {"truth", "exact", "cross_field_evidence"}}
        )
    remaining = {
        (r["claim_id"], r["field"]): r["remaining_technical"] for r in current["review_fields"]
    }
    fields, claims = [], []
    for claim, inputs in sorted(groups.items()):
        legacy, _, _ = legacy_and_graph(claim, inputs, EvidenceReconciler())
        claim_id = fingerprint(claim)
        claim_fields = []
        for f in legacy.fields:
            technical = remaining.get((claim_id, f.field_name), [])
            external = external_categories(f.field_name, list(f.evidence_blockers))
            item = {
                "claim_id": claim_id,
                "field": f.field_name,
                "technical": technical,
                "external": external,
                "critical": f.critical,
                "extraction_state": "RECORDED_TECHNICAL_BLOCKERS"
                if technical
                else "NO_RECORDED_TECHNICAL_BLOCKERS",
                "authority_state": "REQUIRED_UNAVAILABLE" if external else "NO_RECORDED_FIELD_GAP",
            }
            fields.append(item)
            claim_fields.append(item)
        technical = sum(len(f["technical"]) for f in claim_fields)
        external_count = sum(len(f["external"]) for f in claim_fields)
        assert technical == distances[claim_id]["technical_distance_after"]
        claims.append(
            {
                "claim_id": claim_id,
                "fields": claim_fields,
                "technical_unlock_distance": technical,
                "recorded_evidence_blockers": external_count,
                "claim_authority_blockers": ["ACCEPTANCE_AUTHORITY_GAP"],
                "production_unlock_distance": technical + external_count + 1,
                "production_distance_scope": "RECORDED_FIELDS_PLUS_ONE_RELEASE_QUALIFICATION_GAP",
                "critical_blocked_fields": sum(
                    f["critical"] and bool(f["technical"] or f["external"]) for f in claim_fields
                ),
                "technical_stp_capable": technical == 0,
                "production_stp_capable": False,
                "production_authority": False,
            }
        )
    clean = [c for c in claims if c["technical_stp_capable"]]
    write(LOCAL, "technically_clean_claim_closure_matrix.json", clean)
    write(
        LOCAL,
        "remaining_claim_closure_matrix.json",
        [c for c in claims if not c["technical_stp_capable"]],
    )
    write(LOCAL, "field_extraction_authority_disposition.json", fields)
    hitl = hitl_summary(fields)
    write(LOCAL, "hitl_ceiling.json", hitl)
    operational = json.loads((LOCAL.parent / "noncanonical_candidate_result.json").read_text())
    repeats = [
        json.loads((LOCAL / f"repeat_{i}.json").read_text())["experiments"][0] for i in range(1, 4)
    ]
    baseline = json.loads((LOCAL.parent / "iteration2/repeat_3.json").read_text())["experiments"][0]
    gates = [compare_runs(baseline, r) for r in repeats]
    latency = {
        "scope": "FRESH_OCR_ROUTING_SPATIAL_SHADOW_NOT_COMPLETE_CLAIM_PROCESSING",
        "pages_per_run": 12,
        "workers": 1,
        "threads": 8,
        "cpu_memory_arena": True,
        "p95_ms": [r["latency"]["P95"] for r in repeats],
        "median_p95_ms": median(r["latency"]["P95"] for r in repeats),
        "median_p50_ms": median(r["latency"]["P50"] for r in repeats),
        "median_p99_ms": median(r["latency"]["P99"] for r in repeats),
        "median_throughput_pages_s": median(
            r["latency"]["throughput_pages_per_second"] for r in repeats
        ),
        "cold_model_load_ms": [r["model_load_ms"] for r in repeats],
        "first_page_ms": [r["pages"][0]["stages"]["total_ms"] for r in repeats],
        "max_sampled_rss_bytes": max(p["memory_rss_bytes"] for r in repeats for p in r["pages"]),
        "semantics_identical": all(g["identical_semantics"] for g in gates),
        "complete_production_path_measured": False,
        "target_met": False,
    }
    latency["warm_page_p95_ms"] = [
        latency_summary([p["stages"]["total_ms"] for p in r["pages"][1:]])["P95"] for r in repeats
    ]
    latency["host_measurements"] = [
        json.loads((LOCAL / f"repeat_{i}_host.json").read_text()) for i in range(1, 4)
    ]
    latency["p95_page_stage_ms"] = [
        max(r["pages"], key=lambda p: p["stages"]["total_ms"])["stages"] for r in repeats
    ]
    if any(len(p["ocr_internal_ms"]) != 3 for r in repeats for p in r["pages"]):
        raise ValueError("OCR_STAGE_PROFILE_INCOMPLETE")
    latency["median_mean_ocr_internal_ms"] = {
        name: median(sum(p["ocr_internal_ms"][i] for p in r["pages"]) / 12 for r in repeats)
        for i, name in enumerate(("detection", "classification", "recognition"))
    }
    latency["postprocessing_separate_ms"] = None
    latency["production_cache_hit_distribution"] = "NOT_MEASURED"
    latency["configuration_changed_since_iteration2"] = False
    write(LOCAL, "performance_repetitions.json", {"summary": latency, "gates": gates})
    summary = {
        "status": "CONTINUE",
        "scope": "ENGINEERING_FROZEN_200_FIELDS_20_CLAIMS",
        "exact_missing_before": 29,
        "exact_missing_after": current["candidate"]["summary"]["buckets"][
            "TRUTH_NOT_IN_CANDIDATES"
        ],
        "exact_recall": current["candidate"]["summary"]["recall"],
        "governed_recall": current["governed_candidate"]["summary"]["recall"],
        "governed_missing_after": current["governed_candidate"]["summary"]["buckets"][
            "TRUTH_NOT_IN_CANDIDATES"
        ],
        "visibility_counts_starting_29": dict(Counter(r["visibility"] for r in audit)),
        "root_cause_counts_starting_29": dict(Counter(r["primary_root_cause"] for r in audit)),
        "technical_blockers": current["technical_blockers_after"],
        "technical_stp_capable_claims": len(clean),
        "total_claims": len(claims),
        "technical_stp_capable_rate": len(clean) / len(claims),
        "production_stp_capable_with_available_evidence": 0,
        "claim_distance_counts": dict(Counter(str(c["technical_unlock_distance"]) for c in claims)),
        "hitl": hitl,
        "latency": latency,
        "clean_claim_external_field_counts": dict(
            Counter(category for c in clean for f in c["fields"] for category in f["external"])
        ),
        "clean_claim_acceptance_authority_gaps": len(clean),
        "operational": {
            k: operational[k]
            for k in (
                "pages",
                "pages_with_candidates",
                "candidate_counts",
                "candidate_field_pairs",
                "ambiguous_field_pairs",
                "no_candidate_pages",
                "regional_ocr_calls",
                "new_ocr_calls",
                "vlm_calls",
                "canonical_localizations",
                "package_leakage",
                "observed_rss_bytes",
                "elapsed_ms",
                "runtime_scope",
            )
        },
        "canonical_outputs_changed": False,
        "production_authority": False,
        "technical_ceiling_status": ceiling_status(audit),
        "external_ceiling_status": "REQUIRED_AUTHORITY_UNAVAILABLE_NOT_A_NUMERIC_CEILING",
        "release_metrics": {
            k: {"value": None, "status": "NOT_EVALUABLE"}
            for k in (
                "accuracy",
                "critical_accuracy",
                "accepted_precision",
                "critical_false_accepts",
                "field_hitl",
                "claim_hitl",
                "stp",
            )
        },
    }
    summary["critical_c3_fields"] = current["governed_candidate"]["by_dimension"]["criticality"][
        "C3"
    ]["fields"]
    summary["critical_c3_recall_at_5"] = current["governed_candidate"]["by_dimension"][
        "criticality"
    ]["C3"]["recall"]["R@5"]
    before_fields = {(r["claim"], r["field"]): r for r in prior["governed_candidate"]["fields"]}
    after_fields = current["governed_candidate"]["fields"]
    summary["selected_value_correct_fields"] = sum(r["top1_correct"] for r in after_fields)
    summary["candidate_coverage_regressions"] = sum(
        before_fields[r["claim"], r["field"]]["reference_rank"] is not None
        and r["reference_rank"] is None
        for r in after_fields
    )
    summary["selected_value_regressions"] = sum(
        before_fields[r["claim"], r["field"]]["top1_correct"] and not r["top1_correct"]
        for r in after_fields
    )
    validation_path = LOCAL / "validation_aggregate.json"
    summary["validation"] = (
        json.loads(validation_path.read_text())
        if validation_path.exists()
        else {"status": "PENDING"}
    )
    # Explicit aggregate allowlist above excludes all claim/page/source hashes and values.
    write(ROOT / "docs/closure", "iteration3_summary.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
