"""Frozen UB date validation and gated full-cohort engineering replay."""

import time
from collections import defaultdict
from pathlib import Path

from evaluation.non_name_experiment import ambiguity, metrics, score_row
from evaluation.non_name_inputs import digest, pages, read, refs, write
from evaluation.non_name_replay import distance, frozen
from evaluation.ub_birthdate_rule import BirthdateTopology, discover

ROOT = Path.cwd()
DOC = ROOT / "docs/closure/ub_birthdate_recovery"
PRIVATE = ROOT / "evaluation_results/ub_birthdate_recovery"


def verify():
    frozen()
    seal = read(DOC / "birthdate_strategy_freeze.json")
    for name, value in (seal["input_hashes"] | seal["implementation_hashes"]).items():
        if digest(ROOT / name) != value:
            raise ValueError("FROZEN_BIRTHDATE_INPUT_CHANGED")
    return seal


def replay(full=False):
    seal = verify()
    if full:
        gate = read(DOC / "validation_gate.json")
        if not gate["engineering_gate_passed"] or gate["strategy_freeze_sha256"] != digest(
            DOC / "birthdate_strategy_freeze.json"
        ):
            raise ValueError("VALIDATION_REQUIRED_FOR_THIS_FROZEN_STRATEGY")
    baseline = read(ROOT / "evaluation_results/non_name_cohort/full_replay.local.json")
    source = list(pages(ROOT, "full" if full else "dev"))
    if not full:
        allowed = {p["claim_alias"] for p, t in source if p["form_type"] == "UB"}
        baseline = [r for r in baseline if r["claim_alias"] in allowed]
        source = [(p, t) for p, t in source if p["claim_alias"] in allowed]
    else:
        capture = read(
            ROOT
            / "evaluation_results/governed_30_candidate_coverage/primary_capture_input.local.json"
        )["pages"]
        assert len(capture) == 67
        for p in capture:
            if digest(p["image_path"]) != p["image_sha256"]:
                raise ValueError("SOURCE_CHANGED")
    expected = refs(ROOT, "dev") | (refs(ROOT, "validation") if full else {})
    rule = BirthdateTopology(
        **{**seal["topology"], "normalized_region": tuple(seal["topology"]["normalized_region"])}
    )
    proposed = defaultdict(list)
    elapsed = 0.0
    for page, tokens in source:
        start = time.perf_counter()
        candidates = discover(
            tokens,
            form_type=page["form_type"],
            field_name="patient_dob",
            width=page["width"],
            height=page["height"],
            topology=rule,
        )
        elapsed += (time.perf_counter() - start) * 1000
        proposed[page["claim_alias"]].extend(
            {**c, "source_sha256": page["source_sha256"], "page_number": page["page_number"]}
            for c in candidates
        )
    result = []
    for row in baseline:
        proof = proposed[row["claim_alias"]] if row["field"] == "patient_dob" else []
        scored = score_row(
            row, [c["value"] for c in proof], expected[row["claim_alias"], row["field"]]
        )
        scored["evidence"] = proof
        assert all(not row["after"][k] or scored["after"][k] for k in ("1", "3", "5"))
        if row["field"] != "patient_dob":
            assert scored["after_values"] == row["after_values"]
        result.append(scored)
    dates = [r for r in result if r["field"] == "patient_dob"]
    recovered = [
        {"claim_alias": r["claim_alias"], "field": r["field"], "critical": r["critical"]}
        for r in dates
        if r["after"]["5"] and not r["before"]["5"]
    ]
    report = {
        "scope": "FULL_FROZEN_30" if full else "SIX_EXPOSED_UB_CLAIMS_ENGINEERING_VALIDATION",
        "claims": len({r["claim_alias"] for r in result}),
        "metrics": metrics(result),
        "critical_metrics": metrics([r for r in result if r["critical"]]),
        "date_metrics": metrics(dates),
        "recovered_fields": recovered,
        "date_ambiguity": ambiguity(dates),
        "all_field_ambiguity": ambiguity(result),
        "new_candidates": sum(len(r["after_values"]) - len(r["before_values"]) for r in dates),
        "claims_improved": len({r["claim_alias"] for r in recovered}),
        "claim_distance": {
            "before": distance(result, "before"),
            "after": distance(result, "after"),
        },
        "new_ocr_calls": 0,
        "secondary_ocr_calls": 0,
        "llm_calls": 0,
        "latency_delta_ms": elapsed,
        "latency_scope": "IN_MEMORY_GENERATION_ONLY",
        "regressions": 0,
        "new_semantic_regressions": 0,
        "production_acceptance_changed": False,
        "canonical_outputs_changed": False,
        "track_b_accessed": False,
        "output_failures": 22,
        "safe_outputs": 0,
        "generalization": "ENGINEERING_ONLY",
        "clean_validation": False,
        "exposure": "NO_CLEAN_VALIDATION_AVAILABLE",
        "strategy_freeze_sha256": digest(DOC / "birthdate_strategy_freeze.json"),
    }
    name = "full" if full else "validation"
    write(PRIVATE / f"{name}_replay.local.json", result)
    report["private_replay_sha256"] = digest(PRIVATE / f"{name}_replay.local.json")
    write(DOC / f"{name}_scorecard.json", report)
    write(
        DOC / f"{name}_field_audit.json",
        [
            {k: v for k, v in r.items() if k not in {"before_values", "after_values", "evidence"}}
            | {
                "candidate_count_before": len(r["before_values"]),
                "candidate_count_after": len(r["after_values"]),
            }
            for r in result
        ],
    )
    if not full:
        passed = (
            len(recovered) >= seal["engineering_gate"]["minimum_recoveries"]
            and report["date_ambiguity"]["maximum_added_per_field"] <= 1
        )
        write(
            DOC / "validation_gate.json",
            {
                "engineering_gate_passed": passed,
                "clean_validation": False,
                "generalization": "ENGINEERING_ONLY",
                "strategy_freeze_sha256": report["strategy_freeze_sha256"],
            },
        )
    print(__import__("json").dumps(report, indent=2))


if __name__ == "__main__":
    import sys

    replay("--full" in sys.argv)
