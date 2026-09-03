"""P1 shadow qualification for identity and financial blocker routes.

This harness never changes runtime authority. It uses the frozen development
partition for fitting, the frozen validation partition for scoring, and keeps
the production holdout sealed.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from packages.confidence import fit_isotonic, fit_platt
from packages.extraction_recovery import select_field_span

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "evaluation/baselines/phase8_12"
TARGET_FIELDS = {
    "patient_name",
    "insured_name",
    "provider_name",
    "member_id",
    "provider_npi",
    "total_charge",
}


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def _key(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _correct(value: object, truth: object) -> bool:
    return bool(_key(value)) and _key(value) == _key(truth)


def _wilson_lower(successes: int, total: int) -> float:
    if not total:
        return 0.0
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - margin) / denominator


def _semantic_candidate(field: str, candidates: list[dict]) -> dict | None:
    ranked = []
    for candidate in candidates:
        raw = str(candidate.get("raw_value") or "")
        datatype = "PERSON_OR_ORGANIZATION" if field == "provider_name" else "PERSON_NAME"
        span = select_field_span(raw, datatype, field)
        value = span.selected_text
        provider_shape = bool(
            field == "provider_name"
            and re.fullmatch(r"[A-Z]{3,}(?:\s+[A-Z]{2,})+\s+\d{4}", value.upper())
        )
        label_collision = _key(value) in {
            "PATIENTNAME", "PROVIDERNAME", "PRINCIPALDIAGNOSIS", "TOTALCHARGE"
        }
        score = (
            int(provider_shape),
            -int(label_collision),
            float(candidate.get("raw_confidence") or 0),
        )
        ranked.append((score, candidate, value))
    if not ranked:
        return None
    _, candidate, value = max(ranked, key=lambda item: item[0])
    return {**candidate, "qualified_value": value}


def run(baseline: Path = BASELINE) -> dict:
    inputs = baseline / "inputs"
    validation_ids = set(json.loads((inputs / "validation_document_ids.json").read_text("utf-8")))
    replay_rows = [
        row
        for source in ("source_a", "source_b", "source_c")
        for row in _rows(inputs / source / "policy_replay_input.jsonl")
        if row["field_name"] in TARGET_FIELDS
    ]
    grouped = defaultdict(list)
    for row in replay_rows:
        score = max(
            (float(item.get("raw_confidence") or 0) for item in row["candidates"]),
            default=0.0,
        )
        grouped[row["field_name"]].append({
            **row,
            "score": score,
            "correct": _correct(row.get("final_value"), row.get("truth")),
            "split": "validation" if row["document_id"] in validation_ids else "development",
        })

    fields = {}
    for field, items in sorted(grouped.items()):
        training = [item for item in items if item["split"] == "development"]
        validation = [item for item in items if item["split"] == "validation"]
        if len(training) < 10 or len({item["correct"] for item in training}) < 2:
            calibration = {"status": "INSUFFICIENT_VARIATION", "training": len(training)}
        else:
            scores = [item["score"] for item in training]
            labels = [item["correct"] for item in training]
            models = [
                fit_platt(scores, labels, f"phase8.13:{field}:platt"),
                fit_isotonic(scores, labels, f"phase8.13:{field}:isotonic"),
            ]
            selected = min(
                models,
                key=lambda model: sum(
                    (model.predict(item["score"]) - item["correct"]) ** 2
                    for item in validation
                ),
            )
            accepted = [item for item in validation if selected.predict(item["score"]) >= 0.995]
            successes = sum(item["correct"] for item in accepted)
            calibration = {
                "status": "SHADOW_ONLY",
                "model_version": selected.version,
                "training": len(training),
                "validation": len(validation),
                "accepted": len(accepted),
                "accepted_precision": successes / len(accepted) if accepted else None,
                "precision_wilson_lower_95": _wilson_lower(successes, len(accepted)),
                "production_qualified": False,
            }
        semantic = []
        if "name" in field:
            for item in validation:
                selected = _semantic_candidate(field, item["candidates"])
                semantic.append(_correct(selected and selected["qualified_value"], item["truth"]))
        fields[field] = {
            "validation_fields": len(validation),
            "baseline_correct": sum(item["correct"] for item in validation),
            "baseline_accuracy": sum(item["correct"] for item in validation) / len(validation),
            "wrong_crop": sum(bool(item["wrong_crop_suspected"]) for item in validation),
            "semantic_candidate_accuracy": sum(semantic) / len(semantic) if semantic else None,
            "calibration": calibration,
        }
    return {
        "phase": "8.13-p1",
        "authority": "EVALUATION_ONLY",
        "locked_holdout_accessed": False,
        "production_promotions": 0,
        "fields": fields,
        "blockers": dict(Counter(
            "WRONG_CROP" if item["wrong_crop_suspected"] else "EVIDENCE_OR_ROUTE"
            for items in grouped.values() for item in items if item["split"] == "validation"
        )),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.baseline)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
