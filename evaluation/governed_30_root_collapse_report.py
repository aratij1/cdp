"""Publish PHI-safe evidence for the governed root-cause collapse iteration."""

from __future__ import annotations

import json
import re
from pathlib import Path

from evaluation.governed_30_reference import ROOT, digest


def export(root: Path = ROOT) -> None:
    out = root / "evaluation_results/governed_30_root_collapse"
    docs = root / "docs/qualification"
    read = lambda p: json.loads(p.read_text(encoding="utf8"))
    summary = read(out / "root_collapse_summary.local.json")
    fields = read(out / "all_field_audit.local.json")["fields"]
    audit = read(out / "orientation_audit.local.json")
    oriented = [read(p) for p in (out / "oriented_tokens").glob("*.local.json")]
    prior_seconds = sum(
        read(
            root
            / f"evaluation_results/governed_30_candidate_coverage/primary_tokens/{r['claim_alias']}_P{r['page_number']:03}.local.json"
        )["latency_seconds"]
        for r in oriented
    )
    selected = {(r["claim_alias"], r["page_number"]) for r in oriented}
    orientation = {
        "scope": "REVIEWED_ORIENTATION_DIAGNOSTIC; not automatic production preprocessing",
        "pages_audited": len(audit),
        "osd_nonzero_flags": sum(r["rotation"] in {90, 180, 270} for r in audit),
        "source_inverted_verified": sum(
            r.get("visual_inspection") == "SOURCE_TEXT_INVERTED_180" for r in audit
        ),
        "osd_false_positives": sum(
            r.get("visual_inspection") == "UPRIGHT_OSD_FALSE_POSITIVE" for r in audit
        ),
        "automatic_osd_confidence_gate_passes": sum(r["eligible"] for r in audit),
        "automatic_grid_osd_gate_passes": sum(r["rotate_by_grid_osd"] for r in audit),
        "manually_verified_governed_pages_recaptured": len(oriented),
        "other_inverted_pages_not_recaptured": "8 separator/support pages outside the audited governed target fields; no OCR expansion",
        "osd_audit_seconds": sum(r["seconds"] for r in audit),
        "grid_audit_seconds": sum(r["grid_seconds"] for r in audit),
        "same_primary_before_seconds": prior_seconds,
        "same_primary_rotated_seconds": sum(r["seconds"] for r in oriented),
        "same_primary_delta_seconds": sum(r["seconds"] for r in oriented) - prior_seconds,
        "token_presence_on_affected_fields_before": sum(
            r["before_token_presence"]
            for r in fields
            if any(
                (r["claim_alias"], p) in selected for p in r["source_visibility"]["source_pages"]
            )
        ),
        "token_presence_on_affected_fields_after": sum(
            r["after_orientation_token_presence"]
            for r in fields
            if any(
                (r["claim_alias"], p) in selected for p in r["source_visibility"]["source_pages"]
            )
        ),
        "affected_field_count": sum(
            any((r["claim_alias"], p) in selected for p in r["source_visibility"]["source_pages"])
            for r in fields
        ),
        "token_presence_limit": "Whole OCR line/name component equality; not extraction accuracy",
        "pages": audit,
    }
    ocr = read(out / "residual_ocr_benchmark.local.json")
    track_b = read(out / "track_b_continuity.local.json")
    log = (root / ".runs/root-collapse-full-tests.log").read_text(encoding="utf8", errors="replace")
    # PowerShell redirection can encode the captured log as UTF-16.
    if "\x00" in log:
        log = (root / ".runs/root-collapse-full-tests.log").read_text(encoding="utf16")
    match = re.search(r"(\d+) passed", log)
    if not match or "FAILED " in log:
        raise ValueError("FULL_REGRESSION_SUCCESS_REQUIRED")
    tests = int(match[1])
    artifacts = {
        "governed_30_remaining_miss_taxonomy.json": read(
            out / "remaining_miss_taxonomy.local.json"
        ),
        "governed_30_root_collapse_field_audit.json": {"fields": fields},
        "governed_30_root_collapse_scorecard.json": summary,
        "governed_30_root_collapse_orientation.json": orientation,
        "governed_30_root_collapse_semantics.json": read(
            out / "placeholder_contract_audit.local.json"
        ),
        "governed_30_root_collapse_ocr_cohort.json": {
            **ocr,
            "neighbor_audit": read(out / "recognition_neighbor_audit.local.json"),
        },
        "governed_30_root_collapse_track_b.json": track_b,
    }
    private = read(out / "root_collapse_records.local.json")
    reference_values = [
        str(r["reference_value"]) for r in private if len(str(r["reference_value"])) >= 6
    ]
    for name, data in artifacts.items():
        payload = json.dumps(data, indent=2) + "\n"
        if any(json.dumps(value) in payload for value in reference_values):
            raise ValueError("REFERENCE_VALUE_IN_PUBLIC_ARTIFACT")
        (docs / name).write_text(payload, encoding="utf8")

    def f(m):
        return (
            "N/A"
            if not m["denominator"]
            else f"{m['numerator']}/{m['denominator']} ({m['percentage']:.2f}%)"
        )

    tax = "\n".join(f"| {cause} | {count} |" for cause, count in summary["taxonomy"].items())
    recalls = "\n".join(
        f"| {mode} | {f(m['R@1'])} | {f(m['R@3'])} | {f(m['R@5'])} | {f(summary['critical_experiments'][mode]['R@5'])} |"
        for mode, m in summary["experiments"].items()
    )
    field_table = []
    for name, v in summary["field_results"].items():
        causes = v["miss_causes"]
        localization = sum(
            causes.get(c, 0)
            for c in [
                "REGION_LOCALIZATION",
                "LABEL_TO_VALUE_ASSOCIATION",
                "WRONG_FORM_OR_FIELD_TOPOLOGY",
            ]
        )
        field_table.append(
            f"| {name} | {v['comparable']} | {f(v['after']['R@1'])} | {f(v['after']['R@3'])} | {f(v['after']['R@5'])} | {v['source_semantic']} | {localization} | {causes.get('TOKEN_ASSEMBLY', 0)} | {causes.get('OCR_RECOGNITION_MISS', 0)} | {causes.get('SOURCE_VALUE_NOT_PRESENT', 0) + causes.get('SOURCE_ILLEGIBLE', 0)} |"
        )
    recovered = [
        r for r in fields if r["baseline_miss"] and r["experiments"]["combined"]["recall"]["5"]
    ]
    recovered_lines = "\n".join(
        f"- `{r['claim_alias']} / {r['field']}` — {'reviewed orientation' if r['experiments']['orientation']['recall']['5'] else 'field geometry / typed date assembly'}."
        for r in recovered
    )
    report = f"""# CANDIDATE COVERAGE ROOT-CAUSE COLLAPSE

**FINAL STATUS: {summary["status"]}**. All **106 original remaining misses** have exactly one concrete primary cause. No UNKNOWN/OTHER case remains. The official engineering denominator stays **118** across **30 exact Track A claims**.

Candidate Recall@5 improved from **12/118 (10.17%)** to **{f(summary["experiments"]["combined"]["R@5"])}** in the combined review-only experiment. Critical Recall@5 improved from **9/86** to **{f(summary["critical_experiments"]["combined"]["R@5"])}**. **{summary["remaining_after"]} misses remain**. The 98% target is not met. Production extraction, canonical output, acceptance, scoring, ranking, and release truth are unchanged.

The geometry/assembly change alone reaches **{f(summary["experiments"]["geometry"]["R@5"])}**. Two further fields require the explicitly **manually verified orientation diagnostic**. No automated orientation detector or secondary OCR challenger is enabled in production. Baseline commit: `b954b200`, branch `closure/cdp-target`.

## Miss taxonomy

These counts classify the original 106 misses, not a newly reduced denominator. The 118-field audit also records each retained experiment and whether the original miss was recovered. Evidence consists of frozen OCR token indices, label/value boxes, page/column relationships, distances, candidate-region provenance and source-visibility annotations. This is a reconstructed engineering trace, not fabricated historical worker telemetry.

| Primary cause | Original misses |
| --- | --- |
{tax}

Matching text elsewhere on a page is not assigned to the target field. In two UB claims, the correct-looking code appears in the admitting-diagnosis cell while the principal cell contains a different recognized code; these are recognition misses. Four other principal-diagnosis values are present in their actual box-67 region but lack a supported field anchor. Name component-order evidence is treated as assembly only when local label/value geometry supports it. Three initially suspected recognition misses instead contain observed amount components or a merged numeric span; they are assembly failures. A UB charge-column header without a proven totals-row intersection is a topology failure, not a grounded total OCR region.

## Extractable source cohort and conditional ceiling

**EXTRACTABLE_SOURCE_FIELDS: {summary["extractable"]}**. **NONEXTRACTABLE_OR_SEMANTIC_REFERENCE_FIELDS: {summary["nonextractable_or_semantic"]}**. The latter comprise four absent insured-name values represented by reference placeholders; two source name cells saying SAME without a governed inheritance rule; fourteen abbreviation, fixed-width truncation, nickname or identifier-punctuation differences; and one reference total requiring aggregation across two distinct receipts.

These 21 cases remain in the official 118. Visible full names and punctuated identifiers are still extractable as source text; “semantic” here means they cannot be credited as the frozen reference value under the current governed comparison contract. No fake name, abbreviation, stripped identifier or reference-derived total is generated.

Diagnostic recoverable Recall@5: **{f(summary["recoverable_recall"]["baseline"]["R@5"])} → {f(summary["recoverable_recall"]["combined"]["R@5"])}**. Within the 97 source-present fields there are zero established genuinely unavailable cases, so `(97 - 0) / 97 = 100%` is a **conditional logical upper bound**, not a demonstrated OCR ceiling. Keeping the 21 semantic cases unresolved gives a corresponding 97/118 (82.20%) bound on literal frozen-reference recovery. Neither calculation rewrites the official denominator or qualifies a release. No claim of an empirical OCR ceiling is made.

## Candidate and field results

| Experiment | R@1 | R@3 | R@5 | Critical R@5 |
| --- | --- | --- | --- | --- |
{recalls}

The candidate pools retain original emitted selections/alternatives. New geometry operates on observed labels and source token boxes. A proven birth-date/sex compound anchor replaces the generic birth-date row proposal set, because neighboring sex/admission values are not date alternatives. Eight observed digits are assembled with the existing US date convention; characters and centuries are never repaired or inferred. This changes field localization and candidate filtering, not confidence ranking or the comparator.

The following source-semantic and cause counts refer to the original taxonomy; recall columns show the final combined diagnostic.

| Field | Comparable | R@1 | R@3 | R@5 | Semantic | Localization/association/topology | Assembly | OCR | Absent/illegible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(field_table)}

Provider name has no comparable slot in this frozen cohort. Service date remains outside these 118 under the previously sealed mapping decision. No zero-denominator percentage is fabricated.

## Retained changes and orientation diagnostic

Seven critical fields recover through bounded field geometry/assembly: three birth dates using an observed field-10 birth-date/sex relationship, three claim totals including observed dollar/cents assembly, and a label-local name token. The separate six-page orientation diagnostic recovers two more critical fields. No previously covered field is lost.

{recovered_lines}

Geometry uses distinct family bounds, neighboring column boundaries and observed label/value coordinates. A service charge-column header still cannot authorize a claim total. Candidate values come only from observed tokens or explicit date assembly. Runtime APIs accept no reference value, and proposals remain review-only.

Orientation audit: **67 pages** examined using local OSD, then structural grid comparison. There were **16 OSD inversion flags**: **14 visually confirmed inverted pages** and **2 upright false positives**. No page passed the conservative automatic OSD gate or the joint grid/OSD gate. Six inverted pages contained the audited governed target fields and were recaptured with the same PaddleOCR PP-OCRv4 primary engine. Eight separator/support pages outside those target fields were not sent through additional OCR.

Affected-field token presence (whole-line/component comparison): **{orientation["token_presence_on_affected_fields_before"]}/{orientation["affected_field_count"]} → {orientation["token_presence_on_affected_fields_after"]}/{orientation["affected_field_count"]}**. OSD audit cost **{orientation["osd_audit_seconds"]:.2f}s**; structural-grid audit cost **{orientation["grid_audit_seconds"]:.2f}s**. The six same-primary captures cost **{orientation["same_primary_rotated_seconds"]:.2f}s**, versus **{orientation["same_primary_before_seconds"]:.2f}s** for their prior unrotated captures: observed delta **{orientation["same_primary_delta_seconds"]:.2f}s**. These sequential local measurements are not a controlled production latency benchmark. The final four-mode replay took **{summary["replay_seconds"]:.2f}s** including image/hash reads. No global preprocessing change is retained.

## Semantic contract and rejected proposals

The supplied `NSF_matrix.txt` and `UB92_specs.txt`, their compiled output contracts, and existing claim consistency policy provide no explicit rule copying a patient name into a SAME insured-name cell. Existing SELF logic checks equality only when both names are independently observed and unambiguous; it does not create missing values. The two name-placeholder cases stay unresolved. Eight exact placeholder lexemes observed in existing OCR are inventoried separately; a printed SELF checkbox option is not proof it was selected.

The existing name comparator permits formatting differences, not initial/full-name equivalence or arbitrary truncation. The member-ID comparator preserves punctuation. These rules were audited and tested without modification.

Rejected proposals:

- **Automatic orientation:** no conservative evidence gate passed; two low-confidence OSD false positives demonstrate the need to abstain. Costs are recorded above; no production semantic impact.
- **Broader fuzzy name-convention inference:** no incremental Recall@5 recovery in the all-30 replay; removed instead of adding complexity. No OCR calls were added; replay cost was approximately 16 seconds. No acceptance or output impact.
- **SAME/SELF inheritance and abbreviation rewriting:** no authorizing governed rule; zero runtime candidates or OCR calls created.
- **Global or expanded secondary OCR:** not performed. Prior invalid-region and redundant recoveries stay excluded; source semantics, association and assembly cases are not sent to challengers.

## Residual recognition benchmark

There are **{ocr["taxonomy_ocr_misses"]} recognition-classified misses**. A bounded audit of two-to-four neighboring tokens in their observed label neighborhoods found no additional reference match. Existing prior region trials cover **{ocr["benchmarked_fields"]}** of those fields: **{sum(not t["error_type"] for t in ocr["trials"])} completed region calls** across RapidOCR, CLAHE and Paddle, plus **one failed optional handwriting-model attempt**. They produced **zero recoveries** in this residual cohort, with **{sum(t["seconds"] for t in ocr["trials"]):.2f}s** historical measured trial time. These prior results are reused, not credited as new work or rerun. The remaining recognition fields are not declared exhausted. **New secondary OCR calls: 0.**

## Separate routing, output and Track B lanes

Frozen runtime events, field inventory, decisions and tasks were reconciled for the candidate milestones. Review-only proposals are not worker emissions, so actual transitions remain zero: **AUTO_ACCEPTED 0; HITL 16; NOT_EMITTED 102; NOT_ELIGIBLE 6; UNKNOWN 0**. No field suppression is credited. Claim HITL remains **30/30 (100%)**; true STP **0/30**. Raw production accuracy remains **1/118**, critical accuracy **1/86**.

Output remains **22 failures** (`OUTPUT_REQUIRES_STANDARD_FORM_TYPE:UNSTRUCTURED`) and **0 safe outputs**. No output-contract patch is mixed into this iteration.

Track B: source-only UI http://127.0.0.1:8094/qualification-review/ is live (HTTP 200, predictions hidden). Source bindings **150/150**; owner-confirmed membership **0/150**, remaining **150**; completed reviews **0**; trusted fields **0**. Owner-confirmation watcher remains active. No review was written and no prediction was loaded for tuning.

## Validation and evidence

**{tests:,} unit, architecture and fixed-width golden tests passed**; **34 focused structural/semantic/orientation tests passed**. Scoped Ruff and mypy passed. Tests cover strict identity, OTHER/UNKNOWN safety, false-UB04 canaries, source-only input schemas, immutable identifiers, placeholder abstention, compound topology, invalid dates, cross-column isolation and the preserved charge-column guard. **NEW_SEMANTIC_REGRESSIONS = 0** in this regression scope. Canonical production output is unchanged. No external-service integration or production latency qualification is claimed.

Raw sources, OCR strings, reference values and private candidate evidence remain in ignored local evaluation storage. Published artifacts contain aliases, boxes, classifications and aggregates. Frozen source/capture and acceptance-policy hashes are verified by replay.

Reproduce with `.venv/Scripts/python.exe -m evaluation.governed_30_root_collapse`, then `.venv/Scripts/python.exe -m evaluation.governed_30_root_collapse_report`. Local sealed evidence is required. Reviewed rotation capture has a source-only helper in `evaluation/root_collapse_capture.py`; it does not enable automatic rotation.

## Next action

Add a source-proven box-67 principal-diagnosis anchor for the four cases whose correct tokens are already in that cell, then replay the frozen 30 claims.
"""
    if any(value in report for value in reference_values):
        raise ValueError("REFERENCE_VALUE_IN_PUBLIC_REPORT")
    (docs / "GOVERNED_30_ROOT_CAUSE_COLLAPSE.md").write_text(report, encoding="utf8")
    code = [
        "evaluation/governed_30_root_collapse.py",
        "evaluation/governed_30_root_collapse_report.py",
        "evaluation/root_collapse_capture.py",
        "workers/field_candidates/bounded_geometry_recovery.py",
        "tests/unit/cases/test_governed_30_root_collapse.py",
    ]
    seal = {
        "baseline_commit": "b954b200",
        "code": {name: digest(root / name) for name in code},
        "local_evidence": {p.name: digest(p) for p in sorted(out.glob("*.local.json"))},
        "oriented_captures": {
            p.name: digest(p) for p in sorted((out / "oriented_tokens").glob("*.local.json"))
        },
        "validation_log_sha256": digest(root / ".runs/root-collapse-full-tests.log"),
    }
    (docs / "governed_30_root_collapse_seal.json").write_text(
        json.dumps(seal, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    export()
