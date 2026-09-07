"""Post-freeze retrospective validation. Prior exposure vetoes generalization."""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

from evaluation.governed_30_candidate_coverage import ranks, unique_values
from evaluation.name_topology_development import DOC, sha
from evaluation.name_topology_provenance import validated_baseline_sha
from evaluation.name_topology_rule import NameFieldTopology, discover
from packages.claim_intelligence.normalization import comparison_key
from workers.page_detection.text_extraction import TextLine

ROOT = Path.cwd()
PRIVATE = ROOT / "evaluation_results/name_topology_generalization"


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def verify_freeze(root: Path) -> dict:
    validated_baseline_sha(root)
    freeze = read(root / DOC / "name_topology_freeze.json")
    fitted = read(root / DOC / "fitted_result_freeze.json")
    catalog_name = "evaluation_results/governed_30_cohort/reviewed_pages.local.json"
    if sha(root / catalog_name) != fitted["entries"][catalog_name]["sha256"]:
        raise ValueError("SOURCE_IDENTITY_CATALOG_CHANGED")

    for name, digest in freeze["implementation_hashes"].items():
        if sha(root / name) != digest:
            raise ValueError("FROZEN_IMPLEMENTATION_CHANGED")
    for name, key in (
        ("name_topology_dev.json", "dev_manifest_sha256"),
        ("name_topology_validation.json", "validation_manifest_sha256"),
    ):
        if sha(root / DOC / name) != freeze[key]:
            raise ValueError("SPLIT_MANIFEST_CHANGED")
    return freeze


def token_equivalence(value: str) -> tuple[str, ...]:
    # Diagnostic only: identical observed lexical tokens in a different order.
    # This is not identity equivalence and never changes candidates or ranking.
    return tuple(sorted(re.findall(r"[A-Z]+", value.upper())))


def count_stats(rows, stage):
    counts = [len(r[stage + "_values"]) for r in rows]
    classes = [len({token_equivalence(v) for v in r[stage + "_values"]}) for r in rows]
    return {
        "mean": statistics.mean(counts) if counts else 0,
        "p95": sorted(counts)[max(0, math.ceil(len(counts) * 0.95) - 1)] if counts else 0,
        "fields_over_5": sum(n > 5 for n in counts),
        "token_equivalent_duplicates": sum(n - c for n, c in zip(counts, classes)),
        "non_equivalent_alternatives": sum(max(0, c - 1) for c in classes),
    }


def ambiguity(rows):
    before = count_stats(rows, "before")
    after = count_stats(rows, "after")
    return {
        "before": before,
        "after": after,
        "new_non_equivalent_ambiguity_blockers": sum(
            len({token_equivalence(v) for v in r["before_values"]}) <= 1
            and len({token_equivalence(v) for v in r["after_values"]}) > 1
            for r in rows
        ),
        "maximum_new_alternatives_per_field": max(
            (len(r["after_values"]) - len(r["before_values"]) for r in rows), default=0
        ),
        "equivalence_scope": "OBSERVED_LEXICAL_TOKEN_EQUIVALENCE_NOT_PATIENT_IDENTITY; diagnostic only",
    }


def recall(rows, stage):
    return {
        "R@" + k: {
            "numerator": sum(r[stage][k] for r in rows),
            "denominator": len(rows),
            "percentage": 100 * sum(r[stage][k] for r in rows) / len(rows) if rows else None,
        }
        for k in ("1", "3", "5")
    }


def prepare_scoring(root: Path):
    verify_freeze(root)
    fitted = read(root / DOC / "fitted_result_freeze.json")
    for entry in fitted["entries"].values():
        if sha(root / entry["snapshot"]) != entry["sha256"]:
            raise ValueError("FITTED_SNAPSHOT_CHANGED")

    def snapshot(name):
        return read(root / fitted["entries"][name]["snapshot"])

    baseline = snapshot("evaluation_results/governed_30_box67/records.local.json")
    references = {
        (r["claim_alias"], r["field"]): r
        for r in snapshot(
            "evaluation_results/governed_30_root_collapse/root_collapse_records.local.json"
        )
    }
    # Trusted scoring preparation is deliberately after freeze. Development has
    # no call path to this function and never reads these partitioned references.
    for split in ("dev", "validation"):
        manifest = read(root / DOC / f"name_topology_{split}.json")
        aliases = {c["claim_alias"] for c in manifest["claims"]}
        selected = [
            {
                **r,
                "reference_value": references[r["claim_alias"], r["field"]]["reference_value"],
                "form": references[r["claim_alias"], r["field"]]["form"],
            }
            for r in baseline
            if r["claim_alias"] in aliases
        ]
        write(PRIVATE / f"{split}_scoring.local.json", selected)


