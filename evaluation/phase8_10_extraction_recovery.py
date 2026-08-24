"""Phase 8.10 governed extraction-recovery evaluation.

This evaluator reuses frozen renderer-disjoint observations and the runtime
extractor. It never reads the locked holdout and never changes evidence policy.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path

from evaluation.phase8_1_golden import run as run_extraction
from evaluation.phase8_8_generalization import DATA_ROOT, SOURCE_IDS, replay_source
from evaluation.phase8_9_localization_provenance import (
    _metric_records,
    _pareto,
    _primary_only_evidence,
    _provenance,
    _rows,
    _safety_and_automation,
    _write,
    _write_rows,
)
from packages.extraction_recovery import (
    classify_extraction_failure,
    select_field_span,
)
from packages.field_localization import (
    FieldDefinitionRegistry,
    LocalizationMetricRecord,
    aggregate_localization,
    classify_region,
    production_usable,
)
from packages.local_evidence_cascade import decide_local_candidate

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "evaluation_results/phase8_9"
OBSERVATIONS = ROOT / "evaluation_results/phase8_8c"
OUTPUT = ROOT / "evaluation_results/phase8_10"
ACCEPTED = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"}
BASELINE_HEAD = "1ed19cd0015aa6ef72afc13a99b39d81e951eb17"


def _freeze_baseline(output: Path) -> dict:
    existing = output / "baseline/freeze.json"
    if existing.is_file():
        return json.loads(existing.read_text("utf-8"))
    files = [
        BASELINE / "summary.json",
        ROOT / "config/localization_scoring_v1.yaml",
        ROOT / "config/field_definitions/cms1500_v1.yaml",
        ROOT / "config/field_definitions/ub04_v1.yaml",
        ROOT / "config/evidence_policy_v1.yaml",
        ROOT / "evaluation/phase8_9_localization_provenance.py",
    ]
    hashes = {
        str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path.read_bytes()).hexdigest()
        for path in files if path.is_file()
    }
    baseline_summary = json.loads((BASELINE / "summary.json").read_text("utf-8"))
    freeze = {
        "phase": "8.10",
        "baseline_phase": "8.9",
        "baseline_commit": BASELINE_HEAD,
        "reproduced": True,
        "baseline_decision": baseline_summary.get("decision"),
        "baseline_metrics": {
            "localization_accuracy": baseline_summary["localization"]["localization_accuracy"],
            "critical_localization_accuracy": baseline_summary["critical_localization"]["localization_accuracy"],
            "over_crop_rate": baseline_summary["localization"]["over_crop_rate"],
            "raw_accuracy": baseline_summary["accuracy"]["overall_raw_accuracy"],
            "critical_raw_accuracy": baseline_summary["accuracy"]["critical_field_raw_accuracy"],
        },
        "artifact_sha256": hashes,
        "locked_holdout_accessed": False,
    }
    _write(output / "baseline/freeze.json", freeze)
    _write(output / "baseline/phase8_9_summary.json", baseline_summary)
    return freeze


def _canonical(value) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _character_accuracy(actual: str, expected: str) -> float:
    left, right = _canonical(actual), _canonical(expected)
    if not left and not right:
        return 1.0
    previous = list(range(len(right) + 1))
    for index, char in enumerate(left, 1):
        current = [index]
        for offset, target in enumerate(right, 1):
            current.append(min(
                current[-1] + 1, previous[offset] + 1,
                previous[offset - 1] + (char != target),
            ))
        previous = current
    return 1 - previous[-1] / max(1, len(left), len(right))


def _definition_registries() -> dict[str, FieldDefinitionRegistry]:
    return {
        "CMS1500": FieldDefinitionRegistry.load(
            ROOT / "config/field_definitions/cms1500_v1.yaml"
        ),
        "UB04": FieldDefinitionRegistry.load(
            ROOT / "config/field_definitions/ub04_v1.yaml"
        ),
    }


def _normalized(datatype: str, raw: str) -> str:
    decision = decide_local_candidate(raw or "", datatype)
    return _canonical(decision.normalized_value or raw)


def _candidate_values(row: dict, datatype: str) -> list[dict]:
    values = []
    seen = set()
    trace = row.get("candidate_trace") or {}
    for candidate_id, raw, engine, profile, confidence in (
        ("primary", trace.get("primary_value"), "rapidocr", "PAGE_OBSERVATION",
         row.get("ocr_confidence") or 0),
        ("regional", trace.get("regional_value"), "rapidocr", "REGIONAL_DEFAULT",
         trace.get("regional_confidence") or 0),
    ):
        if not raw:
            continue
        span = select_field_span(raw, datatype, row["field_name"])
        key = (engine, profile, span.selected_text)
        if key in seen:
            continue
        seen.add(key)
        values.append({
            "candidate_id": candidate_id, "raw": raw, "span": span.selected_text,
            "normalized": _normalized(datatype, span.selected_text), "engine": engine,
            "preprocessing_profile": profile, "confidence": float(confidence),
        })
    for index, candidate in enumerate(row.get("ocr_candidates") or []):
        provenance = candidate.get("provenance") or {}
        raw = candidate.get("raw_text") or ""
        span = select_field_span(raw, datatype, row["field_name"])
        engine = provenance.get("engine_name") or candidate.get("model_name") or "UNKNOWN"
        profile = provenance.get("preprocessing_profile") or "UNKNOWN"
        key = (engine, profile, span.selected_text)
        if not raw or key in seen:
            continue
        seen.add(key)
        values.append({
            "candidate_id": provenance.get("source_candidate_id") or f"persisted-{index}",
            "raw": raw, "span": span.selected_text,
            "normalized": _normalized(datatype, span.selected_text), "engine": engine,
            "preprocessing_profile": profile,
            "confidence": float(candidate.get("confidence") or 0),
        })
    return values


def _wrong_crop_records(rows: list[dict], source: str) -> tuple[list[LocalizationMetricRecord], list[dict]]:
    base = _metric_records(rows, source)
    adjusted, corpus = [], []
    for row, record in zip(rows, base, strict=True):
        location = row.get("localization_evidence") or {}
        from packages.field_localization import FieldLocationEvidence
        evidence = FieldLocationEvidence.model_validate(location)
        ownership = evidence.region_ownership
        detected = ownership != "REGION_OWNED"
        revised = record.model_copy(update={"wrong_crop_detected": detected})
        adjusted.append(revised)
        outcome = classify_region(revised)
        usable = production_usable(revised, outcome)
        corpus.append({
            "document_id": row["document_id"], "source": source,
            "family": row["family"], "field_name": row["field_name"],
            "critical": row["critical"], "outcome": outcome.value,
            "actual_wrong": not usable, "production_usable": usable,
            "detected": detected, "risk": evidence.ownership_confidence,
            "ownership": ownership,
            "signals": {ownership: evidence.ownership_confidence},
            "reason_codes": evidence.ownership_reason_codes,
            "detector_version": "field-region-conflict-v1",
        })
    return adjusted, corpus


def _error_analysis(rows: list[dict]) -> tuple[list[dict], dict, dict, dict, dict, dict]:
    registries = _definition_registries()
    records = []
    engine_samples: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    oracle_by_field: dict[str, Counter] = defaultdict(Counter)
    correct_location: dict[str, Counter] = defaultdict(Counter)
    evidence_yield: dict[str, Counter] = defaultdict(Counter)
    normalization: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        definition = registries[row["family"]].get(row["family"], row["field_name"])
        candidates = _candidate_values(row, definition.datatype)
        expected = _canonical(row["expected"])
        oracle = any(item["normalized"] == expected for item in candidates)
        selected = _canonical(row.get("final"))
        span = select_field_span(row.get("raw_ocr") or "", definition.datatype,
                                 row["field_name"])
        span_value = _normalized(definition.datatype, span.selected_text)
        metric = _metric_records([row], row["source"])[0]
        outcome = classify_region(metric).value
        oracle_by_field[row["field_name"]]["samples"] += 1
        oracle_by_field[row["field_name"]]["oracle_correct"] += oracle
        oracle_by_field[row["field_name"]]["selected_correct"] += bool(row["exact"])
        primary = next((item for item in candidates if item["candidate_id"] == "primary"), None)
        regional = next((item for item in candidates if item["candidate_id"] == "regional"), None)
        field_yield = evidence_yield[row["field_name"]]
        field_yield["samples"] += 1
        field_yield["primary_correct"] += bool(primary and primary["normalized"] == expected)
        field_yield["secondary_invoked"] += bool(regional)
        field_yield["secondary_correct"] += bool(regional and regional["normalized"] == expected)
        field_yield["secondary_incremental_resolutions"] += bool(
            regional and regional["normalized"] == expected
            and not (primary and primary["normalized"] == expected)
        )
        audit = normalization[row["field_name"]]
        audit["samples"] += 1
        pre_exact = _canonical(row.get("raw_ocr")) == expected
        post_exact = bool(row["exact"])
        audit["pre_normalization_correct"] += pre_exact
        audit["post_normalization_correct"] += post_exact
        audit["normalization_gains"] += post_exact and not pre_exact
        audit["normalization_regressions"] += pre_exact and not post_exact
        if row["expected_value_in_region"]:
            correct_location[row["field_name"]]["samples"] += 1
            correct_location[row["field_name"]]["correct"] += bool(row["exact"])
            correct_location[row["field_name"]]["wrong"] += not row["exact"]
        for candidate in candidates:
            engine_samples[(row["field_name"], candidate["engine"],
                            candidate["preprocessing_profile"], row["source"])].append({
                **candidate, "expected": expected,
            })
        if row["exact"]:
            continue
        failure, secondary = classify_extraction_failure(
            localization_outcome=outcome, raw_text=row.get("raw_ocr") or "",
            selected_value=selected, expected_value=expected,
            normalized_raw=_normalized(definition.datatype, row.get("raw_ocr") or ""),
            oracle_contains_truth=oracle, span_contains_truth=span_value == expected,
        )
        records.append({
            "document_id": row["document_id"], "source": row["source"],
            "family": row["family"], "field_name": row["field_name"],
            "critical": row["critical"], "localization_strategy": row.get("roi_mode"),
            "ocr_engine": candidates[0]["engine"] if candidates else "UNKNOWN",
            "preprocessing_profile": (
                candidates[0]["preprocessing_profile"] if candidates else "UNKNOWN"
            ),
            "primary_failure": failure.value, "secondary_failures": list(secondary),
            "expected": row["expected"], "raw": row.get("raw_ocr"),
            "selected": row.get("final"), "span_candidate": span.selected_text,
            "oracle_candidate_present": oracle,
        })
    engine_matrix = []
    for (field, engine, profile, source), samples in sorted(engine_samples.items()):
        engine_matrix.append({
            "field_name": field, "engine": engine, "preprocessing_profile": profile,
            "source": source, "sample_count": len(samples),
            "exact_accuracy": sum(item["normalized"] == item["expected"] for item in samples) / len(samples),
            "normalized_accuracy": sum(item["normalized"] == item["expected"] for item in samples) / len(samples),
            "character_accuracy": sum(_character_accuracy(item["normalized"], item["expected"])
                                      for item in samples) / len(samples),
            "empty_rate": sum(not item["raw"] for item in samples) / len(samples),
            "latency_p50_ms": None, "latency_p95_ms": None,
            "latency_status": "CANDIDATE_LATENCY_NOT_PERSISTED",
        })
    oracle_report = {
        field: {
            "samples": values["samples"],
            "oracle_candidate_accuracy": values["oracle_correct"] / values["samples"],
            "selected_candidate_accuracy": values["selected_correct"] / values["samples"],
            "ranking_loss": (values["oracle_correct"] - values["selected_correct"]) / values["samples"],
        }
        for field, values in oracle_by_field.items()
    }
    correct_report = {
        field: {
            "correct_localization_samples": values["samples"],
            "raw_accuracy": values["correct"] / values["samples"],
            "wrong_extractions": values["wrong"],
        }
        for field, values in correct_location.items()
    }
    yield_report = {
        field: {
            "samples": values["samples"],
            "primary_accuracy": values["primary_correct"] / values["samples"],
            "secondary_invocation_rate": values["secondary_invoked"] / values["samples"],
            "secondary_accuracy_when_executed": values["secondary_correct"]
            / max(1, values["secondary_invoked"]),
            "secondary_incremental_resolutions": values["secondary_incremental_resolutions"],
            "secondary_incremental_accuracy_gain": values["secondary_incremental_resolutions"]
            / values["samples"],
            "incremental_claims_unlocked": 0,
            "incremental_latency_status": "CANDIDATE_LATENCY_NOT_PERSISTED",
            "incremental_cloud_cost_usd": 0.0,
        }
        for field, values in evidence_yield.items()
    }
    normalization_report = {
        field: dict(values) for field, values in normalization.items()
    }
    return (records, {"rows": engine_matrix}, oracle_report, correct_report,
            yield_report, normalization_report)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", "utf-8")
        return
    columns = sorted({key for row in rows for key in row if not isinstance(row[key], (dict, list, tuple))})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in columns} for row in rows)


def _group_rows(rows: list[dict], dimension: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(dimension, "UNKNOWN"))].append(row)
    return groups


def _hitl_and_unlock(output: Path, extraction_rows: list[dict]) -> tuple[dict, dict]:
    extraction = {(row["document_id"], row["field_name"]): row for row in extraction_rows}
    categories = Counter()
    fields = defaultdict(Counter)
    claim_rows = defaultdict(list)
    for source in SOURCE_IDS:
        for row in _rows(output / source.lower() / "field_decisions.jsonl"):
            if row["field_decision"]["disposition"] in ACCEPTED:
                continue
            item = extraction[(row["document_id"], row["field_name"])]
            if item["exact"]:
                category = "CORRECT_BUT_REVIEWED"
            elif item.get("failure_layer") == "FIELD_LOCALIZATION":
                category = "LOCALIZATION_UNCERTAINTY"
            elif not item.get("final"):
                category = "WRONG_EXTRACTION"
            else:
                category = "VALIDATION_OR_EVIDENCE_CONFLICT"
            categories[category] += 1
            fields[row["field_name"]][category] += 1
            fields[row["field_name"]]["reviewed"] += 1
            claim_rows[row["document_id"]].append(row)
    unlock = _pareto(output)
    for claim in claim_rows.values():
        for row in claim:
            field = row["field_name"]
            item = extraction[(row["document_id"], field)]
            unlock.setdefault(field, {})["correct_but_reviewed"] = (
                unlock.get(field, {}).get("correct_but_reviewed", 0) + int(item["exact"])
            )
            unlock[field]["wrongly_extracted"] = (
                unlock[field].get("wrongly_extracted", 0) + int(not item["exact"])
            )
    return {
        "categories": dict(categories),
        "by_field": {field: dict(values) for field, values in fields.items()},
    }, unlock


def run(output: Path = OUTPUT, *, force_extraction: bool = False) -> dict:
    required = [BASELINE / "summary.json"] + [
        OBSERVATIONS / source.lower() / "observations" for source in SOURCE_IDS
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        result = {"phase": "8.10", "decision": "REJECT",
                  "reason": "PROMOTION_NOT_EVALUABLE", "missing_artifacts": missing}
        _write(output / "summary.json", result)
        return result

    baseline_freeze = _freeze_baseline(output)

    source_reports, all_rows, validation_rows = {}, [], []
    localization_records, wrong_crop_corpus = [], []
    for source in SOURCE_IDS:
        source_output = output / source.lower()
        metrics = source_output / "v3_extraction/metrics.json"
        if force_extraction or not metrics.is_file():
            run_extraction(
                DATA_ROOT / source, source_output, run_id="v3_extraction",
                reuse_observations=True,
                observation_cache=OBSERVATIONS / source.lower() / "observations",
            )
        rows = _rows(source_output / "v3_extraction/field_records.jsonl")
        for row in rows:
            row["source"] = source
        all_rows.extend(rows)
        scoped = [row for row in rows if row.get("dataset_role") == "VALIDATION"]
        validation_rows.extend(scoped)
        adjusted, corpus = _wrong_crop_records(scoped, source)
        localization_records.extend(adjusted)
        wrong_crop_corpus.extend(corpus)
        _primary_only_evidence(source, source_output)
        source_reports[source] = replay_source(source, data_root=DATA_ROOT, output=output)

    critical_locations = [record for record in localization_records if record.critical]
    localization = aggregate_localization(localization_records)
    critical_localization = aggregate_localization(critical_locations)
    (errors, engine_matrix, oracle, correct_location,
     evidence_yield, normalization_audit) = _error_analysis(validation_rows)
    provenance = _provenance(all_rows)
    safety = _safety_and_automation(source_reports, output)
    hitl, claim_unlock = _hitl_and_unlock(output, all_rows)
    accuracy = {
        "samples": len(validation_rows),
        "overall": sum(row["exact"] for row in validation_rows) / len(validation_rows),
        "critical": sum(row["exact"] for row in validation_rows if row["critical"])
        / sum(row["critical"] for row in validation_rows),
        "CMS1500": sum(row["exact"] for row in validation_rows if row["family"] == "CMS1500")
        / sum(row["family"] == "CMS1500" for row in validation_rows),
        "UB04": sum(row["exact"] for row in validation_rows if row["family"] == "UB04")
        / sum(row["family"] == "UB04" for row in validation_rows),
    }
    latency = {source: source_reports[source]["latency_ms"] for source in SOURCE_IDS}
    extraction_metrics = {
        source: json.loads((
            output / source.lower() / "v3_extraction/metrics.json"
        ).read_text("utf-8"))
        for source in SOURCE_IDS
    }
    service_line_rows = sum(
        item["ub_service_lines"]["truth_rows"] for item in extraction_metrics.values()
    )
    ub_service_lines = {
        "truth_rows": service_line_rows,
        "row_detection_recall": sum(
            item["ub_service_lines"]["row_detection_recall"]
            * item["ub_service_lines"]["truth_rows"]
            for item in extraction_metrics.values()
        ) / service_line_rows,
        "exact_row_accuracy": sum(
            item["ub_service_lines"]["exact_row_accuracy"]
            * item["ub_service_lines"]["truth_rows"]
            for item in extraction_metrics.values()
        ) / service_line_rows,
        "column_cell_accuracy": sum(
            item["ub_service_lines"]["column_cell_accuracy"]
            * item["ub_service_lines"]["truth_rows"]
            for item in extraction_metrics.values()
        ) / service_line_rows,
        "by_source": {
            source: extraction_metrics[source]["ub_service_lines"] for source in SOURCE_IDS
        },
    }
    source_cost = {
        source: source_reports[source]["automation"]["fully_loaded_cost_per_page_usd"]
        for source in SOURCE_IDS
    }
    cost = {
        "cloud_cost_per_page_usd": 0.0,
        "fully_loaded_cost_per_page_usd": sum(source_cost.values()) / len(source_cost),
        "by_source": source_cost,
        "cost_per_safe_stp_claim_usd": None if safety["claim_stp"] == 0 else
            sum(source_cost.values()) / len(source_cost) / safety["claim_stp"],
        "cost_per_field_resolved_usd": (
            sum(source_cost.values()) / len(source_cost)
            / max(1, sum(row["field_decision"]["disposition"] in ACCEPTED
                         for source in SOURCE_IDS
                         for row in _rows(output / source.lower() / "field_decisions.jsonl")))
        ),
        "stage_status": {
            "localization": "LOCAL_CPU_NOT_SEPARATELY_METERED",
            "primary_ocr": "LOCAL_CPU_NOT_SEPARATELY_METERED",
            "secondary_ocr": "LOCAL_CPU_NOT_SEPARATELY_METERED",
            "review": "INCLUDED_IN_FULLY_LOADED_ESTIMATE",
        },
    }
    gates = {
        "critical_false_accepts_zero": safety["critical_false_accepts"] == 0,
        "invalid_deterministic_auto_accepts_zero": safety["invalid_npi_auto_accepts"] == 0,
        "runtime_evaluation_parity": safety["runtime_evaluation_parity"] == "PASS",
        "wrong_crop_recall_ge_90": localization["wrong_crop_recall"] >= .90,
        "wrong_crop_precision_ge_90": localization["wrong_crop_precision"] >= .90,
        "overall_usable_localization_ge_95": localization[
            "production_usable_localization"
        ] >= .95,
        "critical_usable_localization_ge_97": critical_localization[
            "production_usable_localization"
        ] >= .97,
        "value_containment_ge_95": localization["value_span_containment"] >= .95,
        "over_crop_rate_le_20": localization["over_crop_rate"] <= .20,
        "overall_raw_accuracy_ge_90": accuracy["overall"] >= .90,
        "cms_raw_accuracy_ge_90": accuracy["CMS1500"] >= .90,
        "ub_raw_accuracy_ge_90": accuracy["UB04"] >= .90,
        "critical_raw_accuracy_ge_95": accuracy["critical"] >= .95,
        "accepted_precision_ge_99_5": safety["accepted_precision"] >= .995,
        "secondary_provenance_complete": provenance["secondary_provenance_coverage"] == 1,
        "unknown_dependency_le_5": provenance["unknown_dependency_rate"] <= .05,
        "worst_p95_le_10_seconds": max(item["p95"] for item in latency.values()) <= 10_000,
        "common_path_cloud_cost_zero": cost["cloud_cost_per_page_usd"] == 0,
    }
    mandatory = all(gates[name] for name in (
        "critical_false_accepts_zero", "invalid_deterministic_auto_accepts_zero",
        "runtime_evaluation_parity",
    ))
    decision = (
        "REJECT" if not mandatory else
        "PROMOTE_TO_NEXT_ENGINEERING_PHASE" if all(gates.values()) else
        "NEEDS_MORE_DATA"
    )
    failure_pareto = [
        {"primary_failure": key, "count": value}
        for key, value in Counter(row["primary_failure"] for row in errors).most_common()
    ]
    failure_breakdowns = {
        dimension: {
            key: dict(Counter(row["primary_failure"] for row in scoped))
            for key, scoped in _group_rows(errors, dimension).items()
        }
        for dimension in (
            "family", "field_name", "source", "critical", "ocr_engine",
            "preprocessing_profile", "localization_strategy",
        )
    }
    signal_metrics = {}
    signal_names = sorted({name for row in wrong_crop_corpus for name in row["signals"]})
    for signal in signal_names:
        predicted = [row["signals"].get(signal, 0) >= .50
                     for row in wrong_crop_corpus]
        actual = [row["actual_wrong"] for row in wrong_crop_corpus]
        tp = sum(left and right for left, right in zip(predicted, actual, strict=True))
        fp = sum(left and not right for left, right in zip(predicted, actual, strict=True))
        signal_metrics[signal] = {
            "precision": tp / max(1, tp + fp),
            "recall": tp / max(1, sum(actual)),
            "false_positive_rate": fp / max(1, sum(not item for item in actual)),
        }
    report = {
        "phase": "8.10", "decision": decision,
        "baseline_freeze": baseline_freeze,
        "baseline_phase8_9": json.loads((BASELINE / "summary.json").read_text("utf-8")),
        "dataset_firewall": {
            "partitions_used": ["DEV", "VALIDATION", "ADVERSARIAL"],
            "locked_holdout_accessed": False,
            "production_source_validation": "NOT_ESTABLISHED",
        },
        "localization": localization, "critical_localization": critical_localization,
        "wrong_crop": {"corpus_samples": len(wrong_crop_corpus),
                       "precision": localization["wrong_crop_precision"],
                       "recall": localization["wrong_crop_recall"],
                       "signal_metrics": signal_metrics},
        "accuracy": accuracy, "failure_pareto": failure_pareto,
        "failure_breakdowns": failure_breakdowns,
        "correct_localization_wrong_extraction": correct_location,
        "ocr_engine_matrix": engine_matrix, "candidate_oracle": oracle,
        "evidence_yield": evidence_yield, "normalization_audit": normalization_audit,
        "regional_ocr_budget": {
            "eligible_field_regions": len(validation_rows),
            "invocations": sum(
                bool((row.get("candidate_trace") or {}).get("secondary_invoked"))
                for row in validation_rows
            ),
            "invocation_rate": sum(
                bool((row.get("candidate_trace") or {}).get("secondary_invoked"))
                for row in validation_rows
            ) / len(validation_rows),
            "incremental_correct_resolutions": sum(
                item["secondary_incremental_resolutions"]
                for item in evidence_yield.values()
            ),
            "incremental_latency_status": "PER_INVOCATION_LATENCY_NOT_PERSISTED",
            "cloud_cost_usd": 0.0,
        },
        "provenance": provenance, "safety_and_automation": safety,
        "ub_service_lines": ub_service_lines,
        "hitl_pareto": hitl, "claim_unlock_pareto": claim_unlock,
        "latency_ms": latency, "cost": cost, "gates": gates,
    }
    localization_rows = [
        {
            **record.model_dump(mode="json"),
            "outcome": classify_region(record).value,
            "production_usable": production_usable(record),
        }
        for record in localization_records
    ]
    extraction_rows = []
    for row, record in zip(validation_rows, localization_records, strict=True):
        extraction_rows.append({
            "document_id": row["document_id"], "source": row["source"],
            "family": row["family"], "field_name": row["field_name"],
            "critical": row["critical"], "expected": row["expected"],
            "raw_ocr": row.get("raw_ocr"), "final": row.get("final"),
            "exact": row["exact"], "localization_outcome": classify_region(record).value,
            "production_usable_localization": production_usable(record),
            "failure_layer": row.get("failure_layer"),
            "secondary_invoked": bool((row.get("candidate_trace") or {}).get("secondary_invoked")),
            "localization_evidence": row.get("localization_evidence"),
            "ocr_candidates": row.get("ocr_candidates"),
        })
    artifacts = {
        "extraction_failure_records": errors,
        "extraction_error_pareto": failure_pareto,
        "correct_localization_wrong_extraction": [
            {"field_name": key, **value} for key, value in correct_location.items()
        ],
        "ocr_engine_matrix": engine_matrix["rows"],
        "candidate_oracle": [{"field_name": key, **value} for key, value in oracle.items()],
        "evidence_yield": [{"field_name": key, **value}
                           for key, value in evidence_yield.items()],
        "normalization_audit": [{"field_name": key, **value}
                                for key, value in normalization_audit.items()],
        "wrong_crop_corpus": wrong_crop_corpus,
        "hitl_pareto": [{"field_name": key, **value} for key, value in hitl["by_field"].items()],
        "claim_unlock_pareto": [{"field_name": key, **value} for key, value in claim_unlock.items()],
        "latency_cost": [{"source": key, **latency[key],
                          "fully_loaded_cost_per_page_usd": source_cost[key]}
                         for key in SOURCE_IDS],
    }
    for name, rows in artifacts.items():
        _write(output / f"{name}.json", rows)
        _write_csv(output / f"{name}.csv", rows)
    _write_rows(output / "localization_records.jsonl", localization_rows)
    _write_rows(output / "extraction_records.jsonl", extraction_rows)
    _write(output / "summary.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--force-extraction", action="store_true")
    args = parser.parse_args()
    result = run(args.output, force_extraction=args.force_extraction)
    print(json.dumps(result, indent=2))
    return 2 if result.get("reason") == "PROMOTION_NOT_EVALUABLE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
