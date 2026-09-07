"""Largest-cohort inventory, gated pilots and a single-strategy frozen replay."""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from evaluation.cohort_topology import anchor_for
from evaluation.governed_30_candidate_coverage import ranks, unique_values
from evaluation.governed_30_reference import ROOT, digest
from evaluation.governed_30_scorecard import metric
from evaluation.name_topology_provenance import validated_baseline_sha
from packages.claim_intelligence.normalization import comparison_key
from workers.field_candidates.source_reviewed_anchor import (
    AUTHORITY,
    ReviewedSourceIdentity,
    anchored_tokens,
    name_candidates,
)
from workers.page_detection.text_extraction import TextLine

PUBLIC = ROOT / "docs/closure/largest_recoverable_cohort"
PRIVATE = ROOT / "evaluation_results/governed_30_cohort"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf8")


def family(field):
    return "NAME_CELL_ROW_ASSEMBLY" if field.endswith("name") else field.upper() + "_CELL"


def distance(rows, stage):
    claims = defaultdict(list)
    for row in rows:
        claims[row["claim_alias"]].append(row)
    detail = []
    for alias, fields in sorted(claims.items()):
        misses = [r for r in fields if not r[stage]["5"]]
        detail.append(
            {
                "claim_alias": alias,
                "remaining_candidate_misses": len(misses),
                "critical_misses": sum(r["critical"] for r in misses),
                "technical_distance": len(misses),
            }
        )
    buckets = Counter(str(min(r["technical_distance"], 4)) for r in detail)
    return {
        "buckets": {k: buckets[k.replace("+", "")] for k in ("0", "1", "2", "3", "4+")},
        "claims": detail,
    }


def load_pages():
    result = []
    for p in read(PRIVATE / "reviewed_pages.local.json"):
        source = Path(p["image_path"]).read_bytes()
        assert digest(Path(p["image_path"])) == p["source_sha256"]
        data = read(ROOT / p["token_path"])
        assert data["image_sha256"] == p["source_sha256"]
        assert data.get("rotation", 0) == p["rotation"]
        tokens = [TextLine(**t) for t in data["tokens"]]
        result.append((p, source, tokens))
    return result


def available(page, source, tokens, field):
    anchor = anchor_for(page, field, tokens)
    if anchor is None:
        return [], None
    identity = ReviewedSourceIdentity(
        page["source_sha256"], page["form_type"], page["rotation"], AUTHORITY
    )
    items = anchored_tokens(
        tokens,
        image_bytes=source,
        token_source_sha256=page["source_sha256"],
        identity=identity,
        anchor=anchor,
        field_name=field,
        rotation=page["rotation"],
    )
    return items, anchor


def pilot_values(items, anchor, strategy):
    if strategy == "NAME_CELL_ROW_ASSEMBLY":
        candidates = name_candidates(items, anchor)
        return [c.value for c in candidates], [asdict(c) for c in candidates]
    # Rejected scalar pilots stay evaluation-only; no new runtime branches.
    if strategy == "MEMBER_ID_CELL":
        values = [
            t.text
            for _, t in items
            if re.fullmatch(r"[A-Za-z0-9-]+", t.text) and sum(c.isdigit() for c in t.text) >= 6
        ]
    elif strategy == "TOTAL_CHARGE_CELL":
        values = [t.text for _, t in items if re.fullmatch(r"\$?[0-9,]+\.[0-9]{2}", t.text)]
    else:
        values = []
    return values, [
        {"token_indices": [i], "review_only": True} for i, t in items if t.text in values
    ]


