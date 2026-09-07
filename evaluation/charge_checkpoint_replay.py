"""Hash-sealed total-charge pilots and frozen 30-claim engineering replay."""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from evaluation.charge_checkpoint_rule import ChargeCell, discover, ocr_allowed
from evaluation.non_name_experiment import ambiguity, metrics, score_row
from evaluation.non_name_inputs import digest, pages, read, refs, write
from evaluation.non_name_replay import distance
from evaluation.ub_birthdate_replay import verify as verify_baseline
from workers.page_detection.text_extraction import TextLine

ROOT = Path.cwd()
DOC = ROOT / "docs/closure/charge_checkpoint"
PRIVATE = ROOT / "evaluation_results/charge_checkpoint"
BASE = ROOT / "evaluation_results/ub_birthdate_recovery/full_replay.local.json"
REGISTRY = PRIVATE / "source_cells.local.json"


def freeze():
    verify_baseline()
    targets = [
        BASE,
        REGISTRY,
        Path(__file__),
        ROOT / "evaluation/charge_checkpoint_rule.py",
        ROOT / "tests/unit/test_charge_checkpoint_rule.py",
        ROOT / "dataset_raw/NSF_matrix.txt",
        ROOT / "dataset_raw/UB92_specs.txt",
        ROOT / "evaluation/governed_30_reference.py",
    ]
    for p, _ in pages(ROOT, "full"):
        targets.append(ROOT / p["token_path"])
    targets.extend(
        ROOT / name
        for name in [
            "docs/closure/ub_birthdate_recovery/full_scorecard.json",
            "docs/closure/ub_birthdate_recovery/birthdate_strategy_freeze.json",
            "docs/closure/non_name_cohort/non_name_strategy_freeze.json",
            "evaluation_results/governed_30_candidate_coverage/primary_capture_input.local.json",
        ]
    )
    result = {
        "scope": "EXPOSED_GOVERNED_30_ENGINEERING_ONLY",
        "clean_validation": False,
        "denominators": {"all": 118, "critical": 86},
        "input_hashes": {p.relative_to(ROOT).as_posix(): digest(p) for p in targets},
        "secondary_ocr": {
            "engine": "RapidOCR-ONNX",
            "calls_max": 5,
            "preprocessing": "adapter default 3x Lanczos; one call per reviewed cell; no character repair",
        },
        "selection": "Retain distinct causes with positive Recall@5 gain and no coverage regression; report all alternatives",
        "production_changes": False,
        "track_b_accessed": False,
    }
    if (DOC / "strategy_freeze.json").exists():
        if read(DOC / "strategy_freeze.json") != result:
            raise ValueError("REFUSING_TO_REPLACE_FROZEN_EXPERIMENT")
    else:
        write(DOC / "strategy_freeze.json", result)


def verify():
    verify_baseline()
    seal = read(DOC / "strategy_freeze.json")
    for name, sha in seal["input_hashes"].items():
        if digest(ROOT / name) != sha:
            raise ValueError("FROZEN_CHARGE_INPUT_CHANGED: " + name)
    capture = read(
        ROOT / "evaluation_results/governed_30_candidate_coverage/primary_capture_input.local.json"
    )["pages"]
    assert len(capture) == 67
    for page in capture:
        if digest(page["image_path"]) != page["image_sha256"]:
            raise ValueError("SOURCE_CHANGED")
    return seal


def cell_for(row):
    return ChargeCell(
        **{**row["cell"], "normalized_region": tuple(row["cell"]["normalized_region"])}
    )


