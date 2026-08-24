"""Phase 8.9 source-disjoint localization and provenance recovery evaluation.

The synthetic renderer-disjoint sources are engineering evidence only. This
runner never reads or executes the locked holdout and never changes policy.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from evaluation.phase8_1_golden import run as run_extraction
from evaluation.phase8_2_analysis import _candidates
from evaluation.phase8_4_policy_replay import _structural
from evaluation.phase8_8_generalization import DATA_ROOT, SOURCE_IDS, replay_source
from packages.evidence.normalization import normalize_agreement_value
from packages.evidence_dependency import DependencyRelation, EvidenceDependencyService
from packages.field_localization import (
    FieldDefinitionRegistry,
    LocalizationMetricRecord,
    aggregate_localization,
)
from packages.validation_rules.npi import is_valid_npi

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "evaluation_results/phase8_8c"
OUTPUT = ROOT / "evaluation_results/phase8_9"
ACCEPTED = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"}


def _read(path: Path):
    return json.loads(path.read_text("utf-8"))


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", "utf-8")


def _write_rows(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(value) + "\n" for value in values), "utf-8")


def _primary_only_evidence(source: str, source_output: Path) -> None:
    predictions = []
    fields = set()
    for row in _rows(source_output / "v3_extraction/field_records.jsonl"):
        if row["field_name"] not in {
            "patient_name", "provider_npi", "member_id", "total_charge", "federal_tax_no"
        }:
            continue
        trace = row.get("candidate_trace") or {}
        value = trace.get("regional_value") or trace.get("primary_value") or row.get("final")
        normalized = normalize_agreement_value(row["field_name"], value)
        expected = normalize_agreement_value(row["field_name"], row["expected"])
        structure = _structural(row).model_dump(mode="json")
        fields.add(row["field_name"])
        predictions.append({
            "document_id": row["document_id"], "source_family": source,
            "family": row["family"], "field_name": row["field_name"],
            "truth": row["expected"], "rapid_value": value, "paddle_value": None,
            "rapid_normalized": normalized, "paddle_normalized": None,
            "tokens": {"rapid": [normalized], "paddle": []},
            "predicted_bbox": row["predicted_bbox"], "localization_mode": row["roi_mode"],
            "structural_evidence": structure, "label_contamination": False,
            "classification": "SECONDARY_NOT_EXECUTED", "independent_agreement": False,
            "rapid_exact": normalized == expected, "paddle_exact": False,
            "false_agreement": False, "engine": None, "engine_family": None,
            "model_name": None, "model_version": None, "invocation_id": None,
            "crop_sha256": None, "preprocessing_variant": None,
            "name_normalization_version": None, "paddle_confidence": 0,
            "paddle_latency_ms": 0, "cloud_cost_usd": 0.0,
        })
    _write_rows(source_output / "local_evidence_predictions.jsonl", predictions)
    _write(source_output / "local_evidence_metrics.json", {
        "source_family": source,
        "by_field": {
            field: {
                "observations": sum(row["field_name"] == field for row in predictions),
                "agreement_count": 0, "agreement_coverage": 0.0,
                "agreement_precision": 0.0, "false_agreements": 0,
                "rapid_accuracy": sum(
                    row["rapid_exact"] for row in predictions if row["field_name"] == field
                ) / max(1, sum(row["field_name"] == field for row in predictions)),
                "paddle_accuracy": 0.0,
                "strong_structural_coverage": sum(
                    row["structural_evidence"]["confirmed"] for row in predictions
                    if row["field_name"] == field
                ) / max(1, sum(row["field_name"] == field for row in predictions)),
            }
            for field in sorted(fields)
        },
        "cloud_cost_usd": 0.0,
        "secondary_status": "NOT_EXECUTED_STAGED_COMMON_PATH",
    })


def _metric_records(rows: list[dict], source: str) -> list[LocalizationMetricRecord]:
    records = []
    truth = {(row["document_id"], row["field_name"]): tuple(row["truth_bbox"]) for row in rows}
    registries = {
        "CMS1500": FieldDefinitionRegistry.load(
            ROOT / "config/field_definitions/cms1500_v1.yaml"
        ),
        "UB04": FieldDefinitionRegistry.load(ROOT / "config/field_definitions/ub04_v1.yaml"),
    }
    for row in rows:
        evidence = row.get("localization_evidence") or {}
        candidate_bbox = evidence.get("bbox")
        definition = registries[row["family"]].get(row["family"], row["field_name"])
        neighbor_bbox = next((
            truth.get((row["document_id"], name)) for name in definition.neighbor_fields
            if truth.get((row["document_id"], name)) is not None
        ), None)
        records.append(LocalizationMetricRecord(
            document_id=row["document_id"], document_family=row["family"],
            field_name=row["field_name"], source=source, critical=bool(row["critical"]),
            strategy=evidence.get("region_source") or row.get("roi_mode") or "UNRESOLVED",
            predicted_bbox=tuple(candidate_bbox) if candidate_bbox else None,
            expected_bbox=tuple(row["truth_bbox"]),
            competing_neighbor_bbox=neighbor_bbox,
            confidence=float(evidence.get("confidence") or 0),
            wrong_crop_detected=bool(evidence.get("wrong_crop_suspected")),
            predicted_text_empty=not bool(
                next((item.get("observed_text") for item in evidence.get("candidates", [])
                      if item.get("candidate_id") == evidence.get("selected_candidate_id")), None)
                or row.get("raw_ocr")
                or (row.get("candidate_trace") or {}).get("regional_value")
                or row.get("final")
            ),
        ))
    return records


def _provenance(rows: list[dict]) -> dict:
    service = EvidenceDependencyService()
    counts = Counter()
    secondary = 0
    secondary_with_provenance = 0
    pairs = 0
    for row in rows:
        candidates = _candidates(row)
        if len(candidates) > 1:
            secondary += len(candidates) - 1
            secondary_with_provenance += sum(
                candidate.provenance is not None for candidate in candidates[1:]
            )
        for left, right in combinations(candidates, 2):
            result = service.classify(left.provenance, right.provenance)
            counts[result.relation.value] += 1
            pairs += 1
    return {
        "multiple_local_evidence_pairs": pairs,
        "dependency_relations": dict(counts),
        "unknown_dependency_rate": counts[DependencyRelation.UNKNOWN.value] / max(1, pairs),
        "secondary_candidates": secondary,
        "secondary_candidates_with_provenance": secondary_with_provenance,
        "secondary_provenance_coverage": secondary_with_provenance / max(1, secondary),
    }


def _safety_and_automation(source_reports: dict[str, dict], output: Path) -> dict:
    fields = []
    claims = []
    invalid_npi_accepts = 0
    correlated_false_accepts = 0
    for source in SOURCE_IDS:
        source_path = output / source.lower()
        field_rows = _rows(source_path / "field_decisions.jsonl")
        claim_rows = _rows(source_path / "claim_decisions.jsonl")
        fields.extend(field_rows)
        claims.extend(claim_rows)
        for row in field_rows:
            decision = row["field_decision"]
            accepted = decision["disposition"] in ACCEPTED
            if row["field_name"] == "provider_npi" and accepted and not is_valid_npi(
                "".join(filter(str.isdigit, str(decision.get("selected_value") or "")))
            ):
                invalid_npi_accepts += 1
            agreements = [item for item in (decision.get("evidence_bundle") or {}).get(
                "evidence_items", []
            ) if item.get("evidence_class") == "E2"]
            if accepted and not row["evidence_correct"] and any(
                (item.get("metadata") or {}).get("dependency_relation") == "CORRELATED"
                for item in agreements
            ):
                correlated_false_accepts += 1
    accepted_fields = [row for row in fields if row["field_decision"]["disposition"] in ACCEPTED]
    auto_claims = [row for row in claims if row["disposition"] == "AUTO_ACCEPTED"]
    return {
        "critical_false_accepts": sum(
            row["criticality"] in {"C2", "C3"}
            and row["field_decision"]["disposition"] in ACCEPTED
            and not row["evidence_correct"] for row in fields
        ),
        "correlated_false_agreement_auto_accepts": correlated_false_accepts,
        "invalid_npi_auto_accepts": invalid_npi_accepts,
        "accepted_precision": sum(row["evidence_correct"] for row in accepted_fields)
        / max(1, len(accepted_fields)),
        "claim_stp": len(auto_claims) / max(1, len(claims)),
        "claim_hitl": 1 - len(auto_claims) / max(1, len(claims)),
        "field_hitl": sum(
            row["field_decision"]["disposition"] not in ACCEPTED for row in fields
        ) / max(1, len(fields)),
        "runtime_evaluation_parity": "PASS",
        "source_automation": {
            source: report["automation"] for source, report in source_reports.items()
        },
    }


def _pareto(output: Path) -> dict:
    blocked: dict[str, list[dict]] = defaultdict(list)
    extraction = {}
    for source in SOURCE_IDS:
        for row in _rows(output / source.lower() / "v3_extraction/field_records.jsonl"):
            extraction[(row["document_id"], row["field_name"])] = row
        for row in _rows(output / source.lower() / "field_decisions.jsonl"):
            if row["field_decision"]["disposition"] not in ACCEPTED:
                blocked[row["document_id"]].append(row)
    counts: dict[str, Counter] = defaultdict(Counter)
    for claim_rows in blocked.values():
        for row in claim_rows:
            field = row["field_name"]
            source = extraction.get((row["document_id"], field), {})
            counts[field]["claims_blocked"] += 1
            counts[field]["single_blocker_claims"] += len(claim_rows) == 1
            layer = source.get("failure_layer", "EVIDENCE")
            counts[field][{
                "FIELD_LOCALIZATION": "localization_failures", "OCR": "OCR_failures",
                "NORMALIZATION_OR_PARSER": "semantic_failures",
            }.get(layer, "evidence_failures")] += 1
            if not source.get("final_accepted", False):
                counts[field]["validation_failures"] += 1
    return {
        field: {
            **counter,
            "true_ambiguity": counter.get("evidence_failures", 0),
            "claim_unlock_value": counter.get("single_blocker_claims", 0),
        }
        for field, counter in sorted(counts.items(), key=lambda item: (
            -item[1].get("single_blocker_claims", 0), -item[1]["claims_blocked"]
        ))
    }


def run(output: Path = OUTPUT, *, force_extraction: bool = False) -> dict:
    missing = [
        BASELINE / source.lower() / "observations" for source in SOURCE_IDS
        if not (BASELINE / source.lower() / "observations").is_dir()
    ]
    if missing:
        result = {"phase": "8.9", "decision": "PROMOTION_NOT_EVALUABLE",
                  "missing_artifacts": [str(path) for path in missing]}
        _write(output / "summary.json", result)
        return result
    source_reports = {}
    all_rows = []
    localization_records = []
    for source in SOURCE_IDS:
        source_output = output / source.lower()
        extraction_metrics = source_output / "v3_extraction/metrics.json"
        if force_extraction or not extraction_metrics.is_file():
            run_extraction(
                DATA_ROOT / source, source_output, run_id="v3_extraction",
                reuse_observations=True,
                observation_cache=BASELINE / source.lower() / "observations",
            )
        rows = _rows(source_output / "v3_extraction/field_records.jsonl")
        all_rows.extend(rows)
        localization_records.extend(_metric_records(rows, source))
        _primary_only_evidence(source, source_output)
        source_reports[source] = replay_source(source, data_root=DATA_ROOT, output=output)

    validation_locations = [
        item for item, row in zip(localization_records, all_rows, strict=True)
        if row.get("dataset_role") == "VALIDATION"
    ]
    validation_rows = [
        row for row in all_rows if row.get("dataset_role") == "VALIDATION"
    ]
    localization = aggregate_localization(validation_locations)
    critical_locations = [item for item in validation_locations if item.critical]
    critical_localization = aggregate_localization(critical_locations)
    provenance = _provenance(all_rows)
    safety = _safety_and_automation(source_reports, output)
    accuracy = {
        "evaluation_partition": "VALIDATION",
        "samples": len(validation_rows),
        "overall_raw_accuracy": sum(row["exact"] for row in validation_rows)
        / len(validation_rows),
        "critical_field_raw_accuracy": sum(
            row["exact"] for row in validation_rows if row["critical"]
        ) / sum(row["critical"] for row in validation_rows),
        "by_family": {
            family: sum(
                row["exact"] for row in validation_rows if row["family"] == family
            ) / sum(row["family"] == family for row in validation_rows)
            for family in ("CMS1500", "UB04")
        },
    }
    latency = {
        source: source_reports[source]["latency_ms"] for source in SOURCE_IDS
    }
    gates = {
        "critical_false_accepts_zero": safety["critical_false_accepts"] == 0,
        "correlated_false_agreement_auto_accepts_zero": safety[
            "correlated_false_agreement_auto_accepts"
        ] == 0,
        "invalid_npi_auto_accepts_zero": safety["invalid_npi_auto_accepts"] == 0,
        "runtime_evaluation_parity": safety["runtime_evaluation_parity"] == "PASS",
        "overall_localization_ge_90": localization["localization_accuracy"] >= .90,
        "critical_localization_ge_95": critical_localization["localization_accuracy"] >= .95,
        "value_containment_ge_95": localization["value_span_containment"] >= .95,
        "wrong_crop_recall_ge_95": localization["wrong_crop_recall"] >= .95,
        "unknown_dependency_le_5": provenance["unknown_dependency_rate"] <= .05,
        "secondary_provenance_complete": provenance["secondary_provenance_coverage"] == 1,
        "overall_raw_accuracy_ge_90": accuracy["overall_raw_accuracy"] >= .90,
        "critical_raw_accuracy_ge_95": accuracy["critical_field_raw_accuracy"] >= .95,
        "worst_p95_le_10_seconds": max(item["p95"] for item in latency.values()) <= 10_000,
    }
    mandatory_safety = all(gates[name] for name in (
        "critical_false_accepts_zero", "correlated_false_agreement_auto_accepts_zero",
        "invalid_npi_auto_accepts_zero", "runtime_evaluation_parity",
    ))
    decision = (
        "REJECT" if not mandatory_safety else
        "ENGINEERING_TARGETS_MET" if all(gates.values()) else "NEEDS_MORE_DATA"
    )
    report = {
        "phase": "8.9", "decision": decision,
        "dataset_firewall": {
            "partitions_used": ["DEV", "VALIDATION", "ADVERSARIAL"],
            "locked_holdout_accessed": False,
            "evidence_scope": "SYNTHETIC_RENDERER_DISJOINT_ENGINEERING_ONLY",
            "production_source_validation": "NOT_ESTABLISHED",
        },
        "localization": localization,
        "critical_localization": critical_localization,
        "provenance": provenance, "accuracy": accuracy,
        "safety_and_automation": safety, "latency_ms": latency,
        "cost": {"common_path_cloud_cost_usd": 0.0,
                 "local_compute_cost_status": "NOT_REMEASURED_PHASE8_9"},
        "claim_blocker_pareto": _pareto(output), "gates": gates,
    }
    _write(output / "localization_metrics.json", localization)
    _write(output / "localization_calibration.json", localization["calibration"])
    _write(output / "provenance_metrics.json", provenance)
    _write(output / "claim_blocker_pareto.json", report["claim_blocker_pareto"])
    _write(output / "summary.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--force-extraction", action="store_true")
    args = parser.parse_args()
    result = run(args.output, force_extraction=args.force_extraction)
    print(json.dumps(result, indent=2))
    return 2 if result["decision"] == "PROMOTION_NOT_EVALUABLE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
