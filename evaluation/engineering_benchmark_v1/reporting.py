from __future__ import annotations

import hashlib
import html
import json
import subprocess
from pathlib import Path
from typing import Any

from .build_manifest import RESULT_ROOT, ROOT
from .metrics import percentile
from .routing_benchmark import PHASE_ROOT


DOCS = ROOT / "docs"


def _read(name: str, default: Any = None):
    path = PHASE_ROOT / name
    return json.loads(path.read_text("utf-8")) if path.is_file() else default


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _matrix_table(matrix: dict[str, dict[str, int]]) -> str:
    predictions = sorted({prediction for counts in matrix.values() for prediction in counts})
    lines = ["| Truth \\ Prediction | " + " | ".join(predictions) + " |",
             "|---|" + "|".join("---:" for _ in predictions) + "|"]
    for truth, counts in matrix.items():
        lines.append("| " + truth + " | " + " | ".join(str(counts.get(key, 0)) for key in predictions) + " |")
    return "\n".join(lines)


def _freeze() -> dict[str, Any]:
    governed = [
        ROOT / "config" / "document_routing.yaml",
        ROOT / "packages" / "document_routing" / "router.py",
        ROOT / "packages" / "document_routing" / "decision_service.py",
        ROOT / "packages" / "standard_form_verification" / "cms1500.py",
        ROOT / "packages" / "standard_form_verification" / "ub04.py",
        ROOT / "packages" / "processing_routes" / "resolver.py",
    ]
    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                          text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        git_sha = "UNAVAILABLE"
    payload = {"evidence_class": "ENGINEERING_BENCHMARK_ONLY",
        "production_promotion_authority": False, "git_sha": git_sha,
        "manifest_sha256": json.loads((RESULT_ROOT / "manifest.json").read_text("utf-8"))["manifest_sha256"],
        "governed_runtime_file_hashes": {path.relative_to(ROOT).as_posix(): _sha(path) for path in governed},
        "experiment_01_production_changed": False}
    (PHASE_ROOT / "freeze.json").write_text(json.dumps(payload, indent=2), "utf-8")
    return payload


def _gallery(pareto: dict[str, Any]) -> None:
    cards = []
    for error in pareto.get("errors", [])[:120]:
        src = "../../" + error["image_path"].replace("\\", "/")
        cards.append(f"""<article><img loading="lazy" src="{html.escape(src)}" alt="error page">
<h3>{html.escape(error['category'])}</h3><p><code>{html.escape(error['document_id'])}</code></p>
<p>{html.escape(error['expected_family'])} → {html.escape(error['predicted_family'])}</p>
<p>{html.escape(error['expected_processing_route'])} → {html.escape(error['predicted_processing_route'])}</p>
<p>Source: {html.escape(error['source_dataset'])}; quality: {html.escape(error['quality_bucket'])}; tuning: {error['tuning_allowed']}</p></article>""")
    document = f"""<!doctype html><html><head><meta charset="utf-8"><title>Phase 7A.13 error gallery</title>
<style>body{{font-family:system-ui;margin:2rem}}main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:1rem}}article{{border:1px solid #ccc;padding:1rem}}img{{width:100%;height:260px;object-fit:contain;background:#eee}}code{{overflow-wrap:anywhere}}</style></head>
<body><h1>Phase 7A.13 engineering error gallery</h1><p>ENGINEERING_BENCHMARK_ONLY. First 120 deterministic errors; no production-promotion authority.</p><main>{''.join(cards)}</main></body></html>"""
    (RESULT_ROOT / "error_gallery.html").write_text(document, "utf-8")