def run_ocr():
    verify()
    from PIL import Image

    from workers.page_detection.text_extraction import RapidOCRTextExtractor

    engine = RapidOCRTextExtractor(intra_op_num_threads=2, inter_op_num_threads=1)
    eligible = [r for r in read(REGISTRY) if not r["primary_value_present"]]
    assert len(eligible) <= 5
    for r in eligible:
        p, cell = r["page"], cell_for(r)
        assert ocr_allowed(
            cell,
            form_type=p["form_type"],
            source_sha256=digest(p["image_path"]),
            value_visible=r["value_visible"],
            primary_value_present=r["primary_value_present"],
        )
        dest = PRIVATE / (p["claim_alias"] + "_secondary.local.json")
        if dest.exists():
            if read(dest)["strategy_sha256"] != digest(DOC / "strategy_freeze.json"):
                raise ValueError("OCR_CACHE_STRATEGY_MISMATCH")
            continue
        with Image.open(p["image_path"]) as im:
            im = im.convert("RGB").rotate(p["rotation"])
            bounds = [
                round(v * (im.width if i % 2 == 0 else im.height))
                for i, v in enumerate(cell.normalized_region)
            ]
            start = perf_counter()
            tokens = engine.extract_region(im, *bounds)
            seconds = perf_counter() - start
        write(
            dest,
            {
                "claim_alias": p["claim_alias"],
                "source_sha256": p["source_sha256"],
                "strategy_sha256": digest(DOC / "strategy_freeze.json"),
                "region_bbox": bounds,
                "engine": engine.engine_name,
                "model": engine.model_name,
                "seconds": seconds,
                "tokens": [asdict(t) for t in tokens],
                "primary_value_present": False,
                "source_value_visible": True,
                "review_only": True,
            },
        )
        print(p["claim_alias"], len(tokens), round(seconds, 3), flush=True)


def inventory(rows, stage):
    groups = {
        "member_id": ["member_id"],
        "patient_dob": ["patient_dob"],
        "service_date": ["service_date"],
        "total_charge": ["total_charge"],
        "principal_diagnosis": ["principal_diagnosis"],
        "names": ["patient_name", "insured_name"],
    }
    known = {f for fs in groups.values() for f in fs}
    groups["other"] = sorted({r["field"] for r in rows} - known)
    result = {}
    for key, fields in groups.items():
        selected = [r for r in rows if r["field"] in fields]
        missed = [r for r in selected if not r[stage]["5"]]
        result[key] = {
            "total": len(selected),
            "covered": len(selected) - len(missed),
            "remaining": len(missed),
            "critical_total": sum(r["critical"] for r in selected),
            "critical_remaining": sum(r["critical"] for r in missed),
            "claims_affected": len({r["claim_alias"] for r in missed}),
        }
    return result


