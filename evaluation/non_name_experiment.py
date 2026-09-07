"""Rank non-name failures, pilot on DEV, freeze one strategy, then validate."""

from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from evaluation.governed_30_candidate_coverage import ranks, unique_values
from evaluation.non_name_inputs import (
    DOC,
    PRIVATE,
    aliases,
    digest,
    pages,
    read,
    refs,
    verify,
    write,
)
from evaluation.non_name_pilots import discover
from evaluation.non_name_strategy import MemberIdTopology
from packages.claim_intelligence.normalization import comparison_key

ROOT = Path.cwd()
BASE = Path("evaluation_results/governed_30_cohort/replay_records.local.json")


def ambiguity(rows):
    out = {}
    for stage in ("before", "after"):
        counts = [len(r[stage + "_values"]) for r in rows]
        classes = [len({comparison_key(r["field"], v) for v in r[stage + "_values"]}) for r in rows]
        out[stage] = {
            "mean": statistics.mean(counts) if counts else 0,
            "p95": sorted(counts)[math.ceil(len(counts) * 0.95) - 1] if counts else 0,
            "fields_over_5": sum(c > 5 for c in counts),
            "equivalent_duplicates": sum(c - n for c, n in zip(counts, classes)),
            "non_equivalent_alternatives": sum(max(0, n - 1) for n in classes),
        }
    out["new_non_equivalent_alternatives"] = (
        out["after"]["non_equivalent_alternatives"] - out["before"]["non_equivalent_alternatives"]
    )
    out["new_equivalent_duplicates"] = (
        out["after"]["equivalent_duplicates"] - out["before"]["equivalent_duplicates"]
    )
    out["new_ambiguity_blockers"] = sum(
        len({comparison_key(r["field"], v) for v in r["before_values"]}) <= 1
        and len({comparison_key(r["field"], v) for v in r["after_values"]}) > 1
        for r in rows
    )
    out["maximum_added_per_field"] = max(
        (len(r["after_values"]) - len(r["before_values"]) for r in rows), default=0
    )
    return out


def score_row(row, values, expected):
    before = row["after_values"]
    after = unique_values(row["field"], before + values)
    key = comparison_key(row["field"], expected)
    rank = lambda vs: next(
        (i for i, v in enumerate(vs, 1) if comparison_key(row["field"], v) == key), None
    )
    return {
        "claim_alias": row["claim_alias"],
        "field": row["field"],
        "critical": row["critical"],
        "before_values": before,
        "after_values": after,
        "before": ranks(row["field"], expected, before),
        "after": ranks(row["field"], expected, after),
        "correct_rank_before": rank(before),
        "correct_rank_after": rank(after),
    }


def metrics(rows):
    return {
        stage: {
            "R@" + k: {
                "numerator": sum(r[stage][k] for r in rows),
                "denominator": len(rows),
                "percentage": 100 * sum(r[stage][k] for r in rows) / len(rows) if rows else None,
            }
            for k in ("1", "3", "5")
        }
        for stage in ("before", "after")
    }


