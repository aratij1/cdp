"""Post-freeze engineering validation, then gated full-30 member-ID replay."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.non_name_experiment import BASE, ambiguity, metrics, score_row
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
from evaluation.non_name_strategy import MemberIdTopology, discover_member_ids

ROOT = Path.cwd()


def frozen():
    verify(ROOT)
    freeze = read(ROOT / DOC / "non_name_strategy_freeze.json")
    for name, expected in freeze["implementation_hashes"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("FROZEN_STRATEGY_CHANGED")
    for split in ("dev", "validation"):
        if digest(ROOT / DOC / f"{split}_manifest.json") != freeze[f"{split}_manifest_sha256"]:
            raise ValueError("PACKAGE_SPLIT_CHANGED")
    return freeze


def distance(rows, stage):
    claims = defaultdict(list)
    for r in rows:
        claims[r["claim_alias"]].append(r)
    detail = [
        {
            "claim_alias": a,
            "distance": sum(not r[stage]["5"] for r in rs),
            "critical_misses": sum(r["critical"] and not r[stage]["5"] for r in rs),
        }
        for a, rs in sorted(claims.items())
    ]
    counts = Counter(str(min(r["distance"], 4)) for r in detail)
    return {
        "buckets": {k: counts[k.replace("+", "")] for k in ("0", "1", "2", "3", "4+")},
        "claims": detail,
    }


def replay(split):
    freeze = frozen()
    if split == "full":
        capture = read(
            ROOT
            / "evaluation_results/governed_30_candidate_coverage/primary_capture_input.local.json"
        )["pages"]
        assert len(capture) == 67
        for page in capture:
            if digest(page["image_path"]) != page["image_sha256"]:
                raise ValueError("FROZEN_SOURCE_IMAGE_CHANGED")
        gate = read(ROOT / DOC / "validation_gate.json")
        if not gate["engineering_gate_passed"] or gate["strategy_freeze_sha256"] != digest(
            ROOT / DOC / "non_name_strategy_freeze.json"
        ):
            raise ValueError("FULL_REPLAY_REQUIRES_PASSING_FROZEN_VALIDATION")
    expected = (
        refs(ROOT, split) if split != "full" else refs(ROOT, "dev") | refs(ROOT, "validation")
    )
    allowed = (
        aliases(ROOT, split)
        if split != "full"
        else aliases(ROOT, "dev") | aliases(ROOT, "validation")
    )
    baseline = [r for r in read(ROOT / BASE) if r["claim_alias"] in allowed]
    policy = MemberIdTopology(
        **{
            **freeze["topology"],
            "normalized_region": tuple(freeze["topology"]["normalized_region"]),
        }
    )
    proposed = defaultdict(list)
    elapsed = 0.0
    page_count = 0
    for p, t in pages(ROOT, split):
        start = time.perf_counter()
        result = discover_member_ids(
            t,
            form_type=p["form_type"],
            field_name="member_id",
            width=p["width"],
            height=p["height"],
            topology=policy,
        )
        elapsed += (time.perf_counter() - start) * 1000
        page_count += 1
        proposed[p["claim_alias"]].extend(
            {
                **c,
                "source_sha256": p["source_sha256"],
                "page_number": p["page_number"],
                "rotation": p["rotation"],
                "source_form_identity": p["form_type"],
            }
            for c in result
        )
    rows = []
    for r in baseline:
        proof = proposed[r["claim_alias"]] if r["field"] == "member_id" else []
        scored = score_row(r, [c["value"] for c in proof], expected[r["claim_alias"], r["field"]])
        scored["candidate_evidence"] = proof
        if r["field"] != "member_id":
            assert scored["after_values"] == r["after_values"]
        assert all(not scored["before"][k] or scored["after"][k] for k in ("1", "3", "5"))
        rows.append(scored)
    fields = [r for r in rows if r["field"] == "member_id"]
    gained = [r for r in fields if r["after"]["5"] and not r["before"]["5"]]
    report = {
        "split": split,
        "claims": len(allowed),
        "selected_field": "member_id",
        "metrics": metrics(rows),
        "critical_metrics": metrics([r for r in rows if r["critical"]]),
        "field_metrics": metrics(fields),
        "recovered_fields": [
            {"claim_alias": r["claim_alias"], "field": r["field"], "critical": r["critical"]}
            for r in gained
        ],
        "claims_improved": len({r["claim_alias"] for r in gained}),
        "new_candidates": sum(len(r["after_values"]) - len(r["before_values"]) for r in fields),
        "field_ambiguity": ambiguity(fields),
        "all_field_ambiguity": ambiguity(rows),
        "correct_rank_distribution": {
            stage: dict(
                Counter(
                    str(r["correct_rank_" + stage])
                    if r["correct_rank_" + stage] is not None
                    else "ABSENT"
                    for r in fields
                )
            )
            for stage in ("before", "after")
        },
        "latency_delta_ms": elapsed,
        "latency_scope": "IN_MEMORY_GENERATION_ONLY; excludes source/hash reads and existing OCR",
        "source_reviewed_pages_checked": page_count,
        "new_ocr_calls": 0,
        "secondary_ocr_calls": 0,
        "llm_calls": 0,
        "wrong_form_proposals": sum(
            c["source_form_identity"] != "CMS1500" for r in rows for c in r["candidate_evidence"]
        ),
        "coverage_regressions": 0,
        "critical_regressions": 0,
        "new_semantic_regressions": 0,
        "clean_validation": False,
        "exposure": "NO_CLEAN_VALIDATION_AVAILABLE",
        "generalization": "ENGINEERING_ONLY",
        "production_acceptance_changed": False,
        "canonical_outputs_changed": False,
        "output_failures": 22,
        "safe_outputs": 0,
        "track_b_accessed": False,
        "names_unchanged": True,
        "strategy_freeze_sha256": digest(ROOT / DOC / "non_name_strategy_freeze.json"),
    }
    write(ROOT / PRIVATE / f"{split}_replay.local.json", rows)
    report["private_replay_sha256"] = digest(ROOT / PRIVATE / f"{split}_replay.local.json")
    write(ROOT / DOC / f"{split}_scorecard.json", report)
    write(
        ROOT / DOC / f"{split}_field_audit.json",
        [
            {
                k: v
                for k, v in r.items()
                if k not in {"before_values", "after_values", "candidate_evidence"}
            }
            | {
                "candidate_count_before": len(r["before_values"]),
                "candidate_count_after": len(r["after_values"]),
            }
            for r in rows
        ],
    )
    write(
        ROOT / DOC / f"{split}_claim_distance.json",
        {"before": distance(rows, "before"), "after": distance(rows, "after")},
    )
    if split == "validation":
        criteria = freeze["validation_gate"]
        a = report["field_ambiguity"]
        checks = {
            "material_gain": len(gained) >= criteria["minimum_recovered_fields"],
            "no_loss": True,
            "no_critical_regression": True,
            "bounded_ambiguity": a["after"]["mean"] - a["before"]["mean"]
            <= criteria["maximum_mean_candidate_delta"]
            and a["maximum_added_per_field"] <= criteria["maximum_additions_per_field"],
            "acceptable_latency": elapsed <= criteria["maximum_incremental_generation_ms"],
            "no_wrong_form": report["wrong_form_proposals"] == 0,
            "new_ocr_zero": True,
        }
        write(
            ROOT / DOC / "validation_gate.json",
            {
                "engineering_gate_passed": all(checks.values()),
                "checks": checks,
                "generalization": "ENGINEERING_ONLY",
                "exposure": "NO_CLEAN_VALIDATION_AVAILABLE",
                "strategy_freeze_sha256": report["strategy_freeze_sha256"],
            },
        )
    print(__import__("json").dumps(report, indent=2))
    return report


if __name__ == "__main__":
    import sys

    replay(sys.argv[1])
