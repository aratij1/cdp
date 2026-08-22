"""Replay the frozen synthetic extraction through canonical evidence decisions.

This module never re-runs or modifies extraction. It consumes recorded primary
predictions and optional measured confirmation candidates, then calls the same
EvidenceDecisionService used by workers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import statistics
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

import yaml

from evaluation.raw_error_analysis import _norm
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.domain.common import BoundingBox
from packages.evidence_decision import (
    DecisionContext,
    EvidenceDecisionService,
    FieldDisposition,
    ReferenceEvidence,
)
from packages.evidence_router import ReferenceSourceState
from packages.ocr.contracts import OCRCandidate
from evaluation.claim_stp_analysis import analyze as analyze_claim_dispositions

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evaluation_data" / "synthetic_public_v3"
DEFAULT_EXTRACTION = (
    ROOT / "evaluation_results" / "raw_accuracy_recovery" /
    "experiment_003_member_id_paddle"
)
DEFAULT_OUTPUT = ROOT / "evaluation_results" / "evidence_optimization"
ACCEPTED = {FieldDisposition.AUTO_ACCEPTED, FieldDisposition.REFERENCE_CONFIRMED}
HITL = {
    FieldDisposition.HUMAN_REVIEW_REQUIRED,
    FieldDisposition.INSUFFICIENT_EVIDENCE,
    FieldDisposition.REJECTED,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_hash(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(_sha256(path).encode())
    return digest.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def freeze_extraction_baseline(dataset: Path, extraction: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    frozen_inputs = [
        dataset / "ground_truth.json",
        dataset / "document_manifest.json",
        dataset / "asset_inventory.json",
        dataset / "provenance.json",
        ROOT / "evaluation" / "generate_public_synthetic_claims.py",
        ROOT / "evaluation" / "benchmark_synthetic_claims.py",
        ROOT / "config" / "templates" / "cms1500_v02_12.yaml",
        ROOT / "config" / "templates" / "ub04_v2014.yaml",
        ROOT / "config" / "ocr_preprocessing.yaml",
        ROOT / "config" / "ocr_field_routes.yaml",
    ]
    frozen_inputs = [path for path in frozen_inputs if path.is_file()]
    extraction_metrics = json.loads((extraction / "metrics.json").read_text(encoding="utf-8"))
    provenance = json.loads((dataset / "provenance.json").read_text(encoding="utf-8"))
    route_config = yaml.safe_load((ROOT / "config" / "ocr_field_routes.yaml").read_text("utf-8"))
    manifest = {
        "baseline_id": "EXTRACTION_BASELINE_V1",
        "qualification": "CORRECTED_SYNTHETIC_DEVELOPMENT_BENCHMARK_NOT_PRODUCTION_ACCURACY",
        "git_sha": _git("rev-parse", "HEAD"),
        "working_tree_dirty": bool(_git("status", "--porcelain")),
        "dataset_version": dataset.name,
        "dataset_hash": _combined_hash(path for path in dataset.rglob("*") if path.is_file()),
        "dataset_contract_hash": _combined_hash(
            path for path in (dataset / "ground_truth.json", dataset / "document_manifest.json")
            if path.is_file()
        ),
        "renderer_version": provenance.get("generator_contract", "legacy-v3-metadata-missing"),
        "renderer_source_hash": _sha256(ROOT / "evaluation" / "generate_public_synthetic_claims.py"),
        "template_versions": {
            "CMS1500": "cms1500_v02_12",
            "UB04": "ub04_v2014",
        },
        "roi_version": "synthetic-public-v3-document-manifest-crop-boxes",
        "ocr_provider_versions": {
            "primary_non_member": "tesseract-recorded-phase1",
            "primary_insured_id_number": "paddleocr-recorded-phase1",
        },
        "field_specific_ocr_routing": route_config,
        "preprocessing_version": "benchmark-synthetic-claims-phase1-bounded",
        "normalization_version": "field-verification-v1",
        "parser_version": "benchmark-direct-field-crop-v1",
        "registration_version": "deskew-plus-bounded-template-alignment-v1",
        "configuration_hashes": {
            path.relative_to(ROOT).as_posix(): _sha256(path) for path in frozen_inputs
        },
        "extraction_metrics": extraction_metrics,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    shutil.copy2(extraction / "metrics.json", output / "extraction_metrics.json")
    shutil.copy2(extraction / "predictions.json", output / "extraction_predictions.json")
    return manifest


def _candidate(
    row: dict, *, document_id: str, field_name: str, manifest: dict,
    variant: str,
) -> OCRCandidate:
    box = manifest[document_id]["crop_boxes"][field_name]
    width = max(box[2], 1)
    height = max(box[3], 1)
    raw_value = row.get("value", row.get("raw_value")) or ""
    engine = str(row.get("engine") or "unknown")
    digest = hashlib.sha256(
        f"{document_id}|{field_name}|{engine}|{variant}|{raw_value}".encode()
    ).hexdigest()[:24]
    return OCRCandidate(
        value=raw_value or None,
        raw_value=raw_value,
        engine=engine,
        model_name=engine,
        model_version="recorded-phase1",
        preprocessing_variant=variant,
        raw_confidence=float(row.get("confidence") or 0),
        calibrated_confidence=None,
        bounding_box=BoundingBox(
            x0=box[0], y0=box[1], x1=box[2], y1=box[3],
            image_width=width, image_height=height,
        ),
        latency_ms=float(row.get("latency_ms") or 0),
        evidence_reference=digest,
    )


def load_confirmation_rows(paths: Iterable[Path]) -> dict[tuple[str, str], list[dict]]:
    result: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for path in paths:
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
        for row in rows:
            result[(row["document_id"], row["field_name"])].append(row)
    return result


def _truth_and_predictions(dataset: Path, extraction: Path) -> tuple[list[dict], dict, dict]:
    truth = json.loads((dataset / "ground_truth.json").read_text(encoding="utf-8"))["documents"]
    manifest = json.loads((dataset / "document_manifest.json").read_text(encoding="utf-8"))
    prediction_docs = json.loads((extraction / "predictions.json").read_text(encoding="utf-8"))["documents"]
    predictions = {
        (document["document_id"], field["field_name"]): field
        for document in prediction_docs for field in document["fields"]
    }
    return truth, manifest, predictions


def _decision_row(
    *, service: EvidenceDecisionService, deterministic_service: DeterministicEvidenceService,
    document: dict, truth_field: dict, primary: dict, manifest: dict,
    claim_values: dict[str, str | None],
    confirmations: list[dict], include_e2: bool, include_e3: bool, include_e4: bool,
    include_e6: bool, oracle_e5: bool = False, oracle_e7: bool = False,
) -> dict:
    document_id, field_name = document["document_id"], truth_field["field_name"]
    candidates = [_candidate(
        primary, document_id=document_id, field_name=field_name,
        manifest=manifest, variant="production-primary-recorded",
    )]
    approved_confirmation = service.ocr_routes.get(field_name, {}).get("confirmation")
    eligible_confirmations = [
        row for row in confirmations
        if row.get("engine") != primary.get("engine")
        and (approved_confirmation is None or row.get("engine") == approved_confirmation)
    ]
    if include_e2:
        candidates.extend(
            _candidate(row, document_id=document_id, field_name=field_name,
                       manifest=manifest, variant="measured-selective-confirmation")
            for row in eligible_confirmations
        )
    if oracle_e7:
        cloud = {
            "value": truth_field["expected_raw"], "engine": "oracle-cloud-counterfactual",
            "confidence": 1.0, "latency_ms": 800,
        }
        candidates.append(_candidate(
            cloud, document_id=document_id, field_name=field_name,
            manifest=manifest, variant="ORACLE_CEILING_NOT_IMPLEMENTED",
        ))
    deterministic = deterministic_service.evaluate(
        field_name, primary.get("raw_value"), claim_values=claim_values,
    )
    policy = service.field_policy.for_field(document["form_type"], field_name)
    reference = None
    reference_state = ReferenceSourceState.DISABLED
    if oracle_e5:
        reference = ReferenceEvidence(
            value=truth_field["expected_raw"], verified=True,
            source="ORACLE_AUTHORIZED_REFERENCE_CEILING", version="counterfactual-only",
        )
        reference_state = ReferenceSourceState.AUTHORIZED
    context = DecisionContext(
        field_name=field_name,
        document_family=document["form_type"],
        criticality=policy.criticality,
        required=policy.required,
        blocks_stp=policy.blocks_stp,
        requires_review_when_unresolved=policy.requires_review_when_unresolved,
        candidates=candidates,
        deterministic_evidence=deterministic.evidence if include_e4 else set(),
        hard_validation_passed=deterministic.passed if include_e4 else False,
        registration_confidence=1.0 if include_e3 else None,
        structural_evidence_source="SYNTHETIC_CANONICAL" if include_e3 else None,
        reference=reference,
        reference_source_state=reference_state,
        cross_field_evidence=(deterministic.cross_field_evidence if include_e6 else set()),
    )
    decision = service.decide(context)
    accepted = decision.disposition in ACCEPTED
    reconciliation_selected = decision.selected_value
    selected = reconciliation_selected if accepted else primary.get("raw_value")
    candidate_correct = _norm(selected) == _norm(truth_field["expected_raw"])
    confirmation_values = [item.get("value") for item in eligible_confirmations]
    available_upstream = set()
    if any(_norm(item) == _norm(primary.get("raw_value")) for item in confirmation_values):
        available_upstream.add("E2")
    bundle = decision.evidence_bundle
    return {
        "document_id": document_id,
        "document_family": document["form_type"],
        "field_name": field_name,
        "criticality": policy.criticality.value,
        "required": policy.required,
        "blocks_stp": policy.blocks_stp,
        "requires_review_when_unresolved": policy.requires_review_when_unresolved,
        "ground_truth": truth_field["expected_raw"],
        "selected_candidate": selected,
        "reconciliation_selected_candidate": reconciliation_selected,
        "candidate_correct": candidate_correct,
        "primary_engine": primary.get("engine"),
        "secondary_candidates": [
            {key: item.get(key) for key in ("engine", "value", "confidence", "latency_ms")}
            for item in eligible_confirmations
        ],
        "engine_agreement": any(
            _norm(item) == _norm(primary.get("raw_value")) for item in confirmation_values
        ),
        "registration_evidence": 1.0 if include_e3 else None,
        "structural_evidence": "SYNTHETIC_CANONICAL" if include_e3 else None,
        "deterministic_evidence": sorted(deterministic.evidence if include_e4 else set()),
        "deterministic_status": deterministic.status.value,
        "reference_evidence": "ORACLE_CEILING_NOT_IMPLEMENTED" if oracle_e5 else "DISABLED",
        "cross_field_evidence": sorted(deterministic.cross_field_evidence if include_e6 else set()),
        "calibrated_confidence": decision.calibrated_probability,
        "calibration_status": (
            "UNCALIBRATED_V0" if "uncalibrated" in " ".join(decision.reason_codes).casefold()
            else "RAW_PROVIDER_SCORE_NOT_CORRECTNESS_PROBABILITY"
        ),
        "current_evidence_policy": bundle.policy_id if bundle else None,
        "policy_version": decision.policy_version,
        "evidence_available": decision.available_evidence,
        "evidence_missing": decision.missing_evidence,
        "review_reason": decision.reason_codes,
        "final_disposition": decision.disposition.value,
        "next_action": decision.next_action.value,
        "available_upstream_not_propagated": sorted(available_upstream),
        "candidate_ids": decision.candidate_ids,
        "evidence_bundle": bundle.model_dump(mode="json") if bundle else None,
        "base_latency_ms": float(primary.get("latency_ms") or 0),
        "confirmation_latency_ms": sum(float(item.get("latency_ms") or 0) for item in eligible_confirmations)
        if include_e2 else 0,
        "oracle_counterfactual": oracle_e5 or oracle_e7,
    }


def replay(
    *, dataset: Path, extraction: Path, confirmation_map: dict,
    include_e2: bool, include_e3: bool, include_e4: bool, include_e6: bool,
    oracle_e5: bool = False, oracle_e7: bool = False,
) -> list[dict]:
    truth, manifest, predictions = _truth_and_predictions(dataset, extraction)
    service = EvidenceDecisionService(route_mode="evaluation")
    deterministic = DeterministicEvidenceService()
    rows = []
    for document in truth:
        claim_values = {
            field["field_name"]: predictions[(document["document_id"], field["field_name"])].get("raw_value")
            for field in document["fields"]
        }
        for field in document["fields"]:
            key = (document["document_id"], field["field_name"])
            rows.append(_decision_row(
                service=service, deterministic_service=deterministic,
                document=document, truth_field=field, primary=predictions[key],
                manifest=manifest, claim_values=claim_values,
                confirmations=confirmation_map.get(key, []),
                include_e2=include_e2, include_e3=include_e3, include_e4=include_e4,
                include_e6=include_e6, oracle_e5=oracle_e5, oracle_e7=oracle_e7,
            ))
    return rows


def summarize(rows: list[dict], extraction_metrics: dict) -> dict:
    dispositions = Counter(row["final_disposition"] for row in rows)
    accepted = [row for row in rows if row["final_disposition"] in {item.value for item in ACCEPTED}]
    reviewed = [row for row in rows if row["final_disposition"] in {item.value for item in HITL}]
    unresolved_automation = [
        row for row in rows if row["final_disposition"] == FieldDisposition.ESCALATE.value
    ]
    blocking = [row for row in rows if row["blocks_stp"]]
    critical = [row for row in rows if row["criticality"] in {"C2", "C3"}]
    claims: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        claims[row["document_id"]].append(row)
    review_counts = [
        sum(item["blocks_stp"] and item["final_disposition"] not in {value.value for value in ACCEPTED}
            for item in fields)
        for fields in claims.values()
    ]
    false_accepts = [row for row in accepted if not row["candidate_correct"]]
    confirmation_latencies = [row["confirmation_latency_ms"] for row in rows]
    mean_confirmation = statistics.mean(confirmation_latencies)
    p95_confirmation = sorted(confirmation_latencies)[int(.95 * (len(rows) - 1))]
    perfect_claims = sum(all(item["candidate_correct"] for item in fields) for fields in claims.values())
    canonical_claim_rows, canonical_claim_metrics, _, _ = analyze_claim_dispositions(rows)
    return {
        "total_fields": len(rows),
        "correct_fields": sum(row["candidate_correct"] for row in rows),
        "incorrect_fields": sum(not row["candidate_correct"] for row in rows),
        "dispositions": dict(sorted(dispositions.items())),
        "safe_coverage": len(accepted) / len(rows),
        "field_hitl_rate": len(reviewed) / len(rows),
        "field_unresolved_automation_rate": len(unresolved_automation) / len(rows),
        "estimated_field_hitl_after_current_routes": (
            sum(row["final_disposition"] not in {item.value for item in ACCEPTED}
                and row["final_disposition"] != FieldDisposition.UNRESOLVED_NON_BLOCKING.value
                for row in rows) / len(rows)
        ),
        "estimated_critical_field_hitl_after_current_routes": (
            sum(row["final_disposition"] not in {item.value for item in ACCEPTED}
                and row["final_disposition"] != FieldDisposition.UNRESOLVED_NON_BLOCKING.value
                for row in critical) / len(critical)
        ),
        "critical_field_hitl_rate": (
            sum(row["final_disposition"] in {item.value for item in HITL} for row in critical) /
            len(critical)
        ),
        "blocking_field_unresolved_rate": (
            sum(row["final_disposition"] not in {item.value for item in ACCEPTED} for row in blocking) /
            len(blocking)
        ),
        "claims_with_at_least_one_review": canonical_claim_metrics["claim_hitl_count"],
        "average_review_fields_per_claim": statistics.mean(review_counts),
        "median_review_fields_per_claim": statistics.median(review_counts),
        "claim_hitl_rate": canonical_claim_metrics["claim_hitl_rate"],
        "claim_stp_rate": canonical_claim_metrics["claim_stp_rate"],
        "claim_dispositions": canonical_claim_metrics["claim_dispositions"],
        "perfect_claims": perfect_claims,
        "false_accepts": len(false_accepts),
        "critical_false_accepts": sum(
            row["criticality"] in {"C2", "C3"} for row in false_accepts
        ),
        "additional_ocr_calls": sum(bool(row["confirmation_latency_ms"]) for row in rows),
        "estimated_incremental_ocr_cost_usd": 0.0,
        "estimated_mean_latency_ms": extraction_metrics["runtime"]["mean_latency_ms"] + mean_confirmation,
        "estimated_p95_latency_ms": extraction_metrics["runtime"]["p95_latency_ms"] + p95_confirmation,
        "qualification": "SYNTHETIC_DEVELOPMENT_REPLAY_NOT_PRODUCTION_ACCURACY",
    }


def classify(row: dict) -> tuple[str, list[str]]:
    reasons = set(row["review_reason"])
    missing = set(row["evidence_missing"])
    categories = []
    if set(row["available_upstream_not_propagated"]) & missing:
        categories.append("EVIDENCE_NOT_PROPAGATED")
    if row["secondary_candidates"] and not row["engine_agreement"]:
        categories.append("CONTRADICTION")
    if not row["candidate_ids"]:
        categories.append("CANDIDATE_NOT_PERSISTED")
    if "E2" in missing:
        categories.append("MISSING_E2_INDEPENDENT_CONFIRMATION")
    if "E3" in missing:
        categories.append("MISSING_E3_STRUCTURAL_EVIDENCE")
    if "E4" in missing:
        categories.append("MISSING_E4_DETERMINISTIC_EVIDENCE")
    if "E5" in missing:
        categories.append("MISSING_E5_AUTHORITATIVE_REFERENCE")
    if "E6" in missing:
        categories.append("MISSING_E6_CROSS_FIELD_EVIDENCE")
    if "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD" in reasons:
        categories.append("CONFIDENCE_NOT_CALIBRATED")
    if any("MISSING_FIELD_EVIDENCE_POLICY" in item for item in reasons):
        categories.append("NO_FIELD_ACCEPTANCE_POLICY")
    if any("CONTRADICTION" in item or "CONFLICT" in item for item in reasons):
        categories.append("CONTRADICTION")
    if not categories:
        categories.append("TRUE_AMBIGUITY" if row["secondary_candidates"] else "OTHER")
    priority = [
        "EVIDENCE_NOT_PROPAGATED", "CANDIDATE_NOT_PERSISTED",
        "CONTRADICTION",
        "MISSING_E4_DETERMINISTIC_EVIDENCE", "MISSING_E3_STRUCTURAL_EVIDENCE",
        "MISSING_E6_CROSS_FIELD_EVIDENCE", "MISSING_E2_INDEPENDENT_CONFIRMATION",
        "MISSING_E5_AUTHORITATIVE_REFERENCE", "CONFIDENCE_NOT_CALIBRATED",
        "NO_FIELD_ACCEPTANCE_POLICY", "TRUE_AMBIGUITY", "OTHER",
    ]
    primary = next(item for item in priority if item in categories)
    return primary, categories


def write_scenario(path: Path, rows: list[dict], metrics: dict) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "dispositions.json").write_text(json.dumps({"rows": rows}, indent=2), "utf-8")
    (path / "metrics.json").write_text(json.dumps(metrics, indent=2), "utf-8")


def _pct(value: float) -> str:
    return f"{value:.2%}"


def write_pareto(path: Path, baseline_rows: list[dict], baseline_metrics: dict) -> dict:
    correct_reviewed = [
        row for row in baseline_rows
        if row["candidate_correct"] and row["final_disposition"] not in {item.value for item in ACCEPTED}
    ]
    counts: Counter[str] = Counter()
    for row in correct_reviewed:
        primary, categories = classify(row)
        row["primary_gap_category"] = primary
        row["gap_categories"] = categories
        counts[primary] += 1
    meaningful = sum(value for key, value in counts.items() if key not in {"OTHER"})
    classified_rate = meaningful / len(correct_reviewed) if correct_reviewed else 1.0
    lines = [
        "# CDP Evidence-Gap Pareto", "",
        "> Corrected synthetic development benchmark; these are not production accuracy or STP claims.", "",
        f"Correct-but-unaccepted fields: **{len(correct_reviewed)}**. Meaningful cause coverage: **{_pct(classified_rate)}**.", "",
        "| Primary cause | Fields | Share |", "|---|---:|---:|",
    ]
    for key, value in counts.most_common():
        lines.append(f"| `{key}` | {value} | {_pct(value / max(1, len(correct_reviewed)))} |")
    lines.extend([
        "", "## Baseline disposition metrics", "",
        f"- Safe coverage: {_pct(baseline_metrics['safe_coverage'])}",
        f"- Field HITL (terminal human dispositions only): {_pct(baseline_metrics['field_hitl_rate'])}",
        f"- Unresolved automation: {_pct(baseline_metrics['field_unresolved_automation_rate'])}",
        f"- Claim STP: {_pct(baseline_metrics['claim_stp_rate'])}",
        f"- False accepts: {baseline_metrics['false_accepts']}", "",
        "The machine-readable row-level audit is `evaluation_results/evidence_optimization/baseline/dispositions.json`.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"correct_but_unaccepted": len(correct_reviewed), "cause_counts": dict(counts),
            "meaningful_classification_rate": classified_rate}


def write_frontier(path: Path, scenarios: list[tuple[str, dict, str]]) -> None:
    lines = [
        "# CDP Safe-Coverage Frontier", "",
        "> Synthetic development replay. Oracle rows are upper bounds, not implemented production evidence.", "",
        "| Evidence | Safe coverage | Est. final field HITL | Unresolved automation | Est. critical HITL | Claim STP | False accepts | Extra OCR | Est. mean latency | Est. P95 | Qualification |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, metrics, qualification in scenarios:
        lines.append(
            f"| {name} | {_pct(metrics['safe_coverage'])} | {_pct(metrics['estimated_field_hitl_after_current_routes'])} | "
            f"{_pct(metrics['field_unresolved_automation_rate'])} | {_pct(metrics['estimated_critical_field_hitl_after_current_routes'])} | "
            f"{_pct(metrics['claim_stp_rate'])} | {metrics['false_accepts']} | {metrics['additional_ocr_calls']} | "
            f"{metrics['estimated_mean_latency_ms']:.1f} ms | {metrics['estimated_p95_latency_ms']:.1f} ms | {qualification} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_counterfactual(path: Path, metrics_by_name: dict[str, dict]) -> None:
    baseline = metrics_by_name["E1+E3+E4"]
    mapping = [
        ("All measured E2 propagated", "E1+E2+E3+E4", "Measured confirmation candidates; selective route candidate."),
        ("E3 fully propagated", "E1+E3", "Canonical synthetic structure only; real pages require measured registration."),
        ("Current deterministic E4", "E1+E3+E4", "Truth-blind validators currently implemented."),
        ("Currently computable E6", "E1+E3+E4+E6", "Only relationships supported by fields present in this dataset."),
        ("Authorized E5", "+E5 oracle", "Oracle ceiling; authorized datasets are currently DISABLED."),
        ("Independent E7", "+E7 oracle", "Oracle ceiling; not provider evidence or a promotion result."),
    ]
    lines = [
        "# CDP Evidence Counterfactual", "",
        "> Synthetic development analysis. E5/E7 oracle ceilings must never be read as implemented coverage.", "",
        "| Counterfactual | Safe coverage | Gain vs E1+E3+E4 | False accepts | Interpretation |",
        "|---|---:|---:|---:|---|",
    ]
    for label, key, note in mapping:
        item = metrics_by_name[key]
        lines.append(
            f"| {label} | {_pct(item['safe_coverage'])} | {_pct(item['safe_coverage'] - baseline['safe_coverage'])} | "
            f"{item['false_accepts']} | {note} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--extraction", type=Path, default=DEFAULT_EXTRACTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--confirmation", type=Path, action="append", default=[])
    parser.add_argument(
        "--replace-frozen-extraction-baseline", action="store_true",
        help="Explicitly replace EXTRACTION_BASELINE_V1; never done by a normal replay.",
    )
    args = parser.parse_args()
    confirmations = args.confirmation or [
        ROOT / "evaluation_results" / "raw_accuracy_recovery" / "ocr_by_field_member_id" / "predictions.json",
        args.output / "ocr_by_field_paddle_confirmation" / "predictions.json",
    ]
    confirmation_map = load_confirmation_rows(confirmations)
    extraction_metrics = json.loads((args.extraction / "metrics.json").read_text("utf-8"))
    extraction_baseline = args.output / "extraction_baseline_v1"
    if (
        args.replace_frozen_extraction_baseline
        or not (extraction_baseline / "manifest.json").is_file()
    ):
        freeze_extraction_baseline(args.dataset, args.extraction, extraction_baseline)
    definitions = [
        ("E1", {"include_e2": False, "include_e3": False, "include_e4": False, "include_e6": False}, "MEASURED"),
        ("E1+E3", {"include_e2": False, "include_e3": True, "include_e4": False, "include_e6": False}, "MEASURED_SYNTHETIC_STRUCTURE"),
        ("E1+E3+E4", {"include_e2": False, "include_e3": True, "include_e4": True, "include_e6": False}, "CURRENT_BASELINE"),
        ("E1+E2+E3+E4", {"include_e2": True, "include_e3": True, "include_e4": True, "include_e6": False}, "MEASURED_CONFIRMATION_COUNTERFACTUAL"),
        ("E1+E3+E4+E6", {"include_e2": False, "include_e3": True, "include_e4": True, "include_e6": True}, "CURRENTLY_COMPUTABLE"),
        ("E1+E2+E3+E4+E6", {"include_e2": True, "include_e3": True, "include_e4": True, "include_e6": True}, "MEASURED_CONFIRMATION_COUNTERFACTUAL"),
        ("+E5 oracle", {"include_e2": False, "include_e3": True, "include_e4": True, "include_e6": True, "oracle_e5": True}, "ORACLE_CEILING_NOT_IMPLEMENTED"),
        ("+E7 oracle", {"include_e2": False, "include_e3": True, "include_e4": True, "include_e6": True, "oracle_e7": True}, "ORACLE_CEILING_NOT_IMPLEMENTED"),
    ]
    scenario_outputs = []
    metrics_by_name = {}
    rows_by_name = {}
    for name, options, qualification in definitions:
        rows = replay(
            dataset=args.dataset, extraction=args.extraction,
            confirmation_map=confirmation_map, **options,
        )
        metrics = summarize(rows, extraction_metrics)
        metrics["scenario"] = name
        metrics["evidence_qualification"] = qualification
        metrics_by_name[name] = metrics
        rows_by_name[name] = rows
        scenario_outputs.append((name, metrics, qualification))
    baseline_rows = rows_by_name["E1+E3+E4"]
    baseline_metrics = metrics_by_name["E1+E3+E4"]
    baseline_metrics["safe_coverage_gain_from_E4"] = (
        baseline_metrics["safe_coverage"] - metrics_by_name["E1+E3"]["safe_coverage"]
    )
    pareto = write_pareto(ROOT / "docs" / "CDP_EVIDENCE_GAP_PARETO.md", baseline_rows, baseline_metrics)
    baseline_metrics["evidence_gap_pareto"] = pareto
    write_scenario(args.output / "baseline", baseline_rows, baseline_metrics)
    optimized_rows = rows_by_name["E1+E2+E3+E4+E6"]
    optimized_metrics = metrics_by_name["E1+E2+E3+E4+E6"]
    write_scenario(args.output / "optimized", optimized_rows, optimized_metrics)
    write_frontier(ROOT / "docs" / "CDP_SAFE_COVERAGE_FRONTIER.md", scenario_outputs)
    write_counterfactual(ROOT / "docs" / "CDP_EVIDENCE_COUNTERFACTUAL.md", metrics_by_name)
    (args.output / "frontier.json").write_text(json.dumps(metrics_by_name, indent=2), "utf-8")
    print(json.dumps({"baseline": baseline_metrics, "optimized": optimized_metrics}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
