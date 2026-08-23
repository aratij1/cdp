"""Publish honest Phase 7A.15 status artifacts from verified tuning truth only."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation_results/phase7a15"
DOCS = ROOT / "docs"


def _rows(name: str) -> list[dict]:
    path = RESULTS / name
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _write(name: str, payload: dict) -> None:
    (RESULTS / name).write_text(json.dumps(payload, indent=2) + "\n", "utf-8")


def _doc(name: str, title: str, body: str) -> None:
    (DOCS / name).write_text(f"# {title}\n\n{body.strip()}\n", "utf-8")


def publish() -> dict:
    manifest = json.loads((RESULTS / "annotation_sample_manifest.json").read_text("utf-8"))
    fields, crops, lines = _rows("field_truth.jsonl"), _rows("crop_truth.jsonl"), _rows(
        "ub_service_line_truth.jsonl"
    )
    verified_fields = [row for row in fields if row["review_status"] == "VERIFIED"]
    verified_crops = [row for row in crops if row["review_status"] == "VERIFIED"]
    verified_lines = [row for row in lines if row["review_status"] == "VERIFIED"]
    ready = bool(verified_fields and verified_crops and verified_lines)
    blocked = {
        "status": "BLOCKED_PENDING_HUMAN_VERIFICATION" if not ready else "READY_FOR_REPLAY",
        "verified_field_records": len(verified_fields),
        "verified_crop_records": len(verified_crops),
        "verified_service_line_pages": len(verified_lines),
        "observation_only_pages_used": 0,
    }
    metric_names = (
        "crop_metrics.json", "ocr_correct_crop.json", "geometry_mode_metrics.json",
        "cms_extraction.json", "ub_extraction.json", "verification.json",
        "ub_service_lines.json", "error_pareto.json",
    )
    for name in metric_names:
        _write(name, blocked | {"metric_status": "NOT_MEASURABLE_UNTIL_TRUTH_FREEZE"})
    _write("experiments.json", {
        **blocked,
        "EXP-03A": "NOT_RUN_TUNING_TRUTH_NOT_FROZEN",
        "next_experiment": "EXP-03A_TEMPLATE_LINEAGE_RECOVERY",
    })
    _write("candidate.json", {
        **blocked, "candidate_id": "ACCURACY_RECOVERY_CANDIDATE_1", "created": False,
    })
    decision = {
        **blocked,
        "decision": "CONTINUE_HUMAN_ANNOTATION" if not ready else "FREEZE_AND_REPLAY_REQUIRED",
        "selection_sha256": manifest["selection_sha256"],
        "selected_pages": manifest["page_count"],
        "selected_family_distribution": manifest["family_distribution"],
        "next_bottleneck": "HUMAN_VERIFY_FIELD_CROP_AND_UB_SERVICE_LINE_TASKS",
    }
    _write("decision.json", decision)

    summary = (
        f"The deterministic tuning-only sample contains {manifest['page_count']} pages: "
        + ", ".join(f"{family}={count}" for family, count in manifest["family_distribution"].items())
        + f". Its selection hash is `{manifest['selection_sha256']}`. No observation-only page was selected. "
        f"Verified fields={len(verified_fields)}, crops={len(verified_crops)}, UB line pages={len(verified_lines)}. "
        "Generated suggestions remain unverified; TUNING_TRUTH_V1 cannot freeze until visual review is complete."
    )
    _doc("CDP_PHASE7A15_TUNING_TRUTH.md", "CDP Phase 7A.15 Tuning Truth", summary)
    _doc("CDP_PHASE7A15_CROP_CORRECTNESS.md", "CDP Phase 7A.15 Crop Correctness",
         summary + "\n\nCrop metrics are not measurable before verified crop truth is frozen.")
    _doc("CDP_PHASE7A15_OCR_CORRECT_CROP.md", "CDP Phase 7A.15 OCR on Correct Crops",
         "RapidOCR, PaddleOCR, and Tesseract are not benchmarked until FULL_VALUE_VISIBLE crops are verified.")
    _doc("CDP_PHASE7A15_TEMPLATE_LINEAGES.md", "CDP Phase 7A.15 Template Lineages",
         "Lineage clustering and EXP-03A remain paused until TUNING_TRUTH_V1 freezes. Registration remains classified as TEMPLATE_LINEAGE_GENERALIZATION_MISMATCH.")
    _doc("CDP_PHASE7A15_CMS_EXTRACTION.md", "CDP Phase 7A.15 CMS Extraction",
         "Baseline exact field accuracy is 19.79%. Post-remediation accuracy is not yet measurable.")
    _doc("CDP_PHASE7A15_UB_EXTRACTION.md", "CDP Phase 7A.15 UB Extraction",
         "Baseline exact field accuracy is 32.41%. Post-remediation accuracy is not yet measurable.")
    _doc("CDP_PHASE7A15_VERIFIER_EVALUATION.md", "CDP Phase 7A.15 Verifier Evaluation",
         "Current refactored verifiers will be measured unchanged after truth freeze; thresholds have not been altered.")
    _doc("CDP_PHASE7A15_UB_SERVICE_LINES.md", "CDP Phase 7A.15 UB Service Lines",
         f"Fifty UB pages are queued for row annotation; {len(verified_lines)} are currently verified.")
    _doc("CDP_PHASE7A15_FIELD_ERROR_PARETO.md", "CDP Phase 7A.15 Field Error Pareto",
         "The error Pareto is not measurable before verified field and crop truth exists.")
    _doc("CDP_PHASE7A15_FINAL_REPORT.md", "CDP Phase 7A.15 Final Report",
         summary + "\n\nDecision: `CONTINUE_HUMAN_ANNOTATION`; no accuracy candidate or observation-only run is authorized.")
    return decision | {"verified_family_fields": dict(Counter(
        row["form_family"] for row in verified_fields
    ))}


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2))
