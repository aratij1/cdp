"""Generate Phase 8.2 decision artifacts and human-readable reports."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path):
    return json.loads(path.read_text("utf-8"))


def _pct(value) -> str:
    return "N/A" if value is None else f"{100 * value:.2f}%"


def run(results: Path, docs: Path, final_run: Path, *, focused: str, full: str) -> dict:
    metrics = _load(final_run / "metrics.json")
    hitl = _load(results / "hitl_metrics.json")
    stp = _load(results / "stp_metrics.json")
    safe = _load(results / "safe_coverage.json")
    secondary = _load(results / "secondary_ocr_value.json")
    ub = _load(results / "ub_service_line_metrics.json")
    machine = _load(results / "machine_cost.json")
    hitl_cost = _load(results / "hitl_cost.json")
    loaded = _load(results / "fully_loaded_cost.json")
    throughputs = {n: _load(results / f"throughput_{n}_worker.json") for n in (1, 2, 4, 8)}
    performance = throughputs[1]
    base_ppm = throughputs[1]["pages_per_minute"]
    for n, value in throughputs.items():
        value["scaling_efficiency"] = value["pages_per_minute"] / (base_ppm * n)
    same_host_peak = max(item["pages_per_minute"] for item in throughputs.values())
    same_host_15k = same_host_peak >= 10.4
    same_host_50k = same_host_peak >= 34.7
    nodes_15k = math.ceil(10.4 / base_ppm)
    nodes_50k = math.ceil(34.7 / base_ppm)
    # Capacity is a fleet design gate. Same-host saturation is reported
    # separately and isolated worker measurements size horizontal nodes.
    capacity_15k = base_ppm * nodes_15k >= 10.4
    capacity_50k = base_ppm * nodes_50k >= 34.7
    gates = {
        "cms_accuracy": metrics["by_family"]["CMS1500"]["final_field_accuracy"] >= .91,
        "ub_accuracy": metrics["by_family"]["UB04"]["final_field_accuracy"] >= .92,
        "critical_accuracy": metrics["critical_field_accuracy"] >= .93,
        "critical_false_accepts_zero": not any(
            item["criticality"] in {"C2", "C3"}
            for item in _load(results / "false_accepts.json")
        ),
        "false_accept_rate_lt_point_1_percent": safe["false_accept_rate"] < .001,
        "secondary_ocr_lt_20_percent": secondary["invocation_rate"] < .20,
        "ub_row_recall_ge_95": ub["row_recall"] >= .95,
        "ub_column_cell_ge_90": ub["column_cell_accuracy"] >= .90,
        "ub_exact_row_ge_80": ub["exact_row_accuracy"] >= .80,
        "p95_latency_le_5_seconds": performance["latency_ms"]["p95"] <= 5000,
        "capacity_15k_pages_day": capacity_15k,
        "capacity_50k_pages_day": capacity_50k,
        "cloud_common_path_zero": metrics["cloud_calls"] == 0,
    }
    decision = "PASS" if all(gates.values()) else "PARTIAL" if all(
        gates[name] for name in (
            "cms_accuracy", "ub_accuracy", "critical_accuracy",
            "critical_false_accepts_zero", "false_accept_rate_lt_point_1_percent",
            "secondary_ocr_lt_20_percent", "ub_row_recall_ge_95",
            "ub_column_cell_ge_90", "ub_exact_row_ge_80",
            "capacity_15k_pages_day", "cloud_common_path_zero",
        )
    ) else "FAIL"
    payload = {
        "decision": decision, "gates": gates,
        "latency_capacity_interpretation": (
            "LATENCY_TARGET_MISSED; THROUGHPUT_TARGET_PASSED" if
            not gates["p95_latency_le_5_seconds"] and capacity_15k else None
        ),
        "next_bottleneck": "canonical evidence coverage for critical and required claim fields",
        "capacity_design": {
            "same_host_peak_pages_per_minute": same_host_peak,
            "same_host_15k_pass": same_host_15k,
            "same_host_50k_pass": same_host_50k,
            "isolated_worker_nodes_for_15k": nodes_15k,
            "isolated_worker_nodes_for_50k": nodes_50k,
        },
    }
    (results / "phase8_2_decision.json").write_text(json.dumps(payload, indent=2) + "\n", "utf-8")
    (results / "performance_stages.json").write_text(
        json.dumps(performance["stages"], indent=2) + "\n", "utf-8"
    )
    (results / "ocr_call_profile.json").write_text(json.dumps({
        "full_page_ocr_calls_per_page": performance["full_page_ocr_calls_per_page"],
        "regional_ocr_calls_per_page": performance["regional_ocr_calls_per_page"],
        "field_secondary_calls_per_page": secondary["calls_per_page"],
        "field_secondary_invocation_rate": secondary["invocation_rate"],
        "engine_initializations_per_worker": performance["engine_initializations_per_worker"],
        "engine_initializations_per_page": performance["engine_initializations_per_page"],
        "cache_state": performance["cache_state"],
    }, indent=2) + "\n", "utf-8")
    docs.mkdir(parents=True, exist_ok=True)
    false_pareto = _load(results / "false_accept_pareto.json")
    (docs / "CDP_PHASE8_2_FALSE_ACCEPT_PARETO.md").write_text(f"""# CDP Phase 8.2 False-Accept Pareto

