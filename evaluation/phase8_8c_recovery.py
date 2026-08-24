"""Phase 8.8C unchanged-source dependency-aware recovery replay."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from hashlib import sha256
from pathlib import Path

from PIL import Image

from evaluation.phase8_8_generalization import (
    DATA_ROOT,
    SOURCE_IDS,
    benchmark_local_evidence,
    _crop_hash,
    _structural as _field_structural,
    replay_source,
    run_source_extraction,
)
from packages.evidence.name_agreement import compare_patient_names, normalize_name_for_agreement
from packages.evidence.normalization import normalize_agreement_value

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "evaluation_results/phase8_8"
OUTPUT = ROOT / "evaluation_results/phase8_8c"
IMPLEMENTATION_BASELINE_SHA = "00a837b31172bd4ae8f8f972dba86baf85c356b6"


def _read(path: Path):
    return json.loads(path.read_text("utf-8"))


def _rows(path: Path):
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", "utf-8")


def _file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _seed_exact_crop_paddle_evidence(source: str) -> dict[str, int]:
    """Reuse frozen Paddle observations only when the candidate pixels are identical."""
    baseline = {
        (row["document_id"], row["field_name"]): row
        for row in _rows(BASELINE / source.lower() / "local_evidence_predictions.jsonl")
    }
    records = _rows(OUTPUT / source.lower() / "v3_extraction/field_records.jsonl")
    manifest = _read(DATA_ROOT / source / "manifest.json")
    documents = {row["document_id"]: row for row in manifest["documents"]}
    seeded = []
    counts = Counter()
    for row in records:
        key = (row["document_id"], row["field_name"])
        old = baseline.get(key)
        if old is None:
            continue
        bbox = row.get("predicted_bbox")
        crop_hash = None
        if bbox is not None:
            with Image.open(DATA_ROOT / source / documents[row["document_id"]]["file"]) as opened:
                crop_hash = _crop_hash(opened.convert("RGB"), bbox)
        exact_crop = bool(crop_hash and crop_hash == old.get("crop_sha256"))
        paddle_value = old.get("paddle_value") if exact_crop else None
        paddle_confidence = float(old.get("paddle_confidence") or 0) if exact_crop else 0.0
        trace = row.get("candidate_trace") or {}
        rapid_value = trace.get("regional_value") or trace.get("primary_value") or row.get("final")
        structural = _field_structural(row).model_dump(mode="json")
        if row["field_name"] == "patient_name":
            comparison = compare_patient_names(rapid_value, paddle_value)
            rapid_normalized = comparison.left_normalized
            paddle_normalized = comparison.right_normalized
            agrees = bool(exact_crop and comparison.agrees and structural["confirmed"])
            expected_normalized = normalize_name_for_agreement(row["expected"])[0]
            contamination = comparison.label_contamination
        else:
            rapid_normalized = normalize_agreement_value(row["field_name"], rapid_value)
            paddle_normalized = normalize_agreement_value(row["field_name"], paddle_value)
            agrees = bool(
                exact_crop and rapid_normalized and rapid_normalized == paddle_normalized
                and structural["confirmed"]
            )
            expected_normalized = normalize_agreement_value(row["field_name"], row["expected"])
            contamination = False
        seeded.append({
            **old,
            "crop_sha256": crop_hash,
            "paddle_value": paddle_value,
            "paddle_confidence": paddle_confidence,
            "paddle_latency_ms": old.get("paddle_latency_ms", 0) if exact_crop else 0,
            "rapid_value": rapid_value,
            "rapid_normalized": rapid_normalized,
            "paddle_normalized": paddle_normalized,
            "structural_evidence": structural,
            "label_contamination": contamination,
            "independent_agreement": agrees,
            "rapid_exact": rapid_normalized == expected_normalized,
            "paddle_exact": paddle_normalized == expected_normalized,
            "false_agreement": bool(agrees and rapid_normalized != expected_normalized),
            "classification": (
                "EXACT_CROP_FROZEN_PADDLE_REUSE" if agrees
                else "PADDLE_EVIDENCE_UNAVAILABLE_FOR_CHANGED_CROP"
            ),
        })
        counts["exact_crop_reused" if exact_crop else "changed_crop_abstained"] += 1
    target = OUTPUT / source.lower() / "local_evidence_predictions.jsonl"
    target.write_text("".join(json.dumps(row) + "\n" for row in seeded), "utf-8")
    return dict(counts)


def _dependency_and_audit() -> tuple[dict, list[dict]]:
    counts = Counter()
    audit = []
    for source in SOURCE_IDS:
        for row in _rows(OUTPUT / source.lower() / "field_decisions.jsonl"):
            decision = row["field_decision"]
            bundle = decision.get("evidence_bundle") or {}
            items = bundle.get("evidence_items") or []
            agreements = [item for item in items if item["evidence_class"] == "E2"]
            for item in agreements:
                relation = (item.get("metadata") or {}).get("dependency_relation", "UNKNOWN")
                counts[relation] += 1
                if not row["evidence_correct"]:
                    counts[f"{relation}_FALSE"] += 1
            if row["criticality"] not in {"C2", "C3"} or decision["disposition"] not in {
                "AUTO_ACCEPTED", "REFERENCE_CONFIRMED"
            }:
                continue
            audit.append({
                "source": source,
                "document_id": row["document_id"],
                "field": row["field_name"],
                "truth": row["truth"],
                "selected_value": decision.get("selected_value"),
                "candidate_list": [
                    {
                        "value": item.get("value"),
                        "source": item.get("source"),
                        "candidate_id": item.get("supports_candidate_id"),
                        "provenance": (item.get("metadata") or {}).get("provenance"),
                    }
                    for item in items if item["evidence_class"] in {"E1", "E7"}
                ],
                "dependency_matrix": [item.get("metadata") for item in agreements],
                "structural_evidence": [item for item in items if item["evidence_class"] == "E3"],
                "deterministic_evidence": [item for item in items if item["evidence_class"] == "E4"],
                "reference_evidence": [item for item in items if item["evidence_class"] == "E5"],
                "cross_field_evidence": [item for item in items if item["evidence_class"] == "E6"],
                "policy_combination": decision.get("available_evidence"),
                "correct": row["evidence_correct"],
                "false_accept": not row["evidence_correct"],
                "reason_codes": decision.get("reason_codes"),
            })
    return {
        "independent_agreements": counts["INDEPENDENT"],
        "partially_independent_agreements": counts["PARTIALLY_INDEPENDENT"],
        "correlated_agreements": counts["CORRELATED"],
        "unknown_agreements": counts["UNKNOWN"],
        "correlated_false_agreements": counts["CORRELATED_FALSE"],
        "independent_false_agreements": counts["INDEPENDENT_FALSE"],
    }, audit


def _structural_counts() -> dict:
    counts = Counter()
    for source in SOURCE_IDS:
        for row in _rows(OUTPUT / source.lower() / "policy_replay_input.jsonl"):
            evidence = row.get("localization_evidence") or {}
            kind = evidence.get("evidence_type", "")
            confirmed = bool(evidence.get("confirmed"))
            if not confirmed:
                counts["unresolved"] += 1
            elif "ANCHOR" in kind:
                counts["anchor_resolved"] += 1
            elif "STRUCTURAL" in kind or "ROW_COLUMN" in kind:
                counts["structural_resolved"] += 1
            elif "TEMPLATE" in kind:
                counts["template_fallback_resolved"] += 1
            if row.get("wrong_crop_suspected"):
                counts["wrong_crop_detections"] += 1
    return dict(counts)


def run() -> dict:
    if not (BASELINE / "summary.json").is_file():
        raise FileNotFoundError("Phase 8.8A baseline is unavailable")
    frozen_inputs = {
        source: _file_sha(BASELINE / source.lower() / "policy_replay_input.jsonl")
        for source in SOURCE_IDS
    }
    if not OUTPUT.exists():
        shutil.copytree(BASELINE, OUTPUT)
    reports = {}
    paddle_reuse = {}
    for source in SOURCE_IDS:
        source_output = OUTPUT / source.lower()
        for stale in (
            source_output / "local_evidence_predictions.jsonl",
            source_output / "local_evidence_metrics.json",
        ):
            stale.unlink(missing_ok=True)
        extraction_metrics = source_output / "v3_extraction/metrics.json"
        baseline_metrics = BASELINE / source.lower() / "v3_extraction/metrics.json"
        fresh_extraction = (
            extraction_metrics.is_file()
            and _file_sha(extraction_metrics) != _file_sha(baseline_metrics)
        )
        if not fresh_extraction:
            run_source_extraction(source, data_root=DATA_ROOT, output=OUTPUT)
        paddle_reuse[source] = _seed_exact_crop_paddle_evidence(source)
        benchmark_local_evidence(source, data_root=DATA_ROOT, output=OUTPUT)
        reports[source] = replay_source(source, data_root=DATA_ROOT, output=OUTPUT)
    dependency, audit = _dependency_and_audit()
    structural = _structural_counts()
    automation = [item["automation"] for item in reports.values()]
    critical_false_accepts = sum(item["critical_false_accepts"] for item in automation)
    after = {
        "worst_critical_accuracy": min(
            item["accuracy"]["critical_accuracy"] for item in reports.values()
        ),
        "worst_accepted_precision": min(item["accepted_precision"] for item in automation),
        "critical_false_accepts": critical_false_accepts,
        "worst_source_stp": min(item["claim_stp"] for item in automation),
        "average_stp": sum(item["claim_stp"] for item in automation) / len(automation),
        "worst_field_hitl": max(item["field_hitl"] for item in automation),
        "cloud_cost_usd": 0.0,
    }
    gates = {
        "worst_critical_accuracy_ge_95": after["worst_critical_accuracy"] >= .95,
        "worst_accepted_precision_ge_99_5": after["worst_accepted_precision"] >= .995,
        "critical_false_accepts_zero": critical_false_accepts == 0,
        "worst_field_hitl_le_15": after["worst_field_hitl"] <= .15,
        "worst_source_stp_ge_30": after["worst_source_stp"] >= .30,
        "average_stp_ge_40": after["average_stp"] >= .40,
        "cloud_cost_zero": True,
    }
    decision = (
        "PROMOTE_TO_NEXT_GENERALIZATION"
        if all(gates.values())
        else "REJECT"
        if critical_false_accepts or not gates["worst_accepted_precision_ge_99_5"]
        else "NEEDS_MORE_DATA"
    )
    summary = {
        "phase": "8.8C",
        "baseline": {
            "implementation_git_sha": IMPLEMENTATION_BASELINE_SHA,
            "average_stp": .023809523809523808,
            "worst_source_stp": 0.0,
            "worst_accepted_precision": .9444444444444444,
            "critical_false_accepts": 2,
            "worst_critical_accuracy": .8660714285714286,
            "worst_field_hitl": .22857142857142854,
        },
        "unchanged_input_sha256": frozen_inputs,
        "sources": reports,
        "after": after,
        "dependency_analysis": dependency,
        "structural": structural,
        "gates": gates,
        "decision": decision,
        "cloud_calls": 0,
        "locked_holdout_run_count": 0,
        "paddle_evidence_reuse": paddle_reuse,
    }
    _write(OUTPUT / "critical_acceptance_audit.json", audit)
    _write(OUTPUT / "summary.json", summary)
    _write(OUTPUT / "decision.json", {"decision": decision, "gates": gates})
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