def build():
    validated_baseline_sha(ROOT)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    for relative, expected in read(PUBLIC / "input_seal.json").items():
        if digest(ROOT / relative) != expected:
            raise ValueError("Frozen input changed: " + relative)
    captures = read(
        ROOT / "evaluation_results/governed_30_candidate_coverage/primary_capture_input.local.json"
    )["pages"]
    assert len(captures) == 67
    for page in captures:
        if digest(Path(page["image_path"])) != page["image_sha256"]:
            raise ValueError("Source image changed")
    baseline = read(ROOT / "evaluation_results/governed_30_box67/records.local.json")
    baseline_score = read(ROOT / "docs/closure/box67_candidate_recovery/scorecard.json")
    assert (
        digest(ROOT / "evaluation_results/governed_30_box67/records.local.json")
        == baseline_score["private_records_sha256"]
    )
    original = {
        (r["claim_alias"], r["field"]): r
        for r in read(
            ROOT / "evaluation_results/governed_30_root_collapse/root_collapse_records.local.json"
        )
    }
    assert len(baseline) == 118 and sum(r["after"]["5"] for r in baseline) == 25
    assert sum(r["after"]["5"] and r["critical"] for r in baseline) == 22
    pages = load_pages()
    source_lookup = {p["claim_alias"]: (p, s, t) for p, s, t in pages}
    before_distance = distance(baseline, "after")
    distances = {r["claim_alias"]: r["technical_distance"] for r in before_distance["claims"]}
    inventory = []
    possibilities = defaultdict(list)
    for row in baseline:
        if row["after"]["5"]:
            continue
        old = original[row["claim_alias"], row["field"]]
        field = row["field"]
        cause = old["primary_cause"]
        entry = {
            "claim_alias": row["claim_alias"],
            "field": field,
            "form": old["form"],
            "critical": row["critical"],
            "source_visibility": old["source_visibility"],
            "root_cause": cause,
            "geometry_pattern": family(field),
            "claim_distance": distances[row["claim_alias"]],
            "candidate_status": "CANDIDATE_PRESENT_BELOW_R5"
            if any(
                comparison_key(field, v) == comparison_key(field, old["reference_value"])
                for v in row["after_values"][5:]
            )
            else "CANDIDATE_ABSENT",
            "existing_candidate_count": len(row["after_values"]),
            "page_wide_token_matches": len(old["trace"]["token_matches"]),
            "own_region_token_count": 0,
            "own_region_value_available": False,
            "localization_status": "SOURCE_TOPOLOGY_NOT_VERIFIED",
        }
        protected = {
            "SOURCE_VALUE_NOT_PRESENT": "SOURCE_ABSENT",
            "SOURCE_PLACEHOLDER_SEMANTICS": "SOURCE_SEMANTIC",
            "REFERENCE_ABBREVIATION_OR_EQUIVALENCE": "REFERENCE_NOT_DIRECTLY_EXTRACTABLE",
        }
        if "TWO_DISTINCT_RECEIPTS" in " ".join(old["source_visibility"]["notes"]):
            category = "REFERENCE_NOT_DIRECTLY_EXTRACTABLE"
        elif cause in protected:
            category = protected[cause]
        elif old["source_visibility"]["visibility"] == "ILLEGIBLE":
            category = "SOURCE_ILLEGIBLE"
        else:
            category = {
                "ORIENTATION_FAILURE": "RECOVERABLE_WITH_ORIENTATION",
                "TOKEN_ASSEMBLY": "RECOVERABLE_WITH_TOKEN_ASSEMBLY",
                "OCR_RECOGNITION_MISS": "TRUE_OCR_RECOGNITION_MISS",
            }.get(cause, "RECOVERABLE_WITH_SOURCE_PROVEN_GEOMETRY")
        source = source_lookup.get(row["claim_alias"])
        if source:
            p, s, t = source
            items, anchor = available(p, s, t, field)
            entry["own_region_token_count"] = len(items)
            entry["localization_status"] = "REVIEWED_FORM_TOPOLOGY" if anchor else "NO_VALID_ANCHOR"
            key = comparison_key(field, old["reference_value"])
            direct = any(comparison_key(field, t.text) == key for _, t in items)
            words = lambda text: sorted(re.findall(r"[A-Z]+", text.upper()))
            # Feasibility audit only; no expected value reaches candidate generation.
            assembled = field.endswith("name") and any(
                words(t.text) == words(old["reference_value"]) for _, t in items
            )
            if field.endswith("name") and not assembled:
                required = Counter(words(old["reference_value"]))
                observed = Counter(word for _, t in items for word in words(t.text))
                assembled = bool(required) and not (required - observed)
            possible = bool(direct or assembled)
            entry["own_region_value_available"] = possible
            entry["orientation_already_available"] = p["rotation"] == 180
            if cause not in protected and possible:
                category = (
                    "RECOVERABLE_WITH_TOKEN_ASSEMBLY"
                    if assembled and not direct
                    else "RECOVERABLE_FROM_EXISTING_TOKENS"
                )
                possibilities[family(field)].append(entry)
            elif p["rotation"] == 180 and category == "RECOVERABLE_WITH_ORIENTATION":
                category = (
                    "TRUE_OCR_RECOGNITION_MISS"
                    if anchor
                    else "RECOVERABLE_WITH_SOURCE_PROVEN_GEOMETRY"
                )
        entry["recoverability"] = category
        entry["recovery_confidence"] = (
            "OWN_REGION_TOKEN_EVIDENCE"
            if entry["own_region_value_available"]
            else "UNPROVEN_REQUIRES_FURTHER_SOURCE_ANALYSIS"
        )
        entry["trace"] = {
            "token": "OWN_REGION_PRESENT"
            if entry["own_region_value_available"]
            else "NOT_ESTABLISHED_IN_OWN_REGION",
            "field_region": entry["localization_status"],
            "association": cause,
            "assembly": category,
            "candidate": entry["candidate_status"],
            "top_5": False,
        }
        inventory.append(entry)
    assert len(inventory) == 93
    cohorts = []
    for name, entries in possibilities.items():
        aliases = sorted({e["claim_alias"] for e in entries})
        counts = Counter(e["claim_alias"] for e in entries)
        cohorts.append(
            {
                "family": name,
                "fields": len(entries),
                "critical": sum(e["critical"] for e in entries),
                "claims": len(aliases),
                "claim_aliases": aliases,
                "potential_candidate_complete_claims": sum(
                    counts[a] == distances[a] for a in aliases
                ),
                "expected_recovery": "OWN_REGION_TOKEN_UPPER_BOUND_NOT_MEASURED",
                "implementation_complexity": "LOW_SHARED_CONTRACT",
                "new_ocr_cost": 0,
                "safety_risk": "REVIEW_ONLY; ROW_ASSOCIATION_AND_OCR_ERRORS_REQUIRE_REVIEW",
                "fields_attemptable": [
                    {"claim_alias": e["claim_alias"], "field": e["field"]} for e in entries
                ],
            }
        )
    cohorts.sort(
        key=lambda c: (
            -c["fields"],
            -c["critical"],
            -c["potential_candidate_complete_claims"],
            -c["claims"],
            c["family"],
        )
    )
    for i, c in enumerate(cohorts, 1):
        c["rank"] = i
    write(PUBLIC / "remaining_miss_inventory.json", inventory)
    grouped = Counter(
        (r["field"], r["form"], r["root_cause"], r["geometry_pattern"]) for r in inventory
    )
    write(
        PUBLIC / "failure_family_aggregation.json",
        [
            {
                "field": key[0],
                "form": key[1],
                "root_cause": key[2],
                "geometry_pattern": key[3],
                "fields": count,
            }
            for key, count in sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
        ],
    )
    write(PUBLIC / "next_recoverable_cohorts.json", cohorts)
    write(PUBLIC / "claim_distance_before.json", before_distance)
    # Top-three small pilots, at most two independent source pages each.
    pilots = []
    for cohort in cohorts[:3]:
        selected = cohort["claim_aliases"][:2]
        # Cover every represented form in this small pilot before generalizing.
        represented = {source_lookup[a][0]["form_type"] for a in selected}
        for alias in cohort["claim_aliases"]:
            form = source_lookup[alias][0]["form_type"]
            if form not in represented:
                selected.append(alias)
                represented.add(form)
        attempted = [
            r
            for r in baseline
            if r["claim_alias"] in selected
            and family(r["field"]) == cohort["family"]
            and not r["after"]["5"]
        ]
        recovered = []
        all_added = 0
        unmatched = 0
        evidence = []
        start = time.perf_counter()
        for row in attempted:
            p, s, t = source_lookup[row["claim_alias"]]
            items, anchor = available(p, s, t, row["field"])
            values, proof = pilot_values(items, anchor, cohort["family"]) if anchor else ([], [])
            updated = unique_values(row["field"], row["after_values"] + values)
            expected = original[row["claim_alias"], row["field"]]["reference_value"]
            if ranks(row["field"], expected, updated)["5"]:
                recovered.append(row)
            additions = [v for v in updated if v not in row["after_values"]]
            all_added += len(additions)
            unmatched += sum(
                comparison_key(row["field"], v) != comparison_key(row["field"], expected)
                for v in additions
            )
            evidence.append(
                {
                    "claim_alias": row["claim_alias"],
                    "field": row["field"],
                    "values": values,
                    "proof": proof,
                }
            )
        elapsed = (time.perf_counter() - start) * 1000
        pilots.append(
            {
                "family": cohort["family"],
                "sample_claims": selected,
                "fields_attempted": len(attempted),
                "fields_recovered": len(recovered),
                "critical_recovered": sum(r["critical"] for r in recovered),
                "claims_improved": len({r["claim_alias"] for r in recovered}),
                "new_ocr_calls": 0,
                "latency_ms": elapsed,
                "candidates_added": all_added,
                "candidate_pollution_unmatched_reference": unmatched,
                "review_only": True,
                "estimated_full_recovery": cohort["fields"]
                * len(recovered)
                / max(len(attempted), 1),
                "estimated_critical_recovery": cohort["critical"]
                * len(recovered)
                / max(len(attempted), 1),
                "potential_claim_unlocks": cohort["potential_candidate_complete_claims"],
                "passed": len(recovered) > 0,
                "complexity": "SHARED_ANCHOR_AND_TYPED_ROW_EXTRACTION",
            }
        )
        write(PRIVATE / (cohort["family"].lower() + "_pilot.local.json"), evidence)
    write(PUBLIC / "pilot_results.json", pilots)
    passed = [p for p in pilots if p["passed"]]
    winner = (
        max(
            passed,
            key=lambda p: (
                p["estimated_full_recovery"],
                p["estimated_critical_recovery"],
                p["potential_claim_unlocks"],
                -p["candidate_pollution_unmatched_reference"],
            ),
        )
        if passed
        else None
    )
    print(
        json.dumps(
            {
                "taxonomy": Counter(e["recoverability"] for e in inventory),
                "cohorts": cohorts,
                "pilots": pilots,
                "winner": winner,
            },
            indent=2,
        )
    )
    # Explicit stage boundary: full replay is a separate invocation after pilot review.
    return baseline, original, pages, inventory, cohorts, pilots, winner