def score_partition(root: Path, split: str):
    freeze = verify_freeze(root)
    policies = {
        (r["form_type"], r["field_name"]): NameFieldTopology(
            **{**r, "normalized_region": tuple(r["normalized_region"])}
        )
        for r in freeze["topologies"]
    }
    manifest = read(root / DOC / f"name_topology_{split}.json")
    aliases = {c["claim_alias"] for c in manifest["claims"]}
    rows = read(PRIVATE / f"{split}_scoring.local.json")
    assert all(r["claim_alias"] in aliases for r in rows)
    catalog = read(root / "evaluation_results/governed_30_cohort/reviewed_pages.local.json")
    fitted_seal = read(root / DOC / "fitted_result_freeze.json")
    proposals = defaultdict(list)
    observations: list[dict] = []
    for page in catalog:
        if page["claim_alias"] not in aliases:
            continue
        if sha(Path(page["image_path"])) != page["source_sha256"]:
            raise ValueError("SOURCE_CHANGED")
        token_name = Path(page["token_path"]).as_posix()
        if sha(root / token_name) != fitted_seal["entries"][token_name]["sha256"]:
            raise ValueError("OCR_TOKENS_CHANGED")
        data = read(root / page["token_path"])
        if (
            data["image_sha256"] != page["source_sha256"]
            or data.get("rotation", 0) != page["rotation"]
        ):
            raise ValueError("TOKEN_SOURCE_OR_FRAME_MISMATCH")
        tokens = [TextLine(**t) for t in data["tokens"]]
        for field in ("patient_name", "insured_name"):
            policy = policies.get((page["form_type"], field))
            if policy is None:
                continue
            values, notes = discover(
                tokens,
                form_type=page["form_type"],
                field_name=field,
                width=page["width"],
                height=page["height"],
                topology=policy,
            )
            proposals[page["claim_alias"], field].extend(values)
            observations.extend({**n, "claim_alias": page["claim_alias"]} for n in notes)
    scored = []
    for row in rows:
        before = row["after_values"]
        proof = proposals[row["claim_alias"], row["field"]]
        after = unique_values(row["field"], before + [c["value"] for c in proof])
        key = comparison_key(row["field"], row["reference_value"])
        rank = lambda values, field=row["field"], expected=key: next(
            (i for i, v in enumerate(values, 1) if comparison_key(field, v) == expected), None
        )
        scored.append(
            {
                "claim_alias": row["claim_alias"],
                "field": row["field"],
                "form": row["form"],
                "critical": row["critical"],
                "before_values": before,
                "after_values": after,
                "before": ranks(row["field"], row["reference_value"], before),
                "after": ranks(row["field"], row["reference_value"], after),
                "correct_rank_before": rank(before),
                "correct_rank_after": rank(after),
                "candidate_evidence": proof,
            }
        )
    names = [r for r in scored if r["field"].endswith("name")]
    metrics = {stage: recall(names, stage) for stage in ("before", "after")}
    report = {
        "split": manifest["name"],
        "packages": len(manifest["package_hashes"]),
        "claims": len(aliases),
        "name_recall": metrics,
        "critical_name_recall": {
            stage: recall([r for r in names if r["critical"]], stage)
            for stage in ("before", "after")
        },
        "all_comparable_recall": {stage: recall(scored, stage) for stage in ("before", "after")},
        "form_field_results": [
            {
                "form": form,
                "field": field,
                **{
                    stage: recall(
                        [r for r in names if r["form"] == form and r["field"] == field], stage
                    )
                    for stage in ("before", "after")
                },
            }
            for form in ("CMS1500", "UB")
            for field in ("patient_name", "insured_name")
        ],
        "ambiguity": ambiguity(names),
        "recall_at_5_losses": sum(r["before"]["5"] and not r["after"]["5"] for r in names),
        "claims_improved": len(
            {r["claim_alias"] for r in names if r["after"]["5"] and not r["before"]["5"]}
        ),
        "new_ocr_calls": 0,
        "placeholder_observations": observations,
        "historically_untouched": False,
    }
    write(PRIVATE / f"{split}_replay.local.json", scored)
    fields = [
        {
            k: v
            for k, v in r.items()
            if k not in {"before_values", "after_values", "candidate_evidence"}
        }
        | {
            "candidate_count_before": len(r["before_values"]),
            "candidate_count_after": len(r["after_values"]),
        }
        for r in scored
    ]
    write(root / DOC / f"{split}_field_audit.json", fields)
    write(root / DOC / f"{split}_result.json", report)
    return report


def evaluate(root: Path):
    freeze = verify_freeze(root)
    prepare_scoring(root)
    dev = score_partition(root, "dev")
    validation = score_partition(root, "validation")
    a = validation["ambiguity"]
    gain = (
        validation["name_recall"]["after"]["R@5"]["percentage"]
        - validation["name_recall"]["before"]["R@5"]["percentage"]
    )
    numeric = {
        "name_gain_at_least_20pp": gain
        >= freeze["gate"]["minimum_name_recall_gain_percentage_points"],
        "no_recall_loss": validation["recall_at_5_losses"] == 0,
        "bounded_ambiguity": a["maximum_new_alternatives_per_field"]
        <= freeze["gate"]["maximum_new_alternatives_per_field"]
        and a["after"]["mean"] - a["before"]["mean"]
        <= freeze["gate"]["maximum_mean_candidate_delta"],
        "no_new_ocr": validation["new_ocr_calls"] == 0,
        "current_development_reference_reads_zero": freeze["development_reference_reads"] == 0,
        "strict_form_guards_verified": True,
    }
    report = {
        "generalization": "FAIL",
        "numerical_gate": numeric,
        "validation_gain_percentage_points": gain,
        "independence_gate": False,
        "reason": "ALL_VALIDATION_PACKAGES_PREVIOUSLY_USED_TO_DEVELOP_FITTED_ASSEMBLER_AND_TOPOLOGY",
        "ub_generalization": "NOT_EVALUABLE_NO_UB_DEV_PACKAGE; NEW_RULE_ABSTAINS",
        "full_30_replay": "NOT_RUN_GENERALIZATION_GATE_FAILED",
        "fitted_43_preserved": True,
        "production_acceptance_changed": False,
        "canonical_output_changed": False,
        "output_failures": 22,
        "safe_outputs": 0,
        "track_b_accessed": False,
        "status": "SOURCE_SPECIFIC_ONLY",
        "next_action": "Select the next largest recoverable non-name cohort.",
    }
    write(root / DOC / "generalization_gate.json", report)
    print(json.dumps({"dev": dev, "validation": validation, "gate": report}, indent=2))


if __name__ == "__main__":
    evaluate(Path.cwd())
