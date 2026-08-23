from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PIL import Image

from packages.document_routing.decision_service import DocumentRoutingDecisionService
from packages.document_routing.router import MultiSignalRoute, MultiSignalRouter
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.standard_form_verification.evidence import evidence_from_router_features
from packages.standard_form_verification.service import StandardFormVerificationService
from workers.cascade.tesseract_adapter import TesseractTextExtractor

from .build_manifest import RESULT_ROOT, ROOT, build_manifest
from .contracts import EngineeringBenchmarkRecord
from .metrics import error_pareto, summarize_routing, summarize_verification


PHASE_ROOT = ROOT / "evaluation_results" / "phase7a13"


def _direct(service: StandardFormVerificationService, family: DocumentClass, routing) -> dict[str, Any]:
    evidence = evidence_from_router_features(family, None, routing)
    result = service.verify(evidence)
    return {"status": result.status.value, "score": result.verification_score,
            "eligible_for_fixed_extractor": result.eligible_for_fixed_extractor,
            "supporting_evidence_classes": list(result.supporting_evidence_classes),
            "reason_codes": list(result.reason_codes), "policy_version": result.verification_policy_version}


def _one(record: EngineeringBenchmarkRecord) -> dict[str, Any]:
    started = time.perf_counter()
    decode_started = time.perf_counter()
    with Image.open(ROOT / record.image_path) as opened:
        image = opened.convert("L")
        image.load()
    decode_ms = (time.perf_counter() - decode_started) * 1000
    ocr_started = time.perf_counter()
    lines = TesseractTextExtractor(psm=11).extract(image)
    ocr_ms = (time.perf_counter() - ocr_started) * 1000
    router_started = time.perf_counter()
    routing = MultiSignalRouter.load().route(image, lines)
    router_ms = (time.perf_counter() - router_started) * 1000
    verifier = StandardFormVerificationService()
    direct = {family.value: _direct(verifier, family, routing)
              for family in (DocumentClass.CMS1500, DocumentClass.UB04)}
    nominated = (DocumentClass(routing.route.value)
                 if routing.route in {MultiSignalRoute.CMS1500, MultiSignalRoute.UB04} else None)
    standard_evidence = (evidence_from_router_features(nominated, None, routing)
                         if nominated is not None else None)
    decision_started = time.perf_counter()
    decision = DocumentRoutingDecisionService(verification_service=verifier).decide(
        record.document_id, record.page_id, routing, standard_evidence, evaluation_only=True)
    decision_ms = (time.perf_counter() - decision_started) * 1000
    total_ms = (time.perf_counter() - started) * 1000
    predicted_family = routing.route.value
    return {
        **record.model_dump(mode="json"),
        "predicted_family": predicted_family,
        "predicted_top_level": decision.classification.top_level_class.value,
        "predicted_taxonomy_family": decision.classification.document_family.value,
        "predicted_taxonomy_subtype": decision.classification.document_subtype.value,
        "standard_nominated": nominated.value if nominated else None,
        "standard_verification": (decision.standard_verification.model_dump(mode="json")
                                  if decision.standard_verification else None),
        "direct_verification": direct,
        "predicted_processing_route": decision.processing_route.value,
        "route_reason_codes": list(decision.route_reason_codes),
        "routing_evidence": routing.model_dump(mode="json"),
        "latency_ms": {"decode": decode_ms, "preprocess": 0.0, "ocr": ocr_ms,
                       "router": router_ms, "decision_and_verification": decision_ms,
                       "total": total_ms},
        "ocr_calls": 1, "cloud_api_calls": 0,
        "evaluation_only": True,
    }