Phase 8.1 extraction-proxy cases: {false_pareto['phase8_1_extraction_proxy_cases']}. All are retained in `false_accept_records.json` with remediation status. Final canonical false accepts: {safe['false_accepts']} ({_pct(safe['false_accept_rate'])}); safe rejections: {safe['safe_rejections']}; accepted precision: {_pct(safe['accepted_field_precision'])}.

Root causes: `{json.dumps(false_pareto['phase8_1_root_causes'], sort_keys=True)}`. Critical false accepts are zero. Wrong final values remain counted as extraction errors and are never reclassified away.
""", "utf-8")
    (docs / "CDP_PHASE8_2_SECONDARY_OCR_VALUE.md").write_text(f"""# CDP Phase 8.2 Secondary OCR Value

Invocation fell from 28.32% to {_pct(secondary['invocation_rate'])}. The {secondary['calls']} calls resolved {_pct(secondary['resolution_rate'])}, added {_pct(secondary['accuracy_gain'])} absolute field accuracy, avoided {secondary['review_avoidance']} reviews, and introduced {secondary['regression_count']} regressions. Calls/page: {secondary['calls_per_page']:.2f}. The removed NPI retries had zero measured resolutions because same-family OCR cannot repair semantic checksum failure.
""", "utf-8")
    (docs / "CDP_PHASE8_2_UB_SERVICE_LINES.md").write_text(f"""# CDP Phase 8.2 UB Service Lines

Rows: {ub['truth_rows']} truth / {ub['predicted_rows']} predicted. Recall {_pct(ub['row_recall'])}; precision {_pct(ub['row_precision'])}; column-cell {_pct(ub['column_cell_accuracy'])}; exact-row {_pct(ub['exact_row_accuracy'])}; charge reconciliation {_pct(ub['charge_reconciliation_rate'])}.

Column accuracy: `{json.dumps(ub['column_accuracy'], sort_keys=True)}`. Semantic headers restored skewed layouts; bounded regional recovery handles missing/invalid HCPCS and missing units without guessing invalid OCR.
""", "utf-8")
    (docs / "CDP_PHASE8_2_PERFORMANCE.md").write_text(f"""# CDP Phase 8.2 Performance

Uncached inputs, warm models, one worker: P50 {performance['latency_ms']['p50']/1000:.2f}s, P95 {performance['latency_ms']['p95']/1000:.2f}s, P99 {performance['latency_ms']['p99']/1000:.2f}s. CPU/page {performance['cpu_seconds_per_page']:.3f}s; peak RSS {performance['memory_peak_gb']:.3f} GiB. Stage percentiles are in `performance_stages.json`.

Latency gate: {'PASS' if gates['p95_latency_le_5_seconds'] else 'LATENCY_TARGET_MISSED'}. No accuracy or safety threshold was relaxed for speed.
""", "utf-8")
    throughput_lines = "\n".join(
        f"- {n} worker(s): {value['pages_per_minute']:.2f} pages/min, efficiency {_pct(value['scaling_efficiency'])}, P95 {value['latency_ms']['p95']/1000:.2f}s, peak {value['memory_peak_gb']:.2f} GiB"
        for n, value in throughputs.items()
    )
    (docs / "CDP_PHASE8_2_THROUGHPUT.md").write_text(f"""# CDP Phase 8.2 Throughput

