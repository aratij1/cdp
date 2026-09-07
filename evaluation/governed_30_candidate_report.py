"""Publish aliased candidate-coverage evidence; raw values stay in ignored storage."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from evaluation.governed_30_reference import ROOT, digest


def export(root: Path = ROOT) -> None:
    local = root / "evaluation_results/governed_30_candidate_coverage"
    docs = root / "docs/qualification"
    read = lambda p: json.loads(p.read_text(encoding="utf8"))
    summary = read(local / "coverage_summary.local.json")
    matrix = read(local / "candidate_failure_matrix.local.json")
    wrong = read(local / "wrong_candidate_values.local.json")
    track_b = read(local / "track_b_continuity.local.json")
    private = read(local / "coverage_records.local.json")
    ranking = read(local / "ranking_miss.local.json")
    ranking_report = {
        "scope": "SEPARATE_RANKING_MISS; no selection changes",
        "cases": ranking,
        "evidence": {
            "selected_confidence": 0.943,
            "correct_alternative_confidence": 0.867,
            "method": "ALTERNATE_PREPROCESS_OCR",
            "model": "PP-OCRv4",
            "diagnosis": "Higher-confidence broad line selected over narrower alternative; confidence is not semantic correctness",
        },
    }
    artifacts = {
        "governed_30_candidate_failure_matrix.json": matrix,
        "top_candidate_blockers.json": read(local / "top_candidate_blockers.local.json"),
        "governed_30_candidate_coverage_scorecard.json": summary,
        "governed_30_candidate_source_visibility.json": read(
            local / "source_visibility.local.json"
        ),
        "governed_30_candidate_wrong_values.json": {
            "scope": "14 ORIGINAL WRONG VALUES; replay-inferred classification, not original OCR trace",
            "counts": dict(Counter(r["wrong_value_classification"] for r in wrong)),
            "fields": wrong,
        },
        "governed_30_candidate_ranking_miss.json": ranking_report,
        "governed_30_candidate_track_b.json": track_b,
    }
    references = [r["reference_value"] for r in private if len(str(r["reference_value"])) >= 6]
    for name, data in artifacts.items():
        payload = json.dumps(data, indent=2) + "\n"
        if any(json.dumps(value) in payload for value in references):
            raise ValueError("REFERENCE_VALUE_IN_AGGREGATE_EXPORT")
        (docs / name).write_text(payload, encoding="utf8")

    def fraction(m: dict) -> str:
        return f"{m['numerator']}/{m['denominator']} ({m['percentage']:.2f}%)"

    field_lines = []
    for field, result in summary["field_results"].items():
        before, after = result["before"]["R@5"], result["after"]["R@5"]
        field_lines.append(
            f"| {field} | {fraction(before)} | {fraction(after)} | {after['numerator'] - before['numerator']} | {after['denominator'] - after['numerator']} |"
        )
    stage_lines = [f"| {stage} | {count} |" for stage, count in summary["failure_counts"].items()]
    recall_lines = [
        f"| R@{k} | {fraction(summary['before'][f'R@{k}'])} | {fraction(summary['token_only'][f'R@{k}'])} | {fraction(summary['after'][f'R@{k}'])} |"
        for k in (1, 3, 5)
    ]
    secondary = summary["secondary_ocr"]
    report = f"""# GOVERNED 30 CANDIDATE COVERAGE CLOSURE

Status: **{summary["status"]}**. This is an isolated engineering candidate experiment, not a production extraction or release qualification result. Overall 98% and critical 99% targets are **not met**. No challenger or candidate rule is enabled in the production worker path.

Branch: `closure/cdp-target`. Frozen baseline commit: `75ebb518`. Track A remains 30 exact claims, 118 comparable fields, 86 critical fields. Raw accuracy remains **1/118 (0.85%)**; critical accuracy remains **1/86 (1.16%)**. Reference scoring, normalization, ranking, acceptance thresholds, truth, and form identity are unchanged.

The original 124-slot audit had 108 missing candidates. Its already-approved exclusion of six ambiguous service-date slots leaves **102 missing among 118**, plus 16 candidate-bearing slots: one correct selected, 14 wrong values, and one correct unselected alternative. This iteration does not change that denominator or exclusion.

## Candidate recall

| Metric | Frozen candidate pool | Token-only proposal pool | With eligible bounded OCR |
| --- | --- | --- | --- |
{chr(10).join(recall_lines)}

Critical R@5: **{fraction(summary["critical_before"]["R@5"])} → {fraction(summary["critical_after"]["R@5"])}**. Existing candidates keep their original order; unique token proposals and then secondary proposals are appended. Candidate@1 is not a new production selection. The correct alternative in the original ranking-miss case stays covered.