def replay():
    verify()
    baseline = read(BASE)
    assert len(baseline) == 118 and sum(r["critical"] for r in baseline) == 86
    assert sum(r["after"]["5"] for r in baseline) == 51
    primary = {p["claim_alias"]: ts for p, ts in pages(ROOT, "full")}
    proposed = {k: defaultdict(list) for k in "ABC"}
    elapsed = Counter()
    attempted = {k: set() for k in "ABC"}
    ocr_seconds = 0.0
    for r in read(REGISTRY):
        p, cell = r["page"], cell_for(r)
        args = {
            "form_type": p["form_type"],
            "source_sha256": p["source_sha256"],
            "width": p["width"],
            "height": p["height"],
            "cell": cell,
        }
        for kind in "AB":
            start = perf_counter()
            values = discover(primary[p["claim_alias"]], pilot=kind, **args)
            elapsed[kind] += (perf_counter() - start) * 1000
            if values:
                attempted[kind].add(p["claim_alias"])
            proposed[kind][p["claim_alias"]] = values
        if not r["primary_value_present"]:
            attempted["C"].add(p["claim_alias"])
            data = read(PRIVATE / (p["claim_alias"] + "_secondary.local.json"))
            if (
                data["strategy_sha256"] != digest(DOC / "strategy_freeze.json")
                or data["source_sha256"] != p["source_sha256"]
            ):
                raise ValueError("UNBOUND_SECONDARY_TOKENS")
            tokens = [TextLine(**t) for t in data["tokens"]]
            start = perf_counter()
            values = discover(tokens, pilot="A", **args) + discover(tokens, pilot="B", **args)
            elapsed["C"] += (perf_counter() - start) * 1000 + data["seconds"] * 1000
            ocr_seconds += data["seconds"]
            proposed["C"][p["claim_alias"]] = values
    # Truth enters only after independent geometry, OCR and numeric generation.
    expected = refs(ROOT, "dev") | refs(ROOT, "validation")

    def score(kinds):
        result = []
        for row in baseline:
            proof = (
                [c | {"pilot": k} for k in kinds for c in proposed[k][row["claim_alias"]]]
                if row["field"] == "total_charge"
                else []
            )
            scored = score_row(
                row, [c["value"] for c in proof], expected[row["claim_alias"], row["field"]]
            )
            scored["evidence"] = proof
            assert all(not row["after"][k] or scored["after"][k] for k in ("1", "3", "5"))
            if row["field"] != "total_charge":
                assert scored["after_values"] == row["after_values"]
            result.append(scored)
        return result

    def summary(rows):
        charges = [r for r in rows if r["field"] == "total_charge"]
        gained = [r for r in charges if r["after"]["5"] and not r["before"]["5"]]
        return {
            "recovered": len(gained),
            "critical_recovered": sum(r["critical"] for r in gained),
            "claims_improved": len({r["claim_alias"] for r in gained}),
            "new_candidates": sum(
                len(r["after_values"]) - len(r["before_values"]) for r in charges
            ),
            "ambiguity": ambiguity(charges),
            "recovered_fields": [
                {
                    "claim_alias": r["claim_alias"],
                    "critical": r["critical"],
                    "rank_before": r["correct_rank_before"],
                    "rank_after": r["correct_rank_after"],
                }
                for r in gained
            ],
        }

    pilots = {}
    for k in "ABC":
        rows = score(k)
        write(PRIVATE / ("pilot_" + k + ".local.json"), rows)
        pilots[k] = summary(rows) | {
            "attempted": len(attempted[k]),
            "secondary_ocr_calls": len(attempted[k]) if k == "C" else 0,
            "latency_ms": elapsed[k],
            "latency_scope": "generation plus actual OCR; excludes evaluation and source loading",
        }
    retained = [k for k in "ABC" if pilots[k]["recovered"] > 0]
    result = score(retained)
    write(PRIVATE / "full_replay.local.json", result)
    report = summary(result) | {
        "scope": "FROZEN_30_ENGINEERING_ONLY",
        "clean_validation": False,
        "claims": 30,
        "metrics": metrics(result),
        "critical_metrics": metrics([r for r in result if r["critical"]]),
        "pilots": pilots,
        "retained_strategies": retained,
        "all_field_ambiguity": ambiguity(result),
        "inventory_before": inventory(result, "before"),
        "inventory_after": inventory(result, "after"),
        "claim_distance": {
            "before": distance(result, "before"),
            "after": distance(result, "after"),
        },
        "new_primary_ocr_calls": 0,
        "secondary_ocr_calls": len(attempted["C"]),
        "llm_calls": 0,
        "secondary_ocr_seconds": ocr_seconds,
        "coverage_regressions": 0,
        "new_semantic_regressions": 0,
        "production_acceptance_changed": False,
        "canonical_outputs_changed": False,
        "track_b_accessed": False,
        "safe_outputs": 0,
        "output_failures": 22,
        "status": "CHECKPOINT_50_REACHED"
        if sum(r["after"]["5"] for r in result) >= 59
        else "MEANINGFUL_CHARGE_GAIN",
        "strategy_sha256": digest(DOC / "strategy_freeze.json"),
        "private_replay_sha256": digest(PRIVATE / "full_replay.local.json"),
    }
    write(DOC / "full_scorecard.json", report)
    write(
        DOC / "full_field_audit.json",
        [
            {k: v for k, v in r.items() if k not in {"before_values", "after_values", "evidence"}}
            for r in result
        ],
    )
    print(report["status"], report["metrics"], report["critical_metrics"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--ocr", action="store_true")
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.ocr:
        run_ocr()
    else:
        replay()