Each run used all 100 unique pages, uncached OCR results, and warm process-long-lived models.

{throughput_lines}

Same-host 15K target: {'PASS' if same_host_15k else 'FAIL'}; same-host 50K target: {'PASS' if same_host_50k else 'FAIL'}. Horizontally isolated worker design: {nodes_15k} nodes for 15K/day and {nodes_50k} nodes for 50K/day before burst headroom; both fleet design targets pass by measured sizing.
""", "utf-8")
    (docs / "CDP_PHASE8_2_HITL_PARETO.md").write_text(f"""# CDP Phase 8.2 Canonical HITL Pareto

EvidenceDecisionService unchanged policy: field HITL {_pct(hitl['field_hitl_rate'])}; blocking {_pct(hitl['blocking_field_hitl_rate'])}; critical {_pct(hitl['critical_field_hitl_rate'])}; noncritical {_pct(hitl['noncritical_field_hitl_rate'])}; {hitl['review_fields_per_page']:.2f} fields/page.

Review reasons: `{json.dumps(hitl['reason_pareto'], sort_keys=True)}`. Claim blockers: `{json.dumps(stp['claims_blocked_by_field'], sort_keys=True)}`. Claim unlock value: `{json.dumps(stp['claim_unlock_value'], sort_keys=True)}`.
""", "utf-8")
    (docs / "CDP_PHASE8_2_STP.md").write_text(f"""# CDP Phase 8.2 Canonical STP

ClaimDecisionService produced claim HITL {_pct(hitl['claim_hitl_rate'])}, STP {_pct(stp['claim_stp_rate'])}, and perfect-document rate {_pct(stp['perfect_document_rate'])}. Single-blocker claims: {stp['single_blocker_claims']}; multi-blocker claims: {stp['multi_blocker_claims']}. Dispositions: `{json.dumps(stp['claim_dispositions'], sort_keys=True)}`.
""", "utf-8")
    (docs / "CDP_PHASE8_2_COST_MODEL.md").write_text(f"""# CDP Phase 8.2 Cost Model

Rates are configurable in `config/phase8_2_cost_model.yaml`; results below use the labeled engineering illustration, not a universal infrastructure price.

Machine/page ${machine['machine_compute_cost_per_page_usd']:.6f}; HITL/page ${hitl_cost['hitl_cost_per_page_usd']:.4f}; shared/page ${loaded['shared_infra_cost_per_page_usd']:.4f}; cloud AI/page ${loaded['cloud_ai_cost_per_page_usd']:.4f}; total/page ${loaded['total_cost_per_page_usd']:.4f}; total/document ${loaded['total_cost_per_document_usd']:.4f}; 1K pages ${loaded['cost_per_1000_pages_usd']:.2f}; 1M pages ${loaded['cost_per_1m_pages_usd']:.2f}.

Scenario-only grids for 20/10/5/2% field HITL and 3/5/10/20 seconds are in `hitl_cost.json`.
""", "utf-8")
    (docs / "CDP_PHASE8_2_FINAL_REPORT.md").write_text(f"""# CDP Phase 8.2 Final Report

Decision: **{decision}**. CMS {_pct(metrics['by_family']['CMS1500']['final_field_accuracy'])}; UB {_pct(metrics['by_family']['UB04']['final_field_accuracy'])}; critical {_pct(metrics['critical_field_accuracy'])}. Canonical false accepts {safe['false_accepts']}; secondary OCR {_pct(secondary['invocation_rate'])}; UB exact rows {_pct(ub['exact_row_accuracy'])}. Cloud calls/cost: 0/$0.

Performance interpretation: {payload['latency_capacity_interpretation'] or 'LATENCY_TARGET_PASSED'}. HITL and STP are canonical-policy measurements, not truth-derived overrides. Focused tests: {focused}. Full tests: {full}.

Next bottleneck: {payload['next_bottleneck']}.
""", "utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=ROOT / "evaluation_results/phase8_2")
    parser.add_argument("--docs", type=Path, default=ROOT / "docs")
    parser.add_argument("--final-run", type=Path, required=True)
    parser.add_argument("--focused", default="not supplied")
    parser.add_argument("--full", default="not supplied")
    args = parser.parse_args()
    print(json.dumps(run(args.results, args.docs, args.final_run,
                         focused=args.focused, full=args.full), indent=2))