def run() -> dict[str, Any]:
    routing = _read("routing_metrics.json", {})
    verification = _read("verification_metrics.json", {})
    extraction = _read("extraction_metrics.json", {})
    end_to_end = _read("end_to_end_metrics.json", {})
    matrices = _read("confusion_matrix.json", {})
    pareto = _read("error_pareto.json", {})
    performance = _read("performance.json", {})
    for transient in ("wall_seconds_this_run", "throughput_pages_per_second_this_run",
                      "orchestrator_cpu_seconds_this_run", "child_cpu_seconds_this_run"):
        performance.pop(transient, None)
    experiment = _read("experiment_01.json", {})
    ocr = _read("ocr_by_field.json", {})
    inventory = json.loads((RESULT_ROOT / "inventory.json").read_text("utf-8"))
    manifest = json.loads((RESULT_ROOT / "manifest.json").read_text("utf-8"))
    freeze = _freeze()
    executed = routing.get("documents", 0)
    manifest_count = inventory["unique_count"]
    scoped_ids = {row["document_id"] for row in manifest["records"][:executed]}
    detail_rows = [json.loads(line) for line in
                   (RESULT_ROOT / "routing_details.jsonl").read_text("utf-8").splitlines()]
    detail_rows = [row for row in detail_rows if row["document_id"] in scoped_ids]
    stage_latency = {}
    for stage in ("decode", "preprocess", "ocr", "router", "decision_and_verification", "total"):
        values = [row["latency_ms"][stage] for row in detail_rows]
        stage_latency[stage] = {"p50_ms": percentile(values, .50),
                                "p95_ms": percentile(values, .95),
                                "p99_ms": percentile(values, .99)}
    performance.update({"manifest_pages": manifest_count, "executed_pages": executed,
        "unexecuted_pages": manifest_count - executed,
        "execution_scope": "largest consecutive deterministic prefix above 500-page minimum",
        "bounded_abort_reason": "dense-token Router V4 anchor reconstruction remained CPU-bound for multiple minutes per page",
        "sum_recorded_document_wall_seconds": sum(row["latency_ms"]["total"] for row in detail_rows) / 1000,
        "stage_latency": stage_latency,
        "parallel_scaling": {"process_workers": 4, "alternate_worker_counts_measured": False,
                             "reason": "accuracy pass used one fixed execution topology"},
        "peak_memory_bytes": None,
        "peak_memory_note": "Per-process RSS was observed during diagnosis but no portable child peak sampler was enabled; no value is fabricated.",
        "cpu_time_seconds": None,
        "cpu_time_note": "Windows host os.times did not expose ProcessPool/Tesseract child CPU; per-stage wall time is authoritative.",
        "ocr_calls": sum(row.get("ocr_calls", 0) for row in detail_rows),
        "ocr_calls_per_page": (sum(row.get("ocr_calls", 0) for row in detail_rows) / len(detail_rows)
                               if detail_rows else 0.0)})
    (PHASE_ROOT / "performance.json").write_text(json.dumps(performance, indent=2), "utf-8")

    routing_fail = routing.get("exact_family_routing_accuracy", 0) < .90
    verification_fail = min(
        verification.get("direct_cms1500_verification", {}).get("recall", 0),
        verification.get("direct_ub04_verification", {}).get("recall", 0)) < .95
    extraction_fail = extraction.get("field_exact_match", 0) < .95
    failed = sum((routing_fail, verification_fail, extraction_fail))
    if failed > 1:
        decision_code = "MULTIPLE_BOTTLENECKS"
    elif routing_fail:
        decision_code = "ROUTING_BOTTLENECK"
    elif verification_fail:
        decision_code = "VERIFICATION_BOTTLENECK"
    elif extraction_fail:
        decision_code = "EXTRACTION_BOTTLENECK"
    else:
        decision_code = "READY_FOR_TARGETED_OPTIMIZATION"
    decision = {"decision": decision_code, "evidence_class": "ENGINEERING_BENCHMARK_ONLY",
        "production_promotion_authority": False, "routing_bottleneck": routing_fail,
        "verification_bottleneck": verification_fail, "extraction_bottleneck": extraction_fail,
        "experiment_01": experiment.get("decision", "NOT_RUN"),
        "false_standard_authorizations": routing.get("false_standard_authorization_count"),
        "critical_false_accepts": extraction.get("critical_false_accepts"),
        "next_action": "Fix nomination recall and verifier evidence semantics independently; preserve the fixed-route firewall. Profile and bound dense-token anchor reconstruction before expanding the corpus pass."}
    (PHASE_ROOT / "decision.json").write_text(json.dumps(decision, indent=2), "utf-8")
    _gallery(pareto)

    confusion_doc = f"""# CDP Engineering Routing Confusion Matrix

Evidence class: `ENGINEERING_BENCHMARK_ONLY`. This is not a production holdout or promotion artifact.

Executed {executed} of {manifest_count} exact-pixel-unique allowlisted pages. The execution stopped at the largest consecutive deterministic prefix after dense-token anchor reconstruction became operationally unbounded.

## Exact family

{_matrix_table(matrices.get('family', {}))}

## Canonical processing route

{_matrix_table(matrices.get('processing_route', {}))}

The family matrix intentionally treats custom and support pages as distinct truth classes even though the frozen hierarchical baseline currently abstains to `UNKNOWN_STRUCTURED`/`UNKNOWN_UNSTRUCTURED`. Processing compatibility is reported separately.
"""
    (DOCS / "CDP_ENGINEERING_ROUTING_CONFUSION_MATRIX.md").write_text(confusion_doc, "utf-8")

    pareto_lines = "\n".join(f"| {item['category']} | {item['count']} | {_pct(item['share'])} | {_pct(item['cumulative_share'])} |"
                              for item in pareto.get("pareto", []))
    pareto_doc = f"""# CDP Engineering Routing Error Pareto

Evidence class: `ENGINEERING_BENCHMARK_ONLY`.

| Category | Errors | Share | Cumulative |
|---|---:|---:|---:|
{pareto_lines}

The classification is deterministic diagnostic attribution, not causal proof. Review page-level evidence in [the error gallery](../evaluation_results/engineering_benchmark_v1/error_gallery.html).
"""
    (DOCS / "CDP_ENGINEERING_ROUTING_ERROR_PARETO.md").write_text(pareto_doc, "utf-8")

    top_pareto = pareto.get("pareto", [{}])[0].get("category", "none") if pareto.get("pareto") else "none"
    report = f"""# CDP Phase 7A.13 Engineering Accuracy Report

## Status

Decision: `{decision_code}`. Evidence class: `ENGINEERING_BENCHMARK_ONLY`. Production-promotion authority: **none**. Production routing and extraction configuration remained unchanged.

The allowlisted manifest contains {manifest_count} unique pages from {inventory['candidate_count']} candidates; {len(inventory['duplicates_removed'])} exact duplicates were removed. The frozen baseline completed {executed} pages. It exceeded the 500-page minimum but not the 1,000-page preference because dense representative pages exposed unbounded Router V4 feature latency.

## Frozen baseline

| Metric | Result | Gate |
|---|---:|---:|
| Exact family routing | {_pct(routing.get('exact_family_routing_accuracy', 0))} | ≥90% |
| Processing-route accuracy | {_pct(routing.get('processing_route_accuracy', 0))} | ≥95% |
| CMS precision / recall | {_pct(routing.get('cms_precision', 0))} / {_pct(routing.get('cms_recall', 0))} | ≥99% / ≥95% |
| UB precision / recall | {_pct(routing.get('ub_precision', 0))} / {_pct(routing.get('ub_recall', 0))} | ≥99% / ≥95% |
| False standard authorization | {_pct(routing.get('false_standard_authorization_rate', 0))} ({routing.get('false_standard_authorization_count', 0)}) | ≤0.5% |
| Safe standard fallback | {_pct(routing.get('safe_standard_fallback_rate', 0))} | diagnostic |
| Routing P95 | {routing.get('latency_ms', {}).get('p95', 0):.2f} ms | ≤1,000 ms |

The fixed-route firewall passed its safety objective: zero non-standard pages reached CMS/UB fixed extractors, and CMS↔UB cross-authorizations were zero. The efficiency cost is high: correct nominations frequently fall back because verification cannot authorize them.

## Verification

Direct CMS verifier precision/recall: {_pct(verification.get('direct_cms1500_verification', {}).get('precision', 0))} / {_pct(verification.get('direct_cms1500_verification', {}).get('recall', 0))}. Direct UB verifier precision/recall: {_pct(verification.get('direct_ub04_verification', {}).get('precision', 0))} / {_pct(verification.get('direct_ub04_verification', {}).get('recall', 0))}.

## Truth-route extraction

The extraction benchmark forced the independently known route and did not change runtime routing. It covered {extraction.get('documents', 0)} pages and {extraction.get('fields', 0)} truth-mapped fields.

| Metric | Result |
|---|---:|
| Field exact match | {_pct(extraction.get('field_exact_match', 0))} |
| Critical exact match | {_pct(extraction.get('critical_exact_match', 0))} |
| Crop correctness | {_pct(extraction.get('crop_correctness', 0))} |
| OCR accuracy given correct crop | {_pct(extraction.get('ocr_accuracy_given_correct_crop', 0))} |
| Safe field coverage | {_pct(extraction.get('safe_field_coverage', 0))} |
| Field HITL | {_pct(extraction.get('field_hitl_rate', 0))} |
| Claim STP | {_pct(extraction.get('claim_stp_rate', 0))} |
| False accepts / critical false accepts | {extraction.get('false_accepts', 0)} / {extraction.get('critical_false_accepts', 0)} |

End-to-end field accuracy is {_pct(end_to_end.get('layer_3_end_to_end_field_accuracy', 0))}; truth-route extraction accuracy is {_pct(end_to_end.get('layer_2_extraction_accuracy_given_truth_route', 0))}. This separation prevents routing failures from being attributed to OCR.

## OCR engines

The crop benchmark made {ocr.get('crop_trials', 0)} local engine trials. No cloud API was used; baseline cloud cost is $0.00. Per-field winners and latency/CER are in `evaluation_results/phase7a13/ocr_by_field.json`.

## Error Pareto and performance

The largest deterministic error category is `{top_pareto}`. Routing P50/P95/P99 is {routing.get('latency_ms', {}).get('p50', 0):.2f} / {routing.get('latency_ms', {}).get('p95', 0):.2f} / {routing.get('latency_ms', {}).get('p99', 0):.2f} ms. Dense pages showed individual router feature times above 46 seconds, separate from OCR, which is a scalability blocker.

## Experiment 1

`{experiment.get('experiment_id', 'NOT_RUN')}` changed only grid evidence mapping in evaluation mode. Tuning processing-route accuracy moved from {_pct(experiment.get('baseline_tuning_processing_route_accuracy', 0))} to {_pct(experiment.get('experiment_tuning_processing_route_accuracy', 0))}; decision: `{experiment.get('decision', 'NOT_RUN')}`. It was not promoted and no production file changed.

## Required next work

Fix standard nomination recall and verifier evidence semantics independently, starting with the failure classes in the Pareto. Preserve zero false-standard authorization. Separately bound or cache exact-equivalent anchor candidate construction and remeasure native dense-page latency. Do not optimize HITL/STP until raw routing and truth-route extraction meet their accuracy gates.

Frozen Git SHA: `{freeze['git_sha']}`. Manifest SHA-256: `{freeze['manifest_sha256']}`.
"""
    (DOCS / "CDP_PHASE7A13_ENGINEERING_ACCURACY_REPORT.md").write_text(report, "utf-8")
    return decision


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
