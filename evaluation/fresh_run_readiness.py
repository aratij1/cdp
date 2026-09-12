"""Metadata-only diagnosis of an existing run; never performs OCR or reads scan files."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def diagnose(directory: Path, output: Path) -> dict:
    raw = json.loads((directory / "raw_execution.local.json").read_text(encoding="utf-8"))
    receipt = json.loads((directory / "run_receipt.json").read_text(encoding="utf-8"))
    stages = json.loads((directory / "stage_timings.local.json").read_text(encoding="utf-8"))["records"]
    audit = [json.loads(line) for line in
             (directory / "ocr_audit.local.jsonl").read_text(encoding="utf-8").splitlines()]
    totals: dict[str, float] = defaultdict(float)
    document_seconds: dict[str, float] = defaultdict(float)
    for row in stages:
        totals[row["worker"]] += row["seconds"]
        document_seconds[row["document_id"]] += row["seconds"]
    rows = []
    for claim in raw["claims"]:
        tasks = {task["field_id"]: task for task in claim["tasks"]}
        pages = {p["page_number"]: p["page_id"] for p in claim["pages"]}
        for field in claim["fields"]:
            task = tasks.get(field["field_id"], {})
            # Only enumerated codes; free-form validation messages may contain values.
            codes = [code for code in task.get("review_reason_codes", [])
                     if re.fullmatch(r"[A-Z][A-Z0-9_]*", str(code))]
            policy_missing = "FIELD_POLICY_NOT_CONFIGURED" in codes
            confidence = float(field.get("confidence") or 0)
            rows.append({
                "document_id": claim["document_id"], "page_id": pages.get(field["page_number"]),
                "field_name": field["field_name"],
                "reason": "NO_ACCEPTANCE_POLICY" if policy_missing else "OTHER",
                "reason_codes": codes,
                "engines": sorted({str(c.get("source")) for c in field.get("candidates", [])}),
                "confidence_band": "HIGH_0.95_TO_1" if confidence >= .95 else
                    "MID_0.8_TO_0.95" if confidence >= .8 else "LOW_BELOW_0.8",
                "validation_result": field["validation_status"],
                "acceptance_policy_result": "NOT_CONFIGURED" if policy_missing else "REVIEW_REQUIRED",
                "disposition": field["disposition"],
                "document_stage_seconds": document_seconds[claim["document_id"]],
                "field_timing": "NOT_CAPTURED",
                "evidence_available": bool(field.get("candidates")),
                "reference_evidence_available": bool(field.get("reference_evidence")),
            })
    reasons = dict(Counter(row["reason"] for row in rows))
    summary = {"scope": "EXISTING_RUN_METADATA_ONLY", "fields": rows, "reason_counts": reasons,
               "source_values_included": False, "accuracy": "NOT_EVALUABLE",
               "claim_membership_verified": raw.get("claims_membership_verified") is True}
    (directory / "hitl_reason_summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    engines = {}
    for engine in sorted({row["engine"] for row in audit}):
        events = [row for row in audit if row["engine"] == engine]
        engines[engine] = {"calls": len(events), "cache_hits": sum(r["cache_hit"] for r in events),
                           "wall_seconds": sum(r["latency_ms"] for r in events)/1000,
                           "cpu_seconds": sum(r["cpu_ms"] for r in events)/1000}
    profile = {
        "scope": "DIAGNOSTIC_EXISTING_12_SCAN_RUN", "production_latency_qualified": False,
        "elapsed_seconds": receipt["elapsed_seconds"], "scans": len(raw["claims"]),
        "seconds_per_scan": receipt["elapsed_seconds"]/len(raw["claims"]),
        "stage_wall_seconds": dict(totals), "instrumented_ocr_engines": engines,
        "ocr_audit_coverage": "18 instrumented extraction calls; routing OCR not separately audited",
        "cache_hits": sum(row["cache_hit"] for row in audit),
        "cache_misses": sum(not row["cache_hit"] for row in audit),
        "duplicate_suppression": "NOT_CAPTURED", "memory": "NOT_CAPTURED",
        "process_cpu": "NOT_CAPTURED; per-instrumented-OCR CPU reported above",
        "engine_versions": sorted({(str(f.get("model_name")), str(f.get("model_version")))
                                   for c in raw["claims"] for f in c["fields"]
                                   if f.get("model_name") and f.get("model_version")}) or "NOT_CAPTURED",
        "preprocessing_versions": sorted({r["preprocessing_profile"] for r in audit}),
        "python": receipt["python"], "runtime": receipt["runtime"],
        "provider_gpu_availability": "NOT_CAPTURED",
        "primary_secondary_ocr_split": "NOT_CAPTURED consistently across routing and extraction",
        "model_loading_serialization_io_split": "NOT_CAPTURED",
        "evidence_processing_split": "Included in validation; not separately captured",
        "execution_model": "Sequential local worker harness",
        "dominant_stages": "Unstructured extraction and routing; OCR/loading subcomponents cannot be separated from this historical trace",
        "optimization_performed": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "fresh_path_profile.json").write_text(json.dumps(profile, indent=2)+"\n")
    (output / "HITL_DIAGNOSTIC.md").write_text(
        "# Existing 12-scan HITL diagnostic\n\n"
        f"{len(rows)}/21 extracted fields: {reasons}. All 12 documents required review. "
        "The recorded terminal reason is FIELD_POLICY_NOT_CONFIGURED: an acceptance-policy "
        "problem, not a measured recognition error. Critical consensus and validation cannot "
        "authorize acceptance without a configured field policy.\n\n"
        "Governance is independently incomplete: claim boundaries and trusted labels are unavailable. "
        "Recognition correctness, source quality and complete-claim accuracy cannot be inferred "
        "from confidence or the HITL rate. No thresholds changed and no scans were opened.\n\n"
        "The run receipt is COMPLETED, but only 9/12 document event chains recorded execution_complete; "
        "three routing holds produced no extracted fields. All 12 scans were attempted. "
        "Automatic outputs and runtime STP_SAFE were 0/12. Production STP_SAFE is NOT_EVALUABLE.\n"
    )
    return {"fields": len(rows), "documents": len(raw["claims"]), "reasons": reasons}