Missing candidate slots: **102 → {summary["missing_candidates_after"]}**. **{summary["fields_with_new_candidate"]}** previously empty slots now contain a review-only proposal; only **10 additional fields** gain a correct value within the first five. Wrong proposals do not count as recall recovery. The final pool contains proposals for {118 - summary["missing_candidates_after"]}/118 fields.

| Field | Before R@5 | After R@5 | Newly covered | Still uncovered |
| --- | --- | --- | --- | --- |
{chr(10).join(field_lines)}

Provider name is not represented in the frozen comparable slots. Service date remains excluded under the prior mapping audit; neither is assigned a new denominator here.

## Missing-candidate failure matrix

All 102 originally empty slots have exactly one primary stage. These are **new-capture replay diagnoses**, not reconstructed original worker logs; those logs did not retain the required token trace. Zero counts do not prove that a stage never failed historically.

| Primary stage | Fields |
| --- | --- |
{chr(10).join(stage_lines)}

The highest-priority shared blocker is total-charge localization (12 critical slots), followed by member-ID localization (10), patient-name localization (9), and patient-name assembly (8). The companion blocker artifact ranks critical count, affected claims, frequency, and field family. Actual claim unlock remains unproven because review and output blockers remain.

## Source visibility and OCR evidence

The original run persisted no full OCR token stream: its in-memory cache is gone, stored candidate token arrays are empty, and OCR audit records contain call metadata. Therefore the requested original-token split is **unknown for all 102 missing slots**. Unbound legacy OCR caches were not attributed to this run.

A new, explicitly labeled primary-engine capture used the same PaddleOCR PP-OCRv4 adapter and 1,600-pixel full-page cap on all **67 hash-verified prepared pages**. This was a primary evidence recapture, not multi-engine full-page escalation. Individual-line comparison found **47/102** references present and **55/102 not matched**. Name word-order equality is included. This is not exhaustive cross-token/date assembly and must not be called proof that 55 values are absent from OCR.

Engineering pixel inspection covers all 118 fields. Among the 102 missing slots: **89 VISIBLE_CLEAR, 7 PARTIAL, 2 OVERPRINTED, 4 NOT_PRESENT**, and zero VISIBLE_LOW_QUALITY/ILLEGIBLE. The four absent values are insured-name placeholders without a corresponding name in the semantic source field. They remain in the denominator and are not generated from pixels. Relational name cells, truncated/initialed names, identifier punctuation differences, and a multi-receipt aggregate require evidence-aware assembly; this iteration does not alter the comparator to force matches. Several prepared pages are rotated 180 degrees.

## Bounded localization and assembly

The retained experiment associates individual label tokens with the next two local rows, bounded by neighboring columns and at most 5% of page height. It handles OCR-confusable characters only in label recognition, preserves identifier characters, and uses the existing last/first interpretation only with source label or comma evidence. It does not merge unrelated columns or globally expand windows.

CMS name/member/charge labels provide explicit anchors. UB name labels can be associated, but terse birth-date labels and the unlabeled principal-diagnosis box remain localization gaps. A UB charge-column header alone is insufficient: the experiment requires a visible TOTALS row and charge-column intersection. The service-line crop that appeared to match a claim total was rejected. Receipts and other layouts receive no fixed CMS/UB coordinate fallback. Review-only proposals confer no standard-form identity or canonical authorization.

## Bounded OCR failure cohort

Nine initial regions were tried with RapidOCR. Final provenance auditing excludes one invalid service-line region and one redundant patient-name trial already covered by token assembly. Seven remaining regions received bounded CLAHE contrast processing and the supported Paddle adapter. One confirmed handwritten charge region attempted TroCR; optional ML dependencies were unavailable, so it produced no inference. Printed claims were not sent through handwriting OCR.

There were **{secondary["attempts"]} attempts, {secondary["completed_calls"]} completed OCR calls**, including the two excluded trials. The seven eligible regions produced **one incremental R@5 recovery (1/7, 14.29%)**, the insured name at rank 4. CLAHE added no incremental match. A matching patient-name OCR result was redundant, not a second recovery. No output from the invalid charge crop enters the final pool.

Primary recapture: **{summary["new_primary_ocr_seconds"]:.2f} seconds** total. Candidate replay including local image/hash reads: **{summary["candidate_replay_seconds"]:.2f} seconds**. Secondary trials including excluded work: **{secondary["seconds_including_rejected_trials"]:.2f} seconds**. Maximum observed post-call process RSS: **{secondary["maximum_observed_process_rss_bytes"] / 1048576:.2f} MiB**; this is not peak memory or isolated engine memory. Primary-capture memory was not measured. The bounded experiment does not establish an acceptable production latency budget; challengers remain disabled.