def pilot():
    verify(ROOT)
    inventory = read(ROOT / DOC / "non_name_miss_inventory.json")
    groups = defaultdict(list)
    for row in inventory:
        groups[row["field"]].append(row)
    cohort = []
    for field, rows in groups.items():
        if field == "member_id":
            possible = [r for r in rows if r["own_region_value_available"]]
        elif field == "patient_dob":
            possible = [r for r in rows if r["root_cause"] == "TOKEN_ASSEMBLY"]
        else:
            possible = []  # Explicitly exclude rejected charge-region coincidences and wrong admitting diagnoses.
        claimset = {r["claim_alias"] for r in possible}
        cohort.append(
            {
                "field": field,
                "remaining_misses": len(rows),
                "recoverable_fields": len(possible),
                "critical": sum(r["critical"] for r in possible),
                "claims": len(claimset),
                "potential_claim_unlocks": sum(r["would_single_field_unlock"] for r in possible),
                "existing_token_evidence": len(possible),
                "complexity": "LOW_NORMALIZED_FIELD_CELL"
                if possible
                else "UNPROVEN_SEMANTICS_OR_RECOGNITION",
                "latency": "NO_NEW_OCR_FOR_PILOT",
                "safety_risk": "REVIEW_ONLY; STRICT_FIELD_REGION_AND_LITERAL_CHARACTERS",
                "strategy": "NORMALIZED_ID_CELL"
                if field == "member_id"
                else "OBSERVED_EIGHT_DIGIT_DATE"
                if field == "patient_dob"
                else "EXPLICIT_MONEY_IN_CLAIM_TOTAL_CELL"
                if field == "total_charge"
                else "ABSTAIN_ON_WRONG_BOX67_OCR",
                "claim_aliases": sorted(claimset),
            }
        )
    cohort.sort(
        key=lambda c: (
            -c["recoverable_fields"],
            -c["critical"],
            -c["claims"],
            -c["potential_claim_unlocks"],
            -c["remaining_misses"],
        )
    )
    cohort.append(
        {
            "field": "service_date",
            "remaining_misses": 0,
            "recoverable_fields": 0,
            "critical": 0,
            "claims": 0,
            "status": "NO_COMPARABLE_SLOT_UNDER_FROZEN_MAPPING; NOT_A_RECOVERY_OPPORTUNITY",
        }
    )
    for i, c in enumerate(cohort, 1):
        c["rank"] = i
    write(ROOT / DOC / "next_non_name_cohorts.json", cohort)
    baseline = read(ROOT / BASE)
    expected = refs(ROOT, "dev")
    allowed = aliases(ROOT, "dev")
    source = {p["claim_alias"]: (p, t) for p, t in pages(ROOT, "dev")}
    pilots = []
    for c in cohort[:3]:
        field = c["field"]
        selected = [
            r
            for r in baseline
            if r["claim_alias"] in allowed and r["field"] == field and not r["after"]["5"]
        ]
        if c["claim_aliases"]:
            selected = [r for r in selected if r["claim_alias"] in c["claim_aliases"]]
        if field == "total_charge":
            selected = [
                r
                for r in selected
                if source.get(r["claim_alias"], ({}, []))[0].get("form_type") == "CMS1500"
            ]
        selected = selected[:3]
        records = []
        start = time.perf_counter()
        evidence = []
        for row in selected:
            p, t = source[row["claim_alias"]]
            candidates = discover(field, p, t)
            records.append(
                score_row(
                    row, [v["value"] for v in candidates], expected[row["claim_alias"], field]
                )
            )
            evidence.append(
                {"claim_alias": row["claim_alias"], "field": field, "candidates": candidates}
            )
        elapsed = (time.perf_counter() - start) * 1000
        gained = {
            "R@" + k: sum(r["after"][k] and not r["before"][k] for r in records)
            for k in ("1", "3", "5")
        }
        rate = gained["R@5"] / len(records) if records else 0
        result = {
            "field": field,
            "attempted": len(records),
            "claim_aliases": [r["claim_alias"] for r in records],
            "recovered": gained,
            "critical_recovered": sum(
                r["critical"] and r["after"]["5"] and not r["before"]["5"] for r in records
            ),
            "claims_improved": len(
                {r["claim_alias"] for r in records if r["after"]["5"] and not r["before"]["5"]}
            ),
            "new_candidates": sum(
                len(r["after_values"]) - len(r["before_values"]) for r in records
            ),
            "ambiguity": ambiguity(records),
            "new_ocr_calls": 0,
            "latency_ms": elapsed,
            "estimated_full_recovery": c["recoverable_fields"] * rate,
            "potential_claim_unlocks": c["potential_claim_unlocks"],
            "safety": "REVIEW_ONLY_NO_REPAIR_NO_PRODUCTION_CHANGES",
        }
        pilots.append(result)
        write(ROOT / PRIVATE / (field + "_pilot.local.json"), evidence)
    write(ROOT / DOC / "pilot_results.json", pilots)
    passing = [p for p in pilots if p["recovered"]["R@5"] > 0]
    winner = (
        max(
            passing,
            key=lambda p: (
                p["estimated_full_recovery"],
                p["critical_recovered"],
                p["potential_claim_unlocks"],
                -p["ambiguity"]["new_non_equivalent_alternatives"],
            ),
        )
        if passing
        else None
    )
    print(json.dumps({"cohorts": cohort, "pilots": pilots, "winner": winner}, indent=2))
    return winner


def freeze():
    winner = pilot()
    if not winner or winner["field"] != "member_id":
        raise ValueError("NO_SUPPORTED_WINNER")
    code = [
        "evaluation/non_name_strategy.py",
        "evaluation/non_name_inputs.py",
        "evaluation/non_name_pilots.py",
    ]
    value = {
        "selected_field": "member_id",
        "status": "ENGINEERING_ONLY",
        "exposure": "NO_CLEAN_VALIDATION_AVAILABLE",
        "topology": asdict(MemberIdTopology()),
        "filters": "OBSERVED_ALPHANUMERIC_WITH_DIGITS; PRESERVE_LEADING_ZEROS_AND_PUNCTUATION",
        "assembly": "ONLY_VISIBLY_CONTIGUOUS_FRAGMENTS; NEVER_INSERT_OR_REPAIR_CHARACTERS",
        "ranking": "APPEND_ONLY; MAX_TWO_SOURCE_ORDER_PROPOSALS",
        "dev_manifest_sha256": digest(ROOT / DOC / "dev_manifest.json"),
        "validation_manifest_sha256": digest(ROOT / DOC / "validation_manifest.json"),
        "implementation_hashes": {p: digest(ROOT / p) for p in code},
        "validation_gate": {
            "minimum_recovered_fields": 1,
            "maximum_mean_candidate_delta": 1,
            "maximum_additions_per_field": 2,
            "maximum_incremental_generation_ms": 1000,
            "no_loss": True,
            "new_ocr_calls": 0,
        },
    }
    path = ROOT / DOC / "non_name_strategy_freeze.json"
    if path.exists() and read(path) != value:
        raise ValueError("FROZEN_STRATEGY_CHANGE_REFUSED")
    if not path.exists():
        write(path, value)
    return value


if __name__ == "__main__":
    import sys

    freeze() if "--freeze" in sys.argv else pilot()