def _load_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    rows = {}
    for line in path.read_text("utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows[row["document_id"]] = row
    return rows


def run(*, workers: int = 4, force: bool = False, limit: int | None = None) -> dict[str, Any]:
    frozen = PHASE_ROOT / "benchmark_freeze.json"
    if frozen.is_file():
        from .freeze import load_frozen_manifest
        manifest = load_frozen_manifest()
    else:
        manifest = build_manifest()
    records = manifest.records[:limit] if limit else manifest.records
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    checkpoint = RESULT_ROOT / "routing_details.jsonl"
    if force and checkpoint.exists():
        checkpoint.unlink()
    completed = _load_checkpoint(checkpoint)
    # A changed manifest invalidates partial results even if document IDs happen to overlap.
    cache_meta = RESULT_ROOT / "routing_cache_meta.json"
    if completed and (not cache_meta.is_file() or
                      json.loads(cache_meta.read_text("utf-8")).get("manifest_sha256") != manifest.manifest_sha256):
        checkpoint.unlink()
        completed = {}
    cache_meta.write_text(json.dumps({"manifest_sha256": manifest.manifest_sha256,
                                      "router_mode": "frozen-current-hierarchical-baseline",
                                      "evidence_class": manifest.evidence_class}, indent=2), "utf-8")
    pending = [record for record in records if record.document_id not in completed]
    wall_started = time.perf_counter()
    process_started = time.process_time()
    times_started = os.times()
    with checkpoint.open("a", encoding="utf-8") as stream:
        # Dense OCR token sets make Router V4's anchor reconstruction CPU-bound.
        # Processes preserve the frozen algorithm while avoiding Python thread
        # contention and mirror separately scaled production workers.
        with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(_one, record): record for record in pending}
            for index, future in enumerate(as_completed(futures), 1):
                row = future.result()
                completed[row["document_id"]] = row
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                stream.flush()
                if index % 25 == 0 or index == len(pending):
                    print(json.dumps({"completed_this_run": index, "pending_this_run": len(pending) - index,
                                      "total_cached": len(completed)}), flush=True)
    rows = [completed[record.document_id] for record in records]
    metrics, matrices = summarize_routing(rows)
    verification = summarize_verification(rows)
    pareto = error_pareto(rows)
    wall = time.perf_counter() - wall_started
    os_elapsed = os.times()
    performance = {
        "evidence_class": manifest.evidence_class, "production_promotion_authority": False,
        "documents": len(rows), "wall_seconds_this_run": wall,
        "throughput_pages_per_second_this_run": (len(pending) / wall if wall else 0.0),
        "orchestrator_cpu_seconds_this_run": time.process_time() - process_started,
        "child_cpu_seconds_this_run": ((os_elapsed.children_user + os_elapsed.children_system) -
                                         (times_started.children_user + times_started.children_system)),
        "latency_ms": metrics["latency_ms"], "cloud_api_calls": 0, "cloud_cost_usd": 0.0,
        "ocr_engine": "Tesseract 5.x PSM 11", "ocr_calls_per_page": metrics["ocr_calls_per_page"],
        "notes": ["CPU values cover only the current invocation; reused checkpoints are excluded.",
                  "Tesseract child CPU accounting depends on host OS support."],
    }
    gates = {
        "exact_family_routing_accuracy_gte_90pct": metrics["exact_family_routing_accuracy"] >= .90,
        "processing_route_accuracy_gte_95pct": metrics["processing_route_accuracy"] >= .95,
        "cms_precision_gte_99pct": metrics["cms_precision"] >= .99,
        "cms_recall_gte_95pct": metrics["cms_recall"] >= .95,
        "ub_precision_gte_99pct": metrics["ub_precision"] >= .99,
        "ub_recall_gte_95pct": metrics["ub_recall"] >= .95,
        "false_standard_authorization_lte_half_pct": metrics["false_standard_authorization_rate"] <= .005,
        "routing_p95_lte_1s": metrics["latency_ms"]["p95"] <= 1000,
    }
    metrics["gates"] = gates
    metrics["gate_pass"] = all(gates.values())
    (PHASE_ROOT / "routing_metrics.json").write_text(json.dumps(metrics, indent=2), "utf-8")
    (PHASE_ROOT / "verification_metrics.json").write_text(json.dumps(verification, indent=2), "utf-8")
    (PHASE_ROOT / "confusion_matrix.json").write_text(json.dumps(matrices, indent=2), "utf-8")
    (PHASE_ROOT / "error_pareto.json").write_text(json.dumps(pareto, indent=2), "utf-8")
    (PHASE_ROOT / "performance.json").write_text(json.dumps(performance, indent=2), "utf-8")
    return {"metrics": metrics, "verification": verification, "performance": performance,
            "error_pareto": pareto, "matrices": matrices}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    result = run(workers=args.workers, force=args.force, limit=args.limit)
    print(json.dumps({"routing_metrics": result["metrics"],
                      "verification_metrics": result["verification"],
                      "performance": result["performance"]}, indent=2))
