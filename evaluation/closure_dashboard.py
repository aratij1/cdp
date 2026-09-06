"""Maintain one closure dashboard; never substitute regression scores for release truth."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluation.cdp2_comparison import legacy_and_graph, load_rows, write
from evaluation.closure_bottlenecks import decompose
from packages.candidate_reconciliation import EvidenceReconciler
from packages.claim_intelligence.document import fingerprint
from packages.claim_intelligence.normalization import normalize

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "overall_accuracy": 0.98,
    "critical_accuracy": 0.995,
    "accepted_precision": 0.995,
    "critical_accepted_precision": 0.995,
    "critical_false_accepts": 0,
    "candidate_recall_at_1": None,
    "candidate_recall_at_3": None,
    "candidate_recall_at_5": 0.98,
    "critical_candidate_recall_at_5": 0.99,
    "technical_blockers": 0,
    "evidence_blockers": None,
    "field_hitl": 0.10,
    "cdp_controlled_hitl": 0.10,
    "claim_hitl": 0.20,
    "stp": 0.80,
    "claims_distance_0": None,
    "claims_distance_1": None,
    "claims_distance_2": None,
    "claims_distance_3": None,
    "claims_distance_4_plus": None,
    "P50_ms": None,
    "P95_ms": 5000,
    "P99_ms": None,
    "throughput_pages_per_second": None,
    "ocr_calls_per_page": 1,
    "llm_calls_per_page": None,
    "paid_ai_cost_per_page": 0.001,
}


def run() -> dict:
    output = ROOT / "evaluation_results/closure"
    iteration5_path = ROOT / "docs/closure/iteration5_summary.json"
    if iteration5_path.exists():
        iteration5_report = json.loads(iteration5_path.read_text())
        write(output, "dashboard.json", iteration5_report)
        return iteration5_report
    iteration4_path = ROOT / "docs/closure/iteration4_summary.json"
    if iteration4_path.exists():
        iteration4_report = json.loads(iteration4_path.read_text())
        write(output, "dashboard.json", iteration4_report)
        return iteration4_report
    iteration3_path = ROOT / "docs/closure/iteration3_summary.json"
    if iteration3_path.exists():
        iteration3_report = json.loads(iteration3_path.read_text())
        write(output, "dashboard.json", iteration3_report)
        return iteration3_report
    if (output / "iteration2/final_candidate.json").exists():
        from evaluation.closure_iteration2_report import run as latest_report
        return latest_report()
    reference_path = (
        ROOT / "evaluation/baselines/phase8_12/inputs/source_b/policy_replay_input.jsonl"
    )
    references = {
        (r["document_id"], r["field_name"]): r["truth"]
        for r in (json.loads(line) for line in reference_path.read_text().splitlines() if line)
    }
    grouped = defaultdict(list)
    for row in load_rows(ROOT):
        grouped[row["document_id"]].append(row)
    rows, residuals = [], []
    technical = evidence = review = evidence_review = total_review = 0
    distances: Counter[str] = Counter()
    for claim, fields in grouped.items():
        legacy, _, _ = legacy_and_graph(claim, fields, EvidenceReconciler())
        distance = sum(len(f.technical_blockers) for f in legacy.fields)
        distances[str(distance) if distance < 4 else "4+"] += 1
        for f in legacy.fields:
            candidates = [c.normalized_value or c.value for c in f.candidates]
            top = normalize(f.field_name, f.canonical_value or "")[0]
            if top in candidates:
                candidates.remove(top)
                candidates.insert(0, top)
            rows.append(
                {
                    "claim_id": claim,
                    "field": f.field_name,
                    "form": legacy.form_type,
                    "criticality": "C3" if f.critical else "NONCRITICAL",
                    "truth": references[(claim, f.field_name)],
                    "candidates": candidates,
                    "top1": top,
                    "authority": "FROZEN_REGRESSION",
                    "accepted": f.accepted,
                    "authority_blocked": "AUTHORITATIVE_DATA_REQUIRED" in f.evidence_blockers,
                    "external_evidence_blocked": "EVIDENCE_REQUIRED" in f.evidence_blockers,
                }
            )
            technical += len(f.technical_blockers)
            evidence += len(f.evidence_blockers)
            review += bool(f.technical_blockers)
            evidence_review += bool(f.evidence_blockers)
            total_review += bool(f.technical_blockers or f.evidence_blockers)
            if f.technical_blockers or f.evidence_blockers:
                residuals.append(
                    {
                        "claim": fingerprint(claim),
                        "field": f.field_name,
                        "source": "FROZEN_SYNTHETIC_NO_REAL_PACKAGE_BINDING",
                        "technical_categories": list(f.technical_blockers),
                        "evidence_categories": list(f.evidence_blockers),
                        "available_evidence": "FROZEN_CANDIDATE_OBSERVATIONS",
                        "missing_evidence": [
                            "SOURCE_TOKEN_GEOMETRY",
                            "VERIFIED_SOURCE_BINDING",
                            "TRUSTED_TRUTH",
                        ],
                        "technical_gap_proven_external": False,
                        "why_not_safely_resolved": "Cannot infer missing source characters or choose between plausible alternatives from regression references",
                        "required_dependency": "Source-bound token observations and independently reviewed fields; authority for identities",
                    }
                )
    engineering = decompose(rows, scope="ENGINEERING")
    release = decompose(rows, scope="RELEASE")
    write(output, "bottlenecks_engineering.json", engineering)
    write(output, "bottlenecks_release.json", release)
    write(output, "residual_blockers.json", residuals)
    current = {k: None for k in TARGETS}
    snapshot = {
        "authority": "FROZEN_REGRESSION",
        "scope": "130_TARGET_FIELDS_NOT_COMPLETE_REAL_CLAIMS",
        "claims": len(grouped),
        "fields": len(rows),
        "technical_blockers": technical,
        "evidence_blockers": evidence,
        "cdp_controlled_review_fields": review,
        "evidence_review_fields": evidence_review,
        "total_review_fields": total_review,
        "technical_distance_distribution": dict(distances),
        "candidate_recall": engineering["summary"]["recall"],
        "critical_candidate_recall": engineering["by_dimension"]["criticality"]
        .get("C3", {})
        .get("recall"),
        "production_stp": None,
        "engineering_claims_unlocked": 0,
    }
    runtime_path = output / "fresh_perception_broader.json"
    runtime = json.loads(runtime_path.read_text()) if runtime_path.exists() else None
    status = {k: "NOT_EVALUABLE" for k in TARGETS}
    report: dict[str, Any] = {
        "project_status": "CONTINUE",
        "current": current,
        "target": TARGETS,
        "gap": {k: None for k in TARGETS},
        "status": status,
        "engineering_regression": snapshot,
        "fresh_perception": runtime,
        "release_qualification": "NOT_EVALUABLE_WITHOUT_TRUSTED_TRUTH",
        "technical_ceiling": {"accuracy": None, "hitl": None, "stp": None, "latency": None},
        "technical_ceiling_status": "NOT_PROVEN_TECHNICAL_GAPS_REMAIN",
        "production_authority": False,
        "runtime_authority": False,
        "external_dependencies": [
            "Independent source-bound review",
            "Member/provider authority",
            "Frozen-to-real package lineage",
            "GitHub write access",
        ],
        "iterations": [
            {
                "iteration": 1,
                "change": "Invert preprocessing transforms for token geometry",
                "benefit": "Known pixel boxes recovered exactly through border, scale and rotation",
                "authority": "DETERMINISTIC_GEOMETRY",
                "retained": True,
            },
            {
                "iteration": 2,
                "change": "Printed label numbers and bounded candidate alternatives",
                "benefit": "24/24 known-source fields; real DOB/charge coverage added",
                "authority": "SYNTHETIC_KNOWN_SOURCE_AND_UNLABELED_COVERAGE",
                "retained": True,
            },
            {
                "iteration": 3,
                "change": "Bounded OCR thread experiment",
                "retained": False,
                "status": "MEASURING",
            },
        ],
        "next_action": "Measure bounded recognition runtime settings and retain only exact semantic winners",
    }
    state_path = output / "iteration_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
        report.update(state)
    for key, filename in {
        "noncanonical_discovery": "noncanonical_candidate_result.json",
        "provider_syntax_comparison": "provider_syntax_comparison.json",
        "arena_safety_gate": "arena_broader_gate.json",
        "all_field_diagnostic": "all_field_candidate_diagnostic.json",
    }.items():
        path = output / filename
        if path.exists():
            payload = json.loads(path.read_text())
            report[key] = {k: v for k, v in payload.items() if k not in {"results", "fields", "by_dimension"}}
    report["candidate_probe"] = json.loads((output / "candidate_probe.json").read_text())
    report["current"].update(ocr_calls_per_page=1, llm_calls_per_page=0, paid_ai_cost_per_page=0)
    for key in ("ocr_calls_per_page", "paid_ai_cost_per_page"):
        report["status"][key] = "ON_TARGET"
        report["gap"][key] = report["target"][key] - report["current"][key]
    report["operational_metric_scope"] = (
        "Fresh local perception experiments only; excludes infrastructure costs"
    )
    write(output, "dashboard.json", report)
    text = [
        "# CDP closure status",
        "",
        "PROJECT STATUS: CONTINUE",
        "",
        "Production authority remains disabled. No closure gate is qualified.",
        "",
        "The local CDP2 commit is preserved on closure/cdp-target. Origin is ashneevai/CDP.",
        "",
        "## Current evidence",
        "",
        (
            f"Frozen regression target subset: {len(grouped)} claims / {len(rows)} fields; {technical} technical blockers, "
            f"{evidence} evidence blockers; {review} CDP-controlled review fields. These are not release scores."
        ),
        "",
        "| Field | Regression R@1 | R@3 | R@5 | Release status |",
        "|---|---:|---:|---:|---|",
    ]
    for name, item in engineering["by_dimension"]["field"].items():
        recall = item["recall"]
        text.append(
            f"| {name} | {recall['R@1']:.1%} | {recall['R@3']:.1%} | {recall['R@5']:.1%} | NOT_EVALUABLE |"
        )
    text += [
        "",
        "All production accuracy, precision, false-accept and STP values remain null.",
        "",
        "## Retained engineering changes",
        "",
        "- Inverse preprocessing geometry: recover known source boxes through borders, scaling and rotation.",
        "- Printed field-number labels: recover 24/24 controlled field cases; add structurally valid real candidates; their correctness remains unverified.",
        "- Candidate duplicates retain provenance; at most five alternatives leave the spatial extractor.",
        "",
        "## Remaining work",
        "",
        (
            "Fresh OCR recognition dominates latency. Eight threads won the broader 12-page experiment. "
            "Perception timing is not complete claim-processing latency."
        ),
        "",
        (
            "The 2,173-page corpus currently has two verified CMS1500 pages and no verified UB04 pages. "
            "Identity gates are preserved. The remaining candidate and runtime gaps are not proven external; "
            "no technical ceiling or PROJECT_CLOSED claim is justified."
        ),
        "",
        (
            "Independent review, source binding and member/provider authority remain external dependencies. "
            "The separate blind 150-page review manifest remains available under evaluation_results/cdp2."
        ),
        "",
        "Machine-readable dashboard and residual field records: evaluation_results/closure/ (untracked runtime artifacts).",
        "",
    ]
    text += ["## Closure iteration results", ""]
    for item in report["iterations"]:
        text.append(
            f"- Iteration {item['iteration']}: {item['change']}. {item.get('benefit', item.get('status', ''))}"
        )
    if "validation" in report:
        text += ["", "Validation: " + json.dumps(report["validation"], sort_keys=True), ""]
    if runtime:
        text += [
            "",
            "## Fresh perception runtime",
            "",
            ("Includes decode, preprocessing, fresh OCR, strict routing and spatial extraction. "
             "Excludes complete claim processing and model cold start; those targets remain unqualified."),
            "",
            "| Threads | Pages | P50 ms | P95 ms | P99 ms | Pages/sec |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for experiment in runtime["experiments"]:
            timing = experiment["latency"]
            text.append(
                f"| {experiment['threads']} | {len(experiment['pages'])} | "
                f"{timing['P50']:.2f} | {timing['P95']:.2f} | {timing['P99']:.2f} | "
                f"{timing['throughput_pages_per_second']:.4f} |"
            )
    text += [
        "",
        "## Exact remaining gaps",
        "",
        "- Regression Recall@5 is 76.15%, below the candidate-recall target; no real release recall is available.",
        f"- Technical blockers decreased 110 to {technical}; review fields remain {review} and engineering claim unlocks remain zero on the 130-field target subset.",
        "- The measured fresh perception P95 alone exceeds the 5-second end-to-end target.",
        "- Real package-to-claim binding and independent field review are unavailable; external identities need authority.",
        "- Technical accuracy, HITL and STP ceilings have not been established. The project is not closed.",
        "",
    ]
    text += [
        "## Latest measured engineering results", "",
        "The same 130-field subset now has technical distances 0: 0, 1: 1, 2: 9, 3: 5, 4+: 5. These are target-field distances, not complete real-claim unlocks. Evidence review remains 122/130; total review remains 122/130; CDP-controlled review remains 59/130. Real claim HITL and STP remain null.", "",
        "Noncanonical discovery: 66 alternatives on 38/100 OTHER pages, including 30 NPI alternatives. All are UNVERIFIED_DISCOVERY, outside canonical decisions. The cohort excludes every package in the blind review manifest; no labels were generated.", "",
        "CPU arena paired experiment (12 identical pages, eight threads, one worker): P50 10366.97 to 4037.25 ms; P95/P99 16375.28 to 5827.47 ms; throughput 0.1038 to 0.2487 pages/sec. Token text, geometry, confidence, candidate and identity outputs matched exactly. Peak RSS increased from 180MB to 1.40GB. Cold model load increased from 597 to 1262 ms and is excluded from these page timings. This native runtime option is default-off.", "",
        "A later repeat with the same arena and default batch size measured P50 4454.72 ms, P95/P99 8993.47 ms and throughput 0.2051 pages/sec. Observed P95 5.83-8.99 seconds does not qualify a reliable eight-second or five-second target. Complete end-to-end latency remains unevaluated. Recognition batches 3 and 12 changed evidence and were slower; neither was retained.", "",
        "The independent all-field diagnostic covers 200 frozen fields: R@1 66%, R@3/R@5 81.5%. It identifies 37 missing reference candidates, 31 ranking misses and 40 fields without a shadow structural validator. It does not replace the historical 130-field denominator or become release truth.", "",
        "Local OCR experiments made one fresh OCR call/page, zero LLM calls and zero paid AI calls. Infrastructure cost and complete processing cost/page are not measured.", "",
        "## Current architecture bottleneck", "",
        "Perception: source-token geometry and label ownership defects repaired; real extraction correctness remains unverified. Candidate generation: missing alternatives remain. Ranking: plausible name alternatives remain unresolved. Validation: provider datatype corrected; 40 all-field structural results remain unknown, not passes. Evidence: no independent source-bound truth or identity authority. Decision: fail-closed policy retained. Latency: recognition dominates and the five-second end-to-end target remains unqualified.", "",
        "## Next action executed", "",
        report["next_action"], "",
        "Git publication remains externally blocked: origin returned HTTP 403 because ashishdat lacks write access to ashneevai/CDP. Local commits are preserved on closure/cdp-target.", "",
    ]
    (ROOT / "docs/CDP_CLOSURE_STATUS.md").write_text("\n".join(text), encoding="utf-8")
    return report


if __name__ == "__main__":
    run()
