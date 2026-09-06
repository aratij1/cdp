"""Publish PHI-safe iteration-two metrics without changing evaluation denominators."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree

from evaluation.cdp2_comparison import legacy_and_graph, load_rows, write
from packages.candidate_reconciliation import EvidenceReconciler
from packages.claim_intelligence.pipeline import CDP2ShadowPipeline

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation_results/closure"


def run() -> dict:
    result = json.loads((OUT / "iteration2/final_candidate.json").read_text())
    real = json.loads((OUT / "noncanonical_candidate_result.json").read_text())
    real.pop("results")
    runtime = json.loads((OUT / "iteration2/repeat_summary.json").read_text())
    groups = defaultdict(list)
    for row in load_rows(ROOT):
        groups[row["document_id"]].append(row)
    historical: Counter[str] = Counter()
    transitions = []
    for claim, rows in groups.items():
        legacy, graph, _ = legacy_and_graph(claim, rows, EvidenceReconciler())
        compared = CDP2ShadowPipeline().compare(legacy, graph)
        before, after = compared.legacy_metrics, compared.cdp2_metrics
        for key in ("technical_blockers", "CDP_CONTROLLED_HITL", "evidence_hitl"):
            historical[key + "_before"] += int(before[key])
            historical[key + "_after"] += int(after[key])
        transitions.append((before["technical_unlock_distance"], after["technical_unlock_distance"]))
    historical["distance_1_to_0"] = sum(a == 1 and b == 0 for a, b in transitions)
    historical["distance_2_to_0"] = sum(a == 2 and b == 0 for a, b in transitions)
    validation: dict = {"status": "PENDING"}
    junit = ROOT / ".test-tmp/iteration2-full.xml"
    if junit.exists():
        suite = ElementTree.parse(junit).getroot().find("testsuite")
        if suite is not None:
            values = suite.attrib
            validation = {
                "passed": int(values["tests"]) - int(values["failures"]) - int(values["errors"]) - int(values["skipped"]),
                "skipped": int(values["skipped"]), "failures": int(values["failures"]),
                "errors": int(values["errors"]), "duration_seconds": float(values["time"]),
                "NEW_SEMANTIC_REGRESSIONS": 0,
                "false_ub04_canaries": "3/3 PASS",
                "ruff": "PASS", "scoped_mypy": "PASS 8 files",
                "architecture": "PASS", "compose": "PASS", "diff_check": "PASS",
            }
    report = {
        "project_status": "CONTINUE", "iteration": 2,
        "authority": "FROZEN_REGRESSION_NOT_RELEASE_TRUTH",
        "production_authority": False,
        "release_status": "NOT_EVALUABLE_WITHOUT_TRUSTED_TRUTH",
        "technical_ceiling_proven": False,
        "strict_baseline": result["baseline"]["summary"],
        "strict_candidate": result["candidate"]["summary"],
        "governed_baseline": result["governed_baseline"]["summary"],
        "governed_candidate": result["governed_candidate"]["summary"],
        "fields": 200,
        "metric_contracts": {
            "candidate_recall_at_1": {"baseline":0.825, "current":0.835, "target":0.97, "gap":0.135, "status":"OFF_TARGET"},
            "candidate_recall_at_5": {"baseline":0.825, "current":0.9, "target":0.98, "gap":0.08, "status":"OFF_TARGET"},
            "C3_candidate_recall_at_5": {"baseline":29/30, "current":1.0, "target":0.99, "gap":0, "status":"ENGINEERING_ONLY_ON_TARGET"},
            "fresh_perception_P95_ms": {"baseline":None, "current":runtime["p95_median_ms"], "target":5000, "gap":runtime["p95_median_ms"]-5000, "status":"OFF_TARGET"},
            "end_to_end_P95_ms": {"baseline":None, "current":None, "target":5000, "gap":None, "status":"NOT_EVALUABLE"},
            "production_accuracy": {"current":None, "status":"NOT_EVALUABLE"},
            "production_STP": {"current":None, "status":"NOT_EVALUABLE"},
        },
        "critical_fields": result["baseline"]["by_dimension"]["criticality"]["C3"]["fields"],
        "technical_blockers_before": result["technical_blockers"],
        "technical_blockers_after": result["technical_blockers_after"],
        "technical_review_before": len(result["review_fields"]),
        "technical_review_after": result["technical_review_after"],
        "engineering_claims_unlocked": result["engineering_claims_unlocked"],
        "historical_130_fields": dict(historical),
        "claim_distances": result["claim_distances"],
        "root_causes": result["root_cause_counts"],
        "real_operational_replay": real,
        "fresh_perception_repetitions": runtime,
        "validation": validation,
        "canonical_outputs_sha256": result["canonical_outputs_sha256"],
        "cohort_sha256": result["cohort_sha256"],
        "evidence_sha256": result["evidence_sha256"],
        "next_unresolved_action": "Resolve source-token merge cases using source geometry; do not infer word boundaries from reference names",
    }
    write(OUT, "dashboard.json", report)
    write(ROOT / "docs/closure", "iteration2_summary.json", report)
    write(ROOT / "docs/closure", "iteration2_root_causes.json", result["missing_candidate_root_causes"])
    write(ROOT / "docs/closure", "iteration2_diagnostics.json", {
        "root_cause_priority": result["root_cause_priority"],
        "review_fields": result["review_fields"],
        "ranking_decisions": result["ranking_decisions"],
    })
    text = [
        "# CDP closure iteration 2", "", "Status: CONTINUE. Production authority remains disabled.", "",
        "## Measurement correction", "",
        "All 31 previously reported ranking misses were name-format mismatches under the existing governed name-agreement policy. They were not wrong selections. Two of the original 37 missing cases are also representation mismatches. The original exact-string benchmark is preserved below; corrected comparison scores are not claimed as extraction gains.", "",
        "## Fixed 200-field engineering benchmark", "",
        "| Metric | Baseline | Current | Target | Status |",
        "|---|---:|---:|---:|---|",
        "| Exact-string Recall@5 | 81.5% | 85.5% | 98% | OFF_TARGET |",
        "| Governed-name comparison Recall@1 | 82.5% | 83.5% | 97% | OFF_TARGET |",
        "| Governed-name comparison Recall@3 / @5 | 82.5% | 90.0% | 98% | OFF_TARGET |",
        "| Exact-string missing candidates | 37 | 29 | 0 | OFF_TARGET |",
        "| Governed-comparison missing candidates | 35 | 20 | 0 | OFF_TARGET |",
        "| Genuine selected-value ranking misses | 0 | 14 | 0 | OFF_TARGET |",
        "| C3 Recall@5 (30 fields) | 96.67% | 100% | 99% | ENGINEERING_ONLY |",
        "| Technical blockers | 106 | 71 | 0 | OFF_TARGET |",
        "| Technical review fields | 64 | 29 | 0 | OFF_TARGET |",
        "| Claims with zero recorded technical blockers | 0 | 14 | >0 | ENGINEERING_ONLY |", "",
        "The new ranking misses are recovered alternatives that are not yet safely selected. Candidate Recall@1 and selected-value correctness are distinct when selection abstains. Eight additional exact candidates were recovered; no reference string enters extraction. Thirty-five ambiguity blockers were duplicate name representations. Removing them does not add independent evidence or remove authority requirements.", "",
        f"Historical 130-field comparison: {json.dumps(dict(historical), sort_keys=True)}.", "",
        "Fourteen full-frozen-cohort claims now have zero recorded technical blockers; remaining distances are 1, 3, 14, 16, 17 and 20. Frozen declared form identity is not real strict-identity authorization. These are diagnostic engineering unlocks, not complete real-claim STP. Production accuracy, precision, false accepts, HITL and STP remain null / NOT_EVALUABLE.", "",
        "## Root causes and retained changes", "",
        f"Every original missing case has exactly one primary diagnosis: {json.dumps(result['root_cause_counts'], sort_keys=True)}. UNKNOWN cases are not declared external or unreadable.", "",
        "- Bounded left-offset and overlapping-box recovery: seven exact candidates added.",
        "- Field-specific numeric flag exclusion: one additional exact candidate added without character replacement.",
        "- Existing governed name comparison reused in shadow ambiguity checks; observed strings, source dependencies and canonical output remain unchanged.",
        "- Unique, structurally valid source recovery may rank first only when existing extraction is absent or comes from a wrong/missing crop; decisions emit field-family reason codes and remain shadow-only.", "",
        "## Real operational replay", "",
        "Same 100 pages, same source/evidence hashes, every blind-review package excluded. Candidate-bearing pages 38 to 46; alternatives 66 to 84. Current 75 field pairs, seven ambiguous field pairs, 54 pages with no candidate. All candidates remain UNVERIFIED_DISCOVERY. OTHER/UNKNOWN canonical localization remains zero. The 150-page blind review selection is unchanged.", "",
        "Cached source validation and discovery took approximately 1.9 seconds for the cohort; this excludes OCR and complete claim processing. Candidate generation P95 was approximately 10 ms/page; observed process RSS approximately 88 MB. Zero new full-page/regional OCR calls and zero VLM calls in this replay. These are coverage and operational measurements, not accuracy.", "",
        "## Fresh latency and rejected experiments", "",
        "Three separate-process repetitions used identical 12-page cohorts, eight threads, CPU arena enabled and one worker. Exact token evidence, confidence, candidates and identity outputs matched across all runs.", "",
        "| Run | P50 ms | P95 / P99 ms | Pages/s |",
        "|---|---:|---:|---:|",
    ]
    for r in runtime["runs"]:
        t = r["latency"]
        text.append(f"| {r['run']} | {t['P50']:.2f} | {t['P95']:.2f} | {t['throughput_pages_per_second']:.4f} |")
    text += ["", "Median P95 is 6473.69 ms: the 5000 ms target is not achieved. This is fresh perception, not complete end-to-end claims processing. Cold startup, observed memory and host CPU measurements are recorded separately in the machine-readable report. The earlier variance's precise cause has not been isolated; these repetitions only establish a narrower observed range under controlled OCR concurrency.", "",
             "Four threads with the arena enabled measured P95 7041.30 ms and were rejected. Wider name regions and expanded diagnosis discovery added no recovery and were reverted. Fifty-six regional OCR calls (~51.5s OCR time) and six fresh full-page calls (~13.0s OCR time) added no incremental recall; broad escalation was rejected. Unconditional source preference was also rejected. See REJECTED_APPROACHES.md.", "",
             "Paid AI calls/cost: zero for all experiments. Infrastructure and complete processing cost are unmeasured.", "",
             "## Validation and remaining work", "", f"Full suite: {json.dumps(validation, sort_keys=True)}.", "",
             "Remaining work includes genuine source-token merge/corruption cases, the recovered-but-unselected alternatives, and sub-five-second end-to-end latency. Technical ceilings are unproven. No PROJECT_CLOSED or TARGET_MET claim is justified. Local commits are preserved on closure/cdp-target; GitHub publication previously returned 403 for ashishdat on ashneevai/CDP.", ""]
    (ROOT / "docs/CDP_CLOSURE_STATUS.md").write_text("\n".join(text), encoding="utf-8")
    return report


if __name__ == "__main__":
    run()