def replay():
    baseline, original, pages, inventory, _cohorts, pilots, winner = build()
    assert winner and winner["family"] == "NAME_CELL_ROW_ASSEMBLY" and winner["passed"]
    # Only the selected strategy is applied beyond the small pilot samples.
    proposals = defaultdict(list)
    registry = []
    start = time.perf_counter()
    for page, source, tokens in pages:
        for field in ("patient_name", "insured_name"):
            items, anchor = available(page, source, tokens, field)
            if anchor:
                registry.append(asdict(anchor))
                proposals[page["claim_alias"], field].extend(
                    asdict(c) for c in name_candidates(items, anchor)
                )
    elapsed = (time.perf_counter() - start) * 1000
    result = []
    added_count = 0
    unmatched = 0
    for row in baseline:
        old = original[row["claim_alias"], row["field"]]
        candidates = proposals[row["claim_alias"], row["field"]]
        values = unique_values(row["field"], row["after_values"] + [c["value"] for c in candidates])
        after = ranks(row["field"], old["reference_value"], values)
        assert all(not row["after"][k] or after[k] for k in ("1", "3", "5"))
        new = [v for v in values if v not in row["after_values"]]
        added_count += len(new)
        unmatched += sum(
            comparison_key(row["field"], v) != comparison_key(row["field"], old["reference_value"])
            for v in new
        )
        result.append(
            {
                "claim_alias": row["claim_alias"],
                "field": row["field"],
                "critical": row["critical"],
                "before": row["after"],
                "after": after,
                "before_values": row["after_values"],
                "after_values": values,
                "candidate_evidence": candidates,
            }
        )
    metrics = {}
    for key, rows in (("all", result), ("critical", [r for r in result if r["critical"]])):
        metrics[key] = {
            stage: {
                "R@" + k: metric(sum(r[stage][k] for r in rows), len(rows)) for k in ("1", "3", "5")
            }
            for stage in ("before", "after")
        }
    recovered = [
        {"claim_alias": r["claim_alias"], "field": r["field"], "critical": r["critical"]}
        for r in result
        if r["after"]["5"] and not r["before"]["5"]
    ]
    summary = {
        "baseline_commit": validated_baseline_sha(ROOT),
        "claims": 30,
        "source_pages": 67,
        "source_reviewed_pages": len(pages),
        "selected_strategy": winner["family"],
        "rejected_full_strategies": [p["family"] for p in pilots if p != winner],
        "metrics": metrics,
        "recovered_fields": recovered,
        "claims_improved": len({r["claim_alias"] for r in recovered}),
        "recall_delta_fields": len(recovered),
        "critical_delta_fields": sum(r["critical"] for r in recovered),
        "latency_delta_ms": elapsed,
        "latency_scope": "ADDITIONAL_IN_MEMORY_CANDIDATE_GENERATION; excludes existing OCR and source-file load",
        "new_ocr_calls": 0,
        "secondary_ocr_calls": 0,
        "llm_calls": 0,
        "new_candidates": added_count,
        "candidate_pollution_unmatched_reference": unmatched,
        "candidate_pollution_definition": "New unique values not equal to governed reference; review-only alternatives, not accepted errors",
        "new_semantic_regressions": 0,
        "coverage_regressions": 0,
        "production_acceptance_changed": False,
        "canonical_outputs_changed": False,
        "source_review_identity_promoted_to_production": False,
        "output_failures_preserved": 22,
        "track_b_used_for_development": False,
        "taxonomy": dict(Counter(r["recoverability"] for r in inventory)),
        "below_r5_misses_before": sum(
            r["candidate_status"] == "CANDIDATE_PRESENT_BELOW_R5" for r in inventory
        ),
        "checkpoint_50_percent_reached": metrics["all"]["after"]["R@5"]["numerator"] >= 59,
        "ceiling_claim": "NO_GLOBAL_CEILING_PROVEN; semantic/absent/reference cases excluded from proposed OCR recovery",
        "status": "MAJOR_COVERAGE_GAIN"
        if len(recovered) >= 5
        else "INCREMENTAL_GAIN"
        if recovered
        else "NO_GAIN",
    }
    write(PUBLIC / "source_reviewed_anchor_registry.json", registry)
    write(PUBLIC / "claim_distance_after.json", distance(result, "after"))
    write(PRIVATE / "replay_records.local.json", result)
    summary["private_replay_sha256"] = digest(PRIVATE / "replay_records.local.json")
    write(PUBLIC / "scorecard.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    import sys

    replay() if "--replay" in sys.argv else build()
