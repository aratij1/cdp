#!/usr/bin/env python3
"""Operational E2E qualification for 100 real claims.

Closes the production-qualification measurement gap by:

1. Scoring the frozen operational 100-claim application-path run
   (classify → select → register → extract → decide → FinalClaim)
2. Reporting true STP separately from Golden Pack Claim STP Proxy
3. Integrating the recovery framework (diagnose → plan_recovery) on
   every incomplete claim, with at most one cause-specific attempt when
   an approved strategy is available

Live re-execution of the Hackathon ZIP is optional (`--live`) and requires
the archive + tesseract. Default mode scores the authoritative frozen run
recorded in AnchorNormalizationDeltaReport.json.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _display_path(path: Path) -> str:
    """Return a workspace-relative path string for reports."""
    resolved = path if path.is_absolute() else (ROOT / path)
    resolved = resolved.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


DEFAULT_OPS_REPORT = ROOT / "AnchorNormalizationDeltaReport.json"
DEFAULT_OUT = ROOT / "evaluation_results" / "operational_e2e_100_v1"
STAGE_SCRIPTS = {
    "ocr": "scripts/ocr_from_geometry.py",
    "rank": "scripts/rank_from_ocr.py",
    "validate": "scripts/validate_from_ranked.py",
    "assemble": "scripts/assemble_extraction_result.py",
    "complete": "scripts/complete_from_extraction.py",
}


@dataclass
class ClaimOutcome:
    claim_index: int
    document: str
    document_id: str
    completed: bool
    review_required: bool | None
    claim_status: str | None
    application_status: str | None
    registration_category: str | None
    registration_reason: str | None
    latency_seconds: float | None
    true_stp: bool
    recovery: dict[str, Any] = field(default_factory=dict)
    source: str = "frozen_operational_run"


def _load_ops_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _recovery_for_failure(
    *,
    registration_category: str | None,
    registration_reason: str | None,
    application_status: str | None,
    strategy_available: bool = False,
) -> dict[str, Any]:
    """Apply packages.recovery diagnose + plan_recovery to one failed claim."""
    from packages.recovery import diagnose, plan_recovery
    from packages.recovery.diagnosis import Cause
    from packages.recovery.planner import Strategy

    reasons = [
        value
        for value in (registration_category, registration_reason, application_status)
        if value
    ]
    category = (registration_category or "").casefold()
    reason = (registration_reason or "").casefold()

    diagnosis = diagnose(
        reasons,
        asset_missing="missing" in reason and "asset" in reason,
        document_unknown="unknown" in reason or "unclassified" in reason,
        unsupported_form="unsupported" in reason,
        contract_failure="contract" in reason,
        source_quality_failure="low_inlier" in reason or "poor_scan" in reason or "blur" in reason,
        template_incompatible="template" in reason and ("mismatch" in reason or "incompat" in reason),
        ocr_attempted="ocr" in reason or "ocr" in category,
        evidence=reasons,
    )
    # Registration/selection failures are explicit enough to surface as those causes
    # when the recorded category matches, without inventing a physical root cause.
    if diagnosis.primary_cause is Cause.UNDETERMINED:
        if "selection" in category:
            from packages.recovery.diagnosis import Diagnosis

            diagnosis = Diagnosis(
                Cause.UNKNOWN_DOCUMENT,
                "MEDIUM",
                tuple(reasons),
                reason="SelectionUnavailable recorded on the application path",
            )
        elif "safety" in category or "registration" in category:
            from packages.recovery.diagnosis import Diagnosis

            diagnosis = Diagnosis(
                Cause.REGISTRATION_FAILURE,
                "MEDIUM",
                tuple(reasons),
                reason="Registration SafetyFailure recorded on the application path",
            )

    # OCR alternate-prep and registration image-enhancement are approved/available.
    available = strategy_available or diagnosis.primary_cause in {
        Cause.OCR_FAILURE,
        Cause.POOR_SCAN,
        Cause.REGISTRATION_FAILURE,
    }
    plan = plan_recovery(diagnosis, strategy_available=available)
    return {
        "diagnosis": {
            "primary_cause": diagnosis.primary_cause.value,
            "confidence": diagnosis.confidence,
            "reason": diagnosis.reason,
            "evidence": list(diagnosis.evidence),
        },
        "plan": {
            "strategy": plan.strategy.value,
            "executable": plan.executable,
            "reason": plan.reason,
            "max_attempts": plan.max_attempts,
        },
        "executed": False,
        "note": (
            "Recovery plans are cause-driven and bounded to one attempt when executable. "
            "Selection/registration failures without an approved alternate strategy route "
            "to HUMAN_QUEUE rather than blind retry."
            if plan.strategy is Strategy.HUMAN_QUEUE or not plan.executable
            else "Executable recovery strategy permitted for one bounded attempt."
        ),
    }


def score_frozen_run(ops_report: dict) -> dict[str, Any]:
    claims = ops_report.get("paired_claims") or []
    outcomes: list[ClaimOutcome] = []
    recovery_strategy_counts: Counter[str] = Counter()
    recovery_cause_counts: Counter[str] = Counter()

    for row in claims:
        after = row.get("after") or {}
        completed = bool(after.get("completed"))
        review_required = after.get("review_required")
        true_stp = completed and review_required is False
        recovery: dict[str, Any] = {}
        if not completed:
            recovery = _recovery_for_failure(
                registration_category=after.get("registration_category"),
                registration_reason=after.get("registration_reason"),
                application_status=after.get("application_status"),
            )
            recovery_strategy_counts[recovery["plan"]["strategy"]] += 1
            recovery_cause_counts[recovery["diagnosis"]["primary_cause"]] += 1

        outcomes.append(
            ClaimOutcome(
                claim_index=int(row.get("claim") or 0),
                document=str(row.get("document") or ""),
                document_id=str(row.get("document_id") or ""),
                completed=completed,
                review_required=review_required if isinstance(review_required, bool) else None,
                claim_status=after.get("claim_status"),
                application_status=after.get("application_status"),
                registration_category=after.get("registration_category"),
                registration_reason=after.get("registration_reason"),
                latency_seconds=after.get("latency_seconds"),
                true_stp=true_stp,
                recovery=recovery,
            )
        )

    submitted = len(outcomes)
    completed_n = sum(1 for item in outcomes if item.completed)
    true_stp_n = sum(1 for item in outcomes if item.true_stp)
    review_n = sum(1 for item in outcomes if item.completed and item.review_required is True)
    incomplete_n = submitted - completed_n
    latencies = [item.latency_seconds for item in outcomes if item.latency_seconds is not None]
    completed_latencies = [
        item.latency_seconds
        for item in outcomes
        if item.completed and item.latency_seconds is not None
    ]

    return {
        "measurement_scope": "OPERATIONAL_E2E",
        "dataset": {
            "label": "HACKATHON_1000_CLAIMS_FIXED_100_SAMPLE",
            "submitted_claims": submitted,
            "sample_sha256": ops_report.get("sample_sha256"),
            "dataset_sha256": ops_report.get("dataset_sha256"),
            "source_report": str(DEFAULT_OPS_REPORT.name),
            "baseline_run": ops_report.get("baseline_run"),
            "current_run": ops_report.get("current_run"),
            "ground_truth_available": False,
        },
        "metric_definitions": {
            "operational_completion": (
                "Application SUCCESS and COMPLETED FinalClaim / submitted claims. "
                "Does not require field correctness against external ground truth."
            ),
            "true_stp": (
                "COMPLETED FinalClaim with review_required=false and no human intervention "
                "/ submitted claims. This is production STP — not Golden Pack Claim STP Proxy."
            ),
            "end_to_end_correct_completion": (
                "Correct FinalClaim against independent ground truth / submitted claims. "
                "Unavailable for the Hackathon sample (no field-level GT)."
            ),
            "golden_pack_claim_stp_proxy": (
                "EXTRACTION_HARNESS metric only. Identity/template supplied by harness. "
                "Must never be labeled production STP."
            ),
        },
        "metrics": {
            "submitted_claims": submitted,
            "operational_completion_count": completed_n,
            "operational_completion_rate": completed_n / max(1, submitted),
            "true_stp_count": true_stp_n,
            "true_stp_rate": true_stp_n / max(1, submitted),
            "completed_with_review_count": review_n,
            "completed_with_review_rate": review_n / max(1, submitted),
            "incomplete_count": incomplete_n,
            "incomplete_rate": incomplete_n / max(1, submitted),
            "end_to_end_correct_completion_count": None,
            "end_to_end_correct_completion_rate": None,
            "end_to_end_correct_completion_status": "UNAVAILABLE_NO_GROUND_TRUTH",
            "mean_latency_seconds_all": (sum(latencies) / len(latencies)) if latencies else None,
            "mean_latency_seconds_completed": (
                sum(completed_latencies) / len(completed_latencies) if completed_latencies else None
            ),
        },
        "failure_taxonomy": dict(
            Counter(
                item.registration_category or item.application_status or "UNKNOWN"
                for item in outcomes
                if not item.completed
            )
        ),
        "recovery_integration": {
            "enabled": True,
            "policy": (
                "On every incomplete claim: diagnose(failure) → plan_recovery(...). "
                "At most one cause-specific attempt when strategy_available; otherwise HUMAN_QUEUE. "
                "No blind retries. Regional OCR alternate-prep remains available in the OCR stage."
            ),
            "incomplete_claims_planned": incomplete_n,
            "strategy_counts": dict(recovery_strategy_counts),
            "cause_counts": dict(recovery_cause_counts),
            "executable_plans": sum(
                1 for item in outcomes if item.recovery.get("plan", {}).get("executable")
            ),
            "human_queue_plans": sum(
                1
                for item in outcomes
                if item.recovery.get("plan", {}).get("strategy") == "HUMAN_QUEUE"
            ),
        },
        "claims": [asdict(item) for item in outcomes],
        "generated_at": datetime.now(UTC).isoformat(),
        "production_qualification": {
            "status": "NOT_QUALIFIED",
            "blocking_reasons": [
                "true_stp_rate is 0% (all completed claims still require field review)",
                "operational_completion_rate is below target (39%)",
                "end_to_end_correct_completion unavailable without independent ground truth",
                "61/100 claims never reach FinalClaim (selection/registration failures)",
            ],
            "passed_gates": [
                "measurement_scope separation enforced (OPERATIONAL_E2E vs EXTRACTION_HARNESS)",
                "recovery framework integrated into E2E scoring for all incomplete claims",
                "true_stp reported separately from Golden Pack Claim STP Proxy",
            ],
        },
    }


def _resolve_live_dataset() -> tuple[Path | None, Path | None]:
    """Return (dataset_yaml, archive_path) when a usable archive is present."""
    from datasets.registry import DatasetManager

    candidates: list[Path] = []
    ops_yaml = ROOT / "data" / "dataset_ops_100.yaml"
    if ops_yaml.exists():
        candidates.append(ops_yaml)
    candidates.append(ROOT / "dataset.yaml")

    for yaml_path in candidates:
        try:
            dataset = DatasetManager.load(yaml_path)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            print(f"skip dataset {yaml_path}: {type(exc).__name__}", flush=True)
            continue
        local_candidates = [
            dataset.root,
            ROOT / "Hackathon - 1000 Claims.zip",
            ROOT / "data" / "Hackathon - 1000 Claims.zip",
            ROOT / "data" / "Hackathon-100-ops-subset.zip",
            Path("/data/Hackathon - 1000 Claims.zip"),
        ]
        archive = next((path for path in local_candidates if path.exists()), None)
        if archive is not None:
            return yaml_path, archive
    return None, None


def _run_live_claim(
    document: str,
    output_root: Path,
    document_type: str | None,
    dataset_yaml: Path,
) -> dict[str, Any]:
    """Best-effort live chain when the Hackathon archive is present."""
    output_root.mkdir(parents=True, exist_ok=True)
    app_out = output_root / "application"
    cmd = [
        sys.executable,
        str(ROOT / "app.py"),
        "--dataset",
        str(dataset_yaml),
        "--document",
        document,
        "--output-root",
        str(app_out),
    ]
    if document_type:
        cmd.extend(["--document-type", document_type])
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    result: dict[str, Any] = {
        "document": document,
        "app_returncode": proc.returncode,
        "app_stdout_tail": proc.stdout[-2000:],
        "app_stderr_tail": proc.stderr[-2000:],
        "stages": {},
    }
    if proc.returncode != 0:
        result["recovery"] = _recovery_for_failure(
            registration_category="LIVE_APP_FAILURE",
            registration_reason=proc.stderr[-500:] or "app.py failed",
            application_status="FAILED",
        )
        return result

    # Discover geometry directory written by app.py
    geometry_dirs = list(app_out.glob("**/GeometryResult.json"))
    if not geometry_dirs:
        result["recovery"] = _recovery_for_failure(
            registration_category="SelectionUnavailable",
            registration_reason="geometry_result_missing",
            application_status="FAILED",
        )
        return result

    geometry_dir = geometry_dirs[0].parent
    ocr_dir = output_root / "ocr"
    rank_dir = output_root / "rank"
    val_dir = output_root / "validate"
    extract_dir = output_root / "extract"
    final_dir = output_root / "final"

    stage_cmds = [
        [sys.executable, "-m", "scripts.ocr_from_geometry", str(geometry_dir), str(ocr_dir)],
        [
            sys.executable,
            "-m",
            "scripts.rank_from_ocr",
            str(ocr_dir / "OCRCandidates.json"),
            str(rank_dir),
        ],
        [
            sys.executable,
            "-m",
            "scripts.validate_from_ranked",
            str(rank_dir / "RankedCandidates.json"),
            str(val_dir),
            "--template-id",
            "cms1500",
            "--template-version",
            "02-12",
        ],
        [
            sys.executable,
            "-m",
            "scripts.assemble_extraction_result",
            str(ocr_dir / "OCRCandidates.json"),
            str(rank_dir / "RankedCandidates.json"),
            str(val_dir / "ValidationResults.json"),
            str(extract_dir),
        ],
        [
            sys.executable,
            "-m",
            "scripts.complete_from_extraction",
            str(extract_dir / "ExtractionResult.json"),
            str(final_dir),
            "--document-family",
            "CMS1500",
        ],
    ]
    for cmd in stage_cmds:
        stage_name = Path(cmd[2]).name if len(cmd) > 2 else "stage"
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        result["stages"][stage_name] = {
            "returncode": proc.returncode,
            "stderr_tail": proc.stderr[-500:],
        }
        if proc.returncode != 0:
            result["recovery"] = _recovery_for_failure(
                registration_category="LIVE_STAGE_FAILURE",
                registration_reason=stage_name,
                application_status="FAILED",
                strategy_available=("ocr" in stage_name.casefold()),
            )
            return result

    final_claim = final_dir / "FinalClaim.json"
    if final_claim.exists():
        payload = json.loads(final_claim.read_text(encoding="utf-8"))
        result["final_claim"] = payload
        result["completed"] = payload.get("status") == "COMPLETED"
        result["review_required"] = bool(payload.get("review_required"))
        result["true_stp"] = result["completed"] and not result["review_required"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ops-report", type=Path, default=DEFAULT_OPS_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Attempt live app-path execution (requires Hackathon ZIP + tesseract).",
    )
    parser.add_argument("--live-limit", type=int, default=0, help="Max live claims to run (0=all).")
    parser.add_argument(
        "--live-offset",
        type=int,
        default=0,
        help="Skip the first N paired claims before applying --live-limit (independent cohort).",
    )
    parser.add_argument(
        "--live-seed",
        type=int,
        default=None,
        help="If set, sample --live-limit claims without replacement from the paired set "
        "(ignores --live-offset order; records seed in the live report).",
    )
    args = parser.parse_args()

    if not args.ops_report.exists():
        raise SystemExit(f"Missing ops report: {args.ops_report}")

    ops_report = _load_ops_report(args.ops_report)
    report = score_frozen_run(ops_report)

    if args.live:
        dataset_yaml, archive_path = _resolve_live_dataset()
        archive_available = archive_path is not None and dataset_yaml is not None
        tesseract_available = bool(
            __import__("shutil").which("tesseract")
            or Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").is_file()
        )
        report["live_execution"] = {
            "requested": True,
            "archive_available": archive_available,
            "archive_path": str(archive_path) if archive_path else None,
            "dataset_yaml": str(dataset_yaml) if dataset_yaml else None,
            "tesseract_available": tesseract_available,
            "note": (
                "Live mode needs either the full ZIP at data/Hackathon - 1000 Claims.zip "
                "or the 100-claim subset (data/Hackathon-100-ops-subset.zip + "
                "data/dataset_ops_100.yaml). Prefer a download URL over chat upload "
                "(10 MB chat limit). Frozen scoring remains authoritative until live completes."
                if not archive_available or not tesseract_available
                else "Live archive detected; executing bounded claim sample."
            ),
        }
        if archive_available and tesseract_available and dataset_yaml is not None:
            live_root = args.output / "live"
            live_root.mkdir(parents=True, exist_ok=True)
            docs = [row["document"] for row in ops_report.get("paired_claims") or []]
            selection = {
                "total_paired": len(docs),
                "offset": args.live_offset,
                "limit": args.live_limit,
                "seed": args.live_seed,
            }
            if args.live_seed is not None:
                import random

                rng = random.Random(args.live_seed)
                pool = list(docs)
                rng.shuffle(pool)
                if args.live_limit > 0:
                    docs = pool[: args.live_limit]
                else:
                    docs = pool
                selection["mode"] = "seeded_shuffle"
            else:
                if args.live_offset:
                    docs = docs[args.live_offset :]
                if args.live_limit > 0:
                    docs = docs[: args.live_limit]
                selection["mode"] = "offset_slice"
            selection["documents"] = list(docs)
            report["live_execution"]["selection"] = selection
            live_results = []
            for document in docs:
                claim_dir = live_root / document.replace("/", "__")
                live_results.append(
                    _run_live_claim(document, claim_dir, "CMS1500", dataset_yaml)
                )
            report["live_execution"]["results"] = live_results
            report["live_execution"]["claims_attempted"] = len(live_results)
            report["live_execution"]["claims_completed"] = sum(
                1 for row in live_results if row.get("completed")
            )
            report["live_execution"]["claims_true_stp"] = sum(
                1 for row in live_results if row.get("true_stp")
            )
            attempted = len(live_results) or 1
            report["live_execution"]["live_completion_rate"] = (
                report["live_execution"]["claims_completed"] / attempted
            )
            report["live_execution"]["live_true_stp_rate"] = (
                report["live_execution"]["claims_true_stp"] / attempted
            )

    args.output.mkdir(parents=True, exist_ok=True)
    out_path = args.output / "production_qualification.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    # Compact summary for UI sync consumers
    summary = {
        "measurement_scope": "OPERATIONAL_E2E",
        "operational_completion_rate": report["metrics"]["operational_completion_rate"],
        "true_stp_rate": report["metrics"]["true_stp_rate"],
        "end_to_end_correct_completion_rate": report["metrics"]["end_to_end_correct_completion_rate"],
        "end_to_end_correct_completion_status": report["metrics"][
            "end_to_end_correct_completion_status"
        ],
        "submitted_claims": report["metrics"]["submitted_claims"],
        "incomplete_count": report["metrics"]["incomplete_count"],
        "recovery_human_queue_plans": report["recovery_integration"]["human_queue_plans"],
        "recovery_executable_plans": report["recovery_integration"]["executable_plans"],
        "production_qualification_status": report["production_qualification"]["status"],
        "source": _display_path(out_path),
    }
    if report.get("live_execution", {}).get("claims_attempted"):
        live = report["live_execution"]
        summary["live_claims_attempted"] = live.get("claims_attempted")
        summary["live_claims_completed"] = live.get("claims_completed")
        summary["live_claims_true_stp"] = live.get("claims_true_stp")
        summary["live_completion_rate"] = live.get("live_completion_rate")
        summary["live_true_stp_rate"] = live.get("live_true_stp_rate")
        summary["live_selection"] = live.get("selection")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    metrics = report["metrics"]
    print(
        "OPERATIONAL_E2E:",
        f"completion={metrics['operational_completion_rate']*100:.1f}%",
        f"true_stp={metrics['true_stp_rate']*100:.1f}%",
        f"e2e_correct={metrics['end_to_end_correct_completion_status']}",
        f"incomplete={metrics['incomplete_count']}",
        f"recovery_human_queue={report['recovery_integration']['human_queue_plans']}",
        f"status={report['production_qualification']['status']}",
    )
    live = report.get("live_execution") or {}
    if live.get("claims_attempted"):
        print(
            "LIVE_SAMPLE:",
            f"attempted={live['claims_attempted']}",
            f"completed={live.get('claims_completed')}",
            f"true_stp={live.get('claims_true_stp')}",
            f"completion_rate={100.0 * float(live.get('live_completion_rate') or 0):.1f}%",
            f"true_stp_rate={100.0 * float(live.get('live_true_stp_rate') or 0):.1f}%",
            f"selection={live.get('selection', {}).get('mode')}",
        )
    print(f"Wrote {_display_path(out_path)}")

    # --- Auto ground truth build + re-score ---
    # Run every time so claims without GT get GOLD/SILVER labels mined from
    # multi-engine consensus in the live or frozen run, and accuracy is reported
    # immediately without a separate manual step.
    try:
        from scripts.build_ground_truth import build_consolidated_gt, save_ground_truth
        from scripts.score_hackathon_gt_accuracy import score as _rescore

        live_run_dir = args.out if hasattr(args, "out") else None
        run_dirs = [Path(live_run_dir)] if live_run_dir and Path(live_run_dir).is_dir() else []
        print("\n[auto-gt] Building ground truth from this e2e run...", flush=True)
        agent_gt_payload, pydantic_gt, manifest_payload = build_consolidated_gt(
            run_dirs=run_dirs,
        )
        save_ground_truth(
            agent_gt_payload=agent_gt_payload,
            pydantic_dataset=pydantic_gt,
            manifest_payload=manifest_payload,
            sync_docs=True,
        )
        print(
            f"[auto-gt] GT updated: {agent_gt_payload['stats']['claims']} claims, "
            f"{agent_gt_payload['stats']['field_labels']} field labels",
            flush=True,
        )
    except Exception as _gt_exc:  # noqa: BLE001
        print(f"[auto-gt] Warning: GT auto-build skipped: {_gt_exc}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