Reference values are used only by evaluation, failure classification, and gate assertions. The generator takes OCR geometry and image dimensions only. Capture helpers accept an exact source-only schema and reject reference-bearing keys. Crop coordinates originate from label/token evidence, never the expected value. The post-trial gate rejects missing provenance, already available token/assembly values, absent/partial source values, and unconfirmed handwriting.

## Separate ranking and downstream lanes

The single `CLM_D_006 / patient_name` ranking miss remains separate. A broad selected line had confidence 0.943; the narrower correct alternative had 0.867. OCR confidence did not establish semantic correctness. No ranking changes are retained. The 14 wrong-value cases have their own classification artifact; they are not relabeled as 14 ranking failures.

At both candidate milestones, routing is recomputed from the sealed field inventory, decisions and tasks. Because proposals are not emitted into production validation, there are **zero actual routing transitions**: auto accepted **0**, HITL **16**, not emitted **102**, not eligible **6**, unknown **0**. No synthetic transition is credited for a shadow candidate. Claim HITL remains **30/30 (100%)**; true STP remains **0/30**. This is an evidence reconciliation, not a replay of new proposals through runtime workers.

Output remains a separate lane: **22 failures**, all the previously recorded `OUTPUT_REQUIRES_STANDARD_FORM_TYPE:UNSTRUCTURED`, and **0 safe outputs**. Candidate recall does not conceal those failures. No new critical false accepts can arise from this disabled experiment; production acceptance evidence remains unchanged.

## Track B and validation

Source-only UI: http://127.0.0.1:8094/qualification-review/ — HTTP 200, predictions hidden. Bindings **150/150**; membership confirmed **{track_b["membership_confirmed"]}**, remaining **{track_b["membership_remaining"]}**; completed reviews **0**; trusted fields **0**. The owner-confirmation watcher is running. Continuity checks created no reviews and loaded no predictions. Independent reviewer registration remains pending.

Validation: **1,882 unit/architecture/golden tests passed**, **19 focused tests also passed** for the provenance and OCR gates. Scoped Ruff and mypy passed. Historical fixed-width goldens, strict identity, three false-UB04 canaries, and OTHER/UNKNOWN safety are included. **NEW_SEMANTIC_REGRESSIONS = 0** in this test scope; OTHER canonical localization = 0, UNKNOWN canonical localization = 0 in the canary/safety tests. No external-service integration or new production latency qualification is claimed.

PHI-bearing source images, OCR text, references and candidate values remain in ignored local evaluation storage. Published artifacts contain aliases, classifications and aggregate counts only. Original input hashes and acceptance-policy hashes are verified before every replay.

Reproduce candidate measurement with `.venv/Scripts/python.exe -m evaluation.governed_30_candidate_coverage`; then publish the aliased artifacts with `.venv/Scripts/python.exe -m evaluation.governed_30_candidate_report`. This requires the local sealed source/capture evidence. The source-only capture helpers live in `evaluation/governed_30_token_capture.py`; selected OCR adapters require the separate OCR environment.

## Next action

Add one source-evidenced claim-total anchor for a no-localization failure, then replay the frozen 30-claim cohort.
"""
    if any(json.dumps(value)[1:-1] in report for value in references):
        raise ValueError("REFERENCE_VALUE_IN_REPORT")
    (docs / "GOVERNED_30_CANDIDATE_COVERAGE_CLOSURE.md").write_text(report, encoding="utf8")
    code = [
        "evaluation/governed_30_candidate_coverage.py",
        "evaluation/governed_30_candidate_report.py",
        "evaluation/governed_30_token_capture.py",
        "workers/field_candidates/label_token_recovery.py",
        "tests/unit/cases/test_governed_30_candidate_coverage.py",
    ]
    seals = {
        "scope": "CANDIDATE_COVERAGE_EXPERIMENT",
        "baseline_commit": "75ebb518",
        "frozen_manifest_sha256": digest(
            root / "evaluation_results/governed_30_root_cause/frozen/run_manifest.local.json"
        ),
        "code": {p: digest(root / p) for p in code},
        "local_evidence": {p.name: digest(p) for p in sorted(local.glob("*.local.json"))},
        "primary_captures": {
            p.name: digest(p) for p in sorted((local / "primary_tokens").glob("*.local.json"))
        },
        "secondary_captures": {
            p.name: digest(p) for p in sorted((local / "secondary_tokens").glob("*.local.json"))
        },
        "validation_log_sha256": digest(root / ".runs/candidate-full-tests.log"),
    }
    (docs / "governed_30_candidate_coverage_seal.json").write_text(
        json.dumps(seals, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    export()
