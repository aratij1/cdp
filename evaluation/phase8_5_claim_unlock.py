"""Phase 8.5 claim-unlock analysis over frozen Phase 8.4 decisions.

This module is deliberately OCR-free. It consumes persisted candidates,
evidence bundles, field decisions, and canonical claim decisions.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluation_results/phase8_4"
EXTRACTION = ROOT / "evaluation_results/phase8_2/final/metrics.json"
ECONOMICS = ROOT / "evaluation_results/phase8_3/production_economics.json"
OBSERVATIONS = ROOT / "evaluation_results/phase8_1/observations"
OUTPUT = ROOT / "evaluation_results/phase8_5"
DOCS = ROOT / "docs"
ACCEPTED = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED", "HUMAN_CONFIRMED"}
CLASSIFICATIONS = {
    "MISSING_EXTRACTION",
    "WRONG_EXTRACTION_SAFE_REJECT",
    "CORRECT_MISSING_EVIDENCE",
    "TRUE_AMBIGUITY",
    "REFERENCE_REQUIRED",
    "POLICY_UNREACHABLE",
    "CROSS_FIELD_CONTRADICTION",
    "UNSUPPORTED",
}


def read_json(path: Path):
    return json.loads(path.read_text("utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", "utf-8")


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in values), "utf-8")


def classify(field: dict | None, decision: dict | None, reach: dict | None) -> str:
    if field is None:
        return "MISSING_EXTRACTION"
    bundle = (decision or {}).get("evidence_bundle") or {}
    if (decision or {}).get("conflicting_evidence") or bundle.get("contradictions"):
        return "TRUE_AMBIGUITY"
    if not field.get("exact"):
        return "WRONG_EXTRACTION_SAFE_REJECT"
    missing = set((decision or {}).get("missing_evidence") or [])
    if reach and reach.get("status") == "UNREACHABLE_POLICY":
        return "POLICY_UNREACHABLE"
    if missing == {"E5"}:
        return "REFERENCE_REQUIRED"
    return "CORRECT_MISSING_EVIDENCE"


def run(output: Path = OUTPUT) -> dict:
    extraction = read_json(EXTRACTION)
    frozen = read_json(SOURCE / "profile_c/metrics.json")
    expected = {
        "safe_field_coverage": 0.6621052631578948,
        "field_hitl": 0.33789473684210525,
        "review_fields_per_page": 3.21,
        "claim_hitl": 1.0,
        "claim_stp": 0.0,
        "false_accepts": 0,
        "critical_false_accepts": 0,
    }
    mismatch = {
        k: {"expected": v, "actual": frozen[k]} for k, v in expected.items() if frozen[k] != v
    }
    if mismatch:
        raise RuntimeError(f"PHASE8_4_FREEZE_MISMATCH:{mismatch}")
    if (
        extraction["by_family"]["CMS1500"]["final_field_accuracy"] < 0.95
        or extraction["by_family"]["UB04"]["final_field_accuracy"] < 0.96
        or extraction["critical_field_accuracy"] < 0.955
    ):
        raise RuntimeError("FROZEN_EXTRACTION_GATE_FAILED")

    fields = read_jsonl(SOURCE / "profile_c/field_decisions.jsonl")
    claims = read_jsonl(SOURCE / "profile_c/claim_decisions.jsonl")
    reach_doc = read_json(SOURCE / "profile_c/policy_reachability.json")
    by_key = {(r["document_id"], r["field_name"]): r for r in fields}
    by_claim: dict[str, list[dict]] = defaultdict(list)
    for field in fields:
        by_claim[field["document_id"]].append(field)
    reach = {(r["document_family"], r["field_name"]): r for r in reach_doc["results"]}

    matrix = []
    blocker_rows = []
    for claim in claims:
        claim_id = claim["claim_id"]
        claim_fields = by_claim[claim_id]
        family = claim_fields[0]["family"]
        blockers = list(claim["blocking_unresolved_fields"])
        per_blocker = []
        for name in blockers:
            field = by_key.get((claim_id, name))
            decision = field["field_decision"] if field else None
            reach_row = reach.get((family, name))
            kind = classify(field, decision, reach_row)
            assert kind in CLASSIFICATIONS
            available = sorted((decision or {}).get("available_evidence") or [])
            missing = sorted((decision or {}).get("missing_evidence") or [])
            item = {
                "claim_id": claim_id,
                "family": family,
                "field": name,
                "criticality": (decision or {}).get(
                    "criticality", "C2" if name == "federal_tax_no" else "UNKNOWN"
                ),
                "classification": kind,
                "correct": None if field is None else bool(field["exact"]),
                "extracted": bool(field and field.get("final_value")),
                "available_evidence": available,
                "missing_evidence": missing,
                "policy_reachability": (reach_row or {}).get("status"),
                "blocking_field_count": len(blockers),
                "claim_unlock_value": 1 / len(blockers),
            }
            per_blocker.append(item)
            blocker_rows.append(item)
        nonblocking = [
            r["field_name"]
            for r in claim_fields
            if r["field_decision"]["disposition"] not in ACCEPTED
            and not r["field_decision"]["blocks_stp"]
        ]
        perfect = all(r["exact"] for r in claim_fields)
        matrix.append(
            {
                "claim_id": claim_id,
                "family": family,
                "perfect_extraction": perfect,
                "blocking_fields": blockers,
                "blocking_field_count": len(blockers),
                "nonblocking_review_fields": nonblocking,
                "critical_blockers": claim["critical_blockers"],
                "correct_but_reviewed_blockers": [
                    r["field"] for r in per_blocker if r["correct"] is True
                ],
                "wrong_and_rejected_blockers": [
                    r["field"]
                    for r in per_blocker
                    if r["classification"] == "WRONG_EXTRACTION_SAFE_REJECT"
                ],
                "missing_extraction_blockers": [
                    r["field"] for r in per_blocker if r["classification"] == "MISSING_EXTRACTION"
                ],
                "missing_evidence_blockers": [
                    r["field"]
                    for r in per_blocker
                    if r["classification"]
                    in {"CORRECT_MISSING_EVIDENCE", "REFERENCE_REQUIRED", "POLICY_UNREACHABLE"}
                ],
                "claim_disposition": claim["disposition"],
                "potential_unlock_fields": blockers,
                "blocker_details": per_blocker,
            }
        )

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in blocker_rows:
        grouped[(row["family"], row["field"])].append(row)
    severity = {"C3": 3, "C2": 2, "C1": 1, "C0": 0, "UNKNOWN": -1}
    pareto = []
    for (family, field_name), rows in grouped.items():
        counts = Counter(r["classification"] for r in rows)
        available = Counter(e for r in rows for e in r["available_evidence"])
        missing = Counter(e for r in rows for e in r["missing_evidence"])
        effort = "HIGH" if counts["MISSING_EXTRACTION"] else "MEDIUM"
        pareto.append(
            {
                "family": family,
                "field": field_name,
                "criticality": rows[0]["criticality"],
                "claims_blocked": len(rows),
                "single_blocker_claims": sum(r["blocking_field_count"] == 1 for r in rows),
                "two_blocker_claims": sum(r["blocking_field_count"] == 2 for r in rows),
                "multi_blocker_claims": sum(r["blocking_field_count"] >= 3 for r in rows),
                "correct_but_reviewed": sum(r["correct"] is True for r in rows),
                "wrong_and_rejected": counts["WRONG_EXTRACTION_SAFE_REJECT"],
                "unextracted": counts["MISSING_EXTRACTION"],
                "unsupported": counts["UNSUPPORTED"],
                "missing_evidence": dict(missing),
                "available_evidence": dict(available),
                "classification_counts": dict(counts),
                "claim_unlock_value": sum(r["claim_unlock_value"] for r in rows),
                "implementation_effort": effort,
            }
        )
    pareto.sort(
        key=lambda r: (
            -r["single_blocker_claims"],
            -r["claim_unlock_value"],
            -severity[r["criticality"]],
            r["implementation_effort"],
            r["field"],
        )
    )

    remaining = {(r["claim_id"], r["family"]): set(r["blocking_fields"]) for r in matrix}
    resolved: set[tuple[str, str]] = set()
    waterfall = []
    all_fields = {(r["family"], r["field"]) for r in blocker_rows}
    while all_fields - resolved:
        choices = []
        for candidate in all_fields - resolved:
            trial = resolved | {candidate}
            unlocked = sum(
                all((family, field) in trial for field in blockers)
                for (_, family), blockers in remaining.items()
            )
            p = next(r for r in pareto if (r["family"], r["field"]) == candidate)
            choices.append(
                (unlocked, p["claim_unlock_value"], severity[p["criticality"]], candidate)
            )
        unlocked, _, _, selected = max(choices)
        resolved.add(selected)
        waterfall.append(
            {
                "step": len(waterfall) + 1,
                "resolved_blocker": {"family": selected[0], "field": selected[1]},
                "cumulative_claims_unlocked": unlocked,
                "counterfactual_claim_stp": unlocked / len(claims),
                "analysis_only": True,
            }
        )

    ub_obs = sorted(OBSERVATIONS.glob("UB*.json"))
    label_hits = 0
    value_like_hits = 0
    aliases = ("FEDERAL TAX", "TAX ID", "EIN")
    for path in ub_obs:
        observation = read_json(path)
        texts = [token["text"].upper() for token in observation.get("ocr_tokens", [])]
        label_hits += any(any(alias in text for alias in aliases) for text in texts)
        value_like_hits += any(
            len("".join(ch for ch in text if ch.isdigit())) == 9 for text in texts
        )
    federal = {
        "field": "federal_tax_no",
        "datatype": "TAX_IDENTIFIER",
        "field_observations": len(ub_obs),
        "golden_truth_rows": 0,
        "observable_labels": label_hits,
        "nine_digit_value_like_tokens": value_like_hits,
        "localization_success": 0,
        "raw_accuracy": None,
        "secondary_ocr_invocations": 0,
        "secondary_ocr_rate": 0.0,
        "accepted_precision": None,
        "false_accepts": 0,
        "critical_false_accepts": 0,
        "safe_coverage": None,
        "claims_unlocked": 0,
        "counterfactual_claims_unlocked_if_legitimately_resolved": 50,
        "reason": "GOLDEN_PACK_OMITS_REQUIRED_FIELD_LABEL_VALUE_AND_TRUTH",
        "fabricated_values": 0,
    }

    def field_analysis(name: str, family: str = "CMS1500") -> dict:
        rows = [r for r in blocker_rows if r["family"] == family and r["field"] == name]
        return {
            "family": family,
            "field": name,
            "claims_blocked": len(rows),
            "correct_but_reviewed": sum(r["correct"] is True for r in rows),
            "wrong_and_rejected": sum(r["correct"] is False for r in rows),
            "true_ambiguity": sum(r["classification"] == "TRUE_AMBIGUITY" for r in rows),
            "unsupported": sum(r["classification"] == "UNSUPPORTED" for r in rows),
            "evidence_availability": dict(
                Counter(e for r in rows for e in r["available_evidence"])
            ),
            "missing_evidence": dict(Counter(e for r in rows for e in r["missing_evidence"])),
            "claims_unlocked": 0,
            "ocr_reruns": 0,
        }

    member = field_analysis("member_id")
    npi = field_analysis("provider_npi")
    total = field_analysis("total_charge")
    financial = {
        "evidence_model": "ClaimFinancialReconciliationEvidence",
        "configured_absolute_tolerance_usd": "0.01",
        "configured_relative_tolerance": "0.0001",
        "cms_total_charge_blockers": total["claims_blocked"],
        "cms_service_line_charge_sets_available": 0,
        "cms_e6_generated": 0,
        "extracted_values_modified": 0,
        "reason": "CMS golden records contain no service-line charges; reconciliation cannot be fabricated.",
    }
    e5_optional_rows = []
    e5_sufficient_rows = []
    for row in blocker_rows:
        reach_row = reach.get((row["family"], row["field"])) or {}
        combinations = [set(combo) for combo in reach_row.get("configured_combinations", [])]
        available = set(row["available_evidence"])
        if any("E5" in combo for combo in combinations) and any(
            "E5" not in combo for combo in combinations
        ):
            e5_optional_rows.append(row)
        if any(combo <= available | {"E5"} for combo in combinations):
            e5_sufficient_rows.append(row)
    sufficient_keys = {(r["claim_id"], r["field"]) for r in e5_sufficient_rows}
    claims_resolved_by_e5_alone = sum(
        all(
            (row["claim_id"], detail["field"]) in sufficient_keys
            for detail in row["blocker_details"]
        )
        for row in matrix
    )
    reference = {
        "state": "DISABLED",
        "authorized_reference_sources": 0,
        "claims_blocked_only_by_missing_e5": claims_resolved_by_e5_alone,
        "claims_where_e5_is_optional": len({r["claim_id"] for r in e5_optional_rows}),
        "claims_where_e5_would_still_be_insufficient": len(
            {
                row["claim_id"]
                for row in blocker_rows
                if (row["claim_id"], row["field"]) not in sufficient_keys
            }
        ),
        "blocker_instances_where_e5_is_optional": len(e5_optional_rows),
        "blocker_instances_resolvable_by_e5_alone": len(e5_sufficient_rows),
        "fabricated_reference_records": 0,
    }

    baseline = {
        "phase": "8.5",
        "frozen_phase8_4_commit": "2e064a44b1c03131a8cd0d584b3ba0e97ebdcc5b",
        "phase8_4_reproduced_exactly": True,
        "extraction": extraction,
        "evidence_and_claim": frozen,
        "ocr_reruns": 0,
    }
    base_profile = {
        **frozen,
        "profile_name": "PHASE8_4_BASELINE",
        "claims_unlocked": 0,
        "fields_newly_accepted": 0,
        "claim_unlock_efficiency": None,
        "common_path_cloud_cost_usd": 0.0,
    }
    profile_b = {
        **base_profile,
        "profile_name": "UB_MISSING_FIELD_RECOVERY",
        "federal_tax_no_observable_instances": 0,
        "result": "NO_PROMOTION_NO_OBSERVABLE_FIELD",
    }
    profile_c = {
        **base_profile,
        "profile_name": "CLAIM_BLOCKER_EVIDENCE_RECOVERY",
        "new_legitimate_evidence_instances": 0,
        "result": "NO_PROMOTION_NO_INDEPENDENT_EVIDENCE",
    }

    economics = read_json(ECONOMICS)
    review_field_cost = economics["review_cost_per_field_usd"]
    review_cost = frozen["review_fields_per_page"] * review_field_cost
    claim_overhead = economics["claim_overhead_cost_per_page_usd"] * frozen["claim_hitl"]
    hitl_cost = review_cost + claim_overhead
    full_cost = (
        hitl_cost
        + economics["throughput_based_machine_cost_per_page_usd"]
        + economics["shared_infrastructure_cost_per_page_usd"]
    )
    cost = {
        "assumptions": economics["configuration"],
        "review_fields_per_page": frozen["review_fields_per_page"],
        "review_cost_per_field_usd": review_field_cost,
        "field_review_cost_per_page_usd": review_cost,
        "claim_review_overhead_cost_per_page_usd": claim_overhead,
        "hitl_cost_per_page_usd": hitl_cost,
        "machine_cost_per_page_usd": economics["throughput_based_machine_cost_per_page_usd"],
        "shared_infrastructure_cost_per_page_usd": economics[
            "shared_infrastructure_cost_per_page_usd"
        ],
        "cloud_cost_per_page_usd": 0.0,
        "fully_loaded_cost_per_page_usd": full_cost,
        "cost_per_stp_claim_usd": None,
        "review_cost_avoided_usd": 0.0,
        "claims_unlocked": 0,
    }
    perfect = {
        "perfect_claims_currently_blocked": sum(r["perfect_extraction"] for r in matrix),
        "perfect_claims_unlocked": 0,
        "perfect_claims_remaining_blocked": sum(r["perfect_extraction"] for r in matrix),
        "metric": "PERFECT_BUT_NOT_STP",
        "reasons": dict(
            Counter(
                d["classification"]
                for r in matrix
                if r["perfect_extraction"]
                for d in r["blocker_details"]
            )
        ),
    }
    decision = {
        "decision": "NO_PROMOTION",
        "production_state": "SAFE_HITL",
        "safety_gate_passed": True,
        "first_claim_stp_target_met": False,
        "critical_false_accepts": 0,
        "total_false_accepts": 0,
        "accepted_precision": 1.0,
        "claim_stp": 0.0,
        "claim_hitl": 1.0,
        "reason_codes": [
            "UB_TAX_FIELD_NOT_OBSERVABLE_IN_GOLDEN_PACK",
            "NO_NEW_INDEPENDENT_EVIDENCE_AVAILABLE",
            "DO_NOT_FABRICATE_EVIDENCE",
        ],
    }

    write_json(output / "baseline.json", baseline)
    write_jsonl(output / "claim_blocker_matrix.jsonl", matrix)
    write_json(
        output / "claim_blocker_pareto.json", {"rows": pareto, "classification_coverage": 1.0}
    )
    write_json(
        output / "claim_unlock_waterfall.json",
        {"current_claim_stp": 0.0, "steps": waterfall, "production_decisions_changed": False},
    )
    write_json(output / "perfect_but_not_stp.json", perfect)
    write_json(output / "federal_tax_no_metrics.json", federal)
    write_json(output / "member_id_blockers.json", member)
    write_json(output / "npi_blockers.json", npi)
    write_json(output / "total_charge_blockers.json", total)
    write_json(output / "financial_reconciliation.json", financial)
    write_json(output / "reference_opportunity.json", reference)
    write_json(output / "profile_a.json", base_profile)
    write_json(output / "profile_b.json", profile_b)
    write_json(output / "profile_c.json", profile_c)
    write_jsonl(output / "field_decisions.jsonl", fields)
    write_jsonl(output / "claim_decisions.jsonl", claims)
    write_json(output / "cost.json", cost)
    write_json(output / "decision.json", decision)

    top = pareto[:5]
    top_lines = "\n".join(
        f"{i}. {r['family']}.{r['field']}: {r['claims_blocked']} claims; {r['single_blocker_claims']} single-blocker; unlock value {r['claim_unlock_value']:.2f}."
        for i, r in enumerate(top, 1)
    )
    waterfall_lines = "\n".join(
        f"{r['step']}. Resolve `{r['resolved_blocker']['family']}.{r['resolved_blocker']['field']}` -> {r['cumulative_claims_unlocked']} claims ({r['counterfactual_claim_stp']:.0%} STP)."
        for r in waterfall
    )
    reports = {
        "CDP_PHASE8_5_CLAIM_BLOCKER_PARETO.md": f"# Phase 8.5 Claim Blocker Pareto\n\n{top_lines}\n\nAll {len(blocker_rows)} blocker instances use one of the eight governed classifications (100% classified).\n",
        "CDP_PHASE8_5_CLAIM_UNLOCK_WATERFALL.md": f"# Phase 8.5 Claim Unlock Waterfall\n\nCurrent production-equivalent STP: **0%**. This is truth-assisted counterfactual analysis only; no production decision was changed.\n\n{waterfall_lines}\n",
        "CDP_PHASE8_5_PERFECT_BUT_NOT_STP.md": f"# Phase 8.5 Perfect but Not STP\n\nPerfect claims currently blocked: **{perfect['perfect_claims_currently_blocked']}**. Unlocked: **0**. Remaining blocked: **{perfect['perfect_claims_remaining_blocked']}**. Perfect extraction is not evidence sufficiency.\n",
        "CDP_PHASE8_5_UB_FEDERAL_TAX_NO.md": f"# Phase 8.5 UB Federal Tax Number\n\nThe canonical dynamic field capability is implemented, but the golden pack has **{federal['golden_truth_rows']} truth rows**, **{federal['observable_labels']} observable labels**, and no legitimate values. Accuracy and safe coverage are therefore not measurable. No OCR was rerun and no value was fabricated. Actual claims unlocked: **0**; counterfactual ceiling: **50**.\n",
        "CDP_PHASE8_5_REFERENCE_OPPORTUNITY.md": f"# Phase 8.5 Reference Opportunity\n\nReference state: **DISABLED**. Authorized sources: **0**. Claims resolvable by E5 alone: **{reference['claims_blocked_only_by_missing_e5']}**. Claims with an optional E5 route: **{reference['claims_where_e5_is_optional']}**. Claims where E5 alone remains insufficient: **{reference['claims_where_e5_would_still_be_insufficient']}**. Fabricated reference records: **0**.\n",
        "CDP_PHASE8_5_COST_IMPACT.md": f"# Phase 8.5 Cost Impact\n\nField review: **${review_cost:.6f}/page**. Claim-review overhead: **${claim_overhead:.6f}/page**. HITL total: **${hitl_cost:.6f}/page**. Fully loaded: **${full_cost:.6f}/page**. Cloud common path: **$0**. STP is zero, so cost/STP claim is undefined and review cost avoided is $0.\n",
        "CDP_PHASE8_5_FINAL_REPORT.md": f"# CDP Phase 8.5 Final Report\n\n## Outcome\n\n**NO PROMOTION; SAFE HITL remains active.** Phase 8.4 was reproduced exactly. Safety remains 100% accepted precision, zero false accepts, and zero critical false accepts. Claim STP remains 0% because no legitimate new evidence exists in this corpus.\n\n## Frozen accuracy\n\n- CMS: {extraction['by_family']['CMS1500']['final_field_accuracy']:.2%}\n- UB: {extraction['by_family']['UB04']['final_field_accuracy']:.2%}\n- Critical: {extraction['critical_field_accuracy']:.2%}\n- Safe field coverage: {frozen['safe_field_coverage']:.2%}\n- Field HITL: {frozen['field_hitl']:.2%}\n- Claim HITL/STP: {frozen['claim_hitl']:.0%}/{frozen['claim_stp']:.0%}\n\n## Dominant blockers\n\n{top_lines}\n\n## Decision rationale\n\nThe UB tax-number capability is production-shaped but unbenchmarked because the engineering pack omits the field. CMS member ID, NPI, and total blockers lack the independent evidence required by policy. Reducing blockers or manufacturing E5/E6 would violate the safety contract.\n",
    }
    for name, content in reports.items():
        (DOCS / name).write_text(content, "utf-8")
    return {
        "baseline": baseline,
        "top_blockers": top,
        "federal_tax_no": federal,
        "cost": cost,
        "decision": decision,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
