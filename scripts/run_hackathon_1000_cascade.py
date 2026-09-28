#!/usr/bin/env python3
"""Run field-cascade ops on the Hackathon Claims corpus (cascade strategy from YAML).

Operational completion / true-STP / HITL evaluation (no field-level GT).
Pipeline per claim: app.py (register+geometry+recovery ladder) → ocr → rank →
validate → assemble → complete (E3 from registration_report).

Resume-safe: JSONL ledger skips finished claim_ids.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.extraction_recovery.gap_taxonomy import classify_field_gap

DEFAULT_ZIP = ROOT / "data" / "Hackathon - 1000 Claims.zip"
DEFAULT_DATASET = ROOT / "dataset.yaml"
DEFAULT_OUT = ROOT / "evaluation_results" / "hackathon_1000_cascade_v12"

CRITICAL = (
    "patient_dob",
    "total_charge",
    "patient_name",
    "insured_id_number",
    "insured_name",
)
AUTO = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"}
CASCADE_ENGINES = ("paddleocr", "rapidocr", "tesseract", "tesseract_digits")


def _ocr_pool_enabled() -> bool:
    raw = (os.environ.get("CDP_OCR_WORKER_POOL") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def _app_pool_enabled() -> bool:
    raw = (os.environ.get("CDP_APP_WORKER_POOL") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def _ocr_pool_job(geometry_dir: str, output_dir: str) -> tuple[int, str]:
    """Long-lived pool worker entry — keeps Paddle/Rapid warm across claims."""
    try:
        from scripts.ocr_from_geometry import run as ocr_run

        result = ocr_run(geometry_dir, output_dir)
        status = result.get("status")
        payload = json.dumps(
            {
                "status": status,
                "fields": len(result.get("fields") or []),
                "candidates": sum(
                    len(row.get("candidates") or [])
                    for row in (result.get("fields") or [])
                ),
            }
        )
        return (0 if status == "COMPLETED" else 1, payload)
    except Exception as exc:  # noqa: BLE001
        return (1, f"{type(exc).__name__}: {exc}")


def _app_pool_job(
    dataset_yaml: str,
    document: str,
    document_type: str,
    output_root: str,
) -> tuple[int, str]:
    """Long-lived registration worker — amortize imports + template SIFT cache."""
    import logging

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(message)s",
        force=True,
    )
    logging.getLogger("cdp.registration.telemetry").setLevel(logging.ERROR)
    try:
        from app import process_one

        _path, state = process_one(
            dataset_yaml,
            document=document,
            output_root=output_root,
            document_type=document_type or None,
        )
        status = state.get("status")
        return (0 if status == "SUCCESS" else 1, json.dumps({"status": status}))
    except Exception as exc:  # noqa: BLE001
        return (1, f"{type(exc).__name__}: {exc}")


def _shutdown_process_pool(pool: ProcessPoolExecutor | None) -> None:
    """Terminate pool workers — Paddle/ORT atexit finalizers can hang on join."""
    if pool is None:
        return
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except TypeError:
        pool.shutdown(wait=False)
    processes = getattr(pool, "_processes", None) or {}
    for proc in list(processes.values()):
        try:
            if proc.is_alive():
                proc.terminate()
        except Exception:  # noqa: BLE001, S110
            pass


def _spawn_pool(n_workers: int) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(
        max_workers=max(1, n_workers),
        mp_context=__import__("multiprocessing").get_context("spawn"),
        initializer=_pool_worker_silence_stdio,
    )


def _pool_worker_silence_stdio() -> None:
    """Keep ProcessPool workers from flooding the parent stdout pipe.

    TrOCR/transformers warnings on inherited stdout filled the tee pipe and
    blocked the cascade main thread (~27 claims finished but never ledgered).
    """
    import os
    import sys

    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            # Dup over stdio fds so the redirect outlives this with-block.
            os.dup2(devnull.fileno(), sys.stdout.fileno())
            os.dup2(devnull.fileno(), sys.stderr.fileno())
    except OSError:
        pass
    # Spawn workers do not inherit the parent process's in-memory factories.
    # Without this, Azure DI charge residual raises AZURE_DI_FACTORY_UNCONFIGURED.
    from workers.ocr_engine_factories import wire_package_ocr_providers

    wire_package_ocr_providers()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _bundle_id(document: str) -> str:
    """Group + claim family (e.g. Group A/M048DJJM) — multipage claim bundle."""
    text = (document or "").replace("\\", "/")
    if "/" in text:
        group, name = text.split("/", 1)
    else:
        group, name = "", text
    family = name.split(".")[0] if name else ""
    return f"{group}/{family}" if group else family


def _group_id(document: str) -> str:
    text = (document or "").replace("\\", "/")
    return text.split("/", 1)[0] if "/" in text else "UNKNOWN"


def _probe_ocr_engines() -> dict[str, Any]:
    """One-shot live probe: paddle / rapid / tesseract must OBSERVE, not UNAVAILABLE."""
    from PIL import Image, ImageDraw, ImageFont

    from packages.ocr_router import OCRRouter, OCRRouteRequest
    from workers.ocr_engine_factories import wire_package_ocr_providers

    wire_package_ocr_providers()
    image = Image.new("L", (220, 64), 255)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None
    draw.text((12, 18), "HELLO 123", fill=0, font=font)
    router = OCRRouter(lambda _attempt: True)
    result = router.route(
        OCRRouteRequest(
            image,
            (0, 0, image.width, image.height),
            engine_order=("paddleocr", "rapidocr", "tesseract"),
        )
    )
    # Force tesseract even when confirmation already satisfied.
    tess_only = router.route(
        OCRRouteRequest(
            image,
            (0, 0, image.width, image.height),
            engine_order=("tesseract",),
        )
    )
    observed = {
        attempt.engine: attempt.reason for attempt in result.attempts
    }
    observed["tesseract"] = (
        tess_only.selected.reason
        if tess_only.selected is not None
        else next((a.reason for a in tess_only.attempts if a.engine == "tesseract"), "MISSING")
    )
    return {
        "paddleocr": observed.get("paddleocr", "MISSING"),
        "rapidocr": observed.get("rapidocr", "MISSING"),
        "tesseract": observed.get("tesseract", "MISSING"),
        "all_observed": all(
            observed.get(name) == "OBSERVED"
            for name in ("paddleocr", "rapidocr", "tesseract")
        ),
        "tesseract_text": (
            " ".join(line.text for line in tess_only.selected.observation.lines)
            if tess_only.selected and tess_only.selected.observation
            else ""
        ),
    }


def _ocr_engine_stats(claim_out: Path) -> dict[str, Any]:
    """Count cascade OCR attempt outcomes from OCRCandidates.json."""
    path = claim_out / "ocr" / "OCRCandidates.json"
    attempts: Counter[str] = Counter()
    observed: Counter[str] = Counter()
    unavailable: Counter[str] = Counter()
    if not path.exists():
        return {
            "engines_attempted": {},
            "engines_observed": {},
            "engines_unavailable": {},
            "cascade_healthy": False,
            "tesseract_observed": 0,
            "tesseract_unavailable": 0,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "engines_attempted": {},
            "engines_observed": {},
            "engines_unavailable": {},
            "cascade_healthy": False,
            "tesseract_observed": 0,
            "tesseract_unavailable": 0,
        }
    for field in payload.get("fields") or []:
        for attempt in field.get("attempts") or []:
            engine = str(attempt.get("engine") or "")
            if engine not in CASCADE_ENGINES:
                continue
            attempts[engine] += 1
            reason = str(attempt.get("reason") or "")
            if reason == "OBSERVED":
                observed[engine] += 1
            elif reason == "UNAVAILABLE":
                unavailable[engine] += 1
    # Healthy when primary paddle + confirmation rapid observed, and tesseract
    # never reported UNAVAILABLE (fill may be unused when first two succeed).
    healthy = (
        observed.get("paddleocr", 0) > 0
        and observed.get("rapidocr", 0) > 0
        and unavailable.get("tesseract", 0) == 0
    )
    return {
        "engines_attempted": dict(attempts),
        "engines_observed": dict(observed),
        "engines_unavailable": dict(unavailable),
        "cascade_healthy": healthy,
        "tesseract_observed": observed.get("tesseract", 0)
        + observed.get("tesseract_digits", 0),
        "tesseract_unavailable": unavailable.get("tesseract", 0),
    }

def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _list_documents(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as zf:
        docs = [name for name in zf.namelist() if not name.endswith("/")]
    return sorted(docs)


def _load_done(ledger: Path) -> set[str]:
    latest: dict[str, dict] = {}
    if not ledger.exists():
        return set()
    with ledger.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            claim_id = str(row.get("claim_id") or "").strip()
            if claim_id:
                latest[claim_id] = row
    return {
        claim_id for claim_id, row in latest.items()
        if row.get("finished") and row.get("disposition") in {
            "TRUE_STP", "HITL", "REGISTRATION_FAILED"
        }
    }


def _append_ledger(ledger: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    with lock, ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _claim_slug(document: str) -> str:
    return document.replace("/", "__")


def _prune_document_json(app_out: Path) -> None:
    """Drop oversized document.json; keep registration_trace for OCR."""
    for path in app_out.glob("**/document.json"):
        try:
            path.unlink()
        except OSError:
            pass


def _prune_trace(app_out: Path) -> None:
    for path in app_out.glob("**/registration_trace.json"):
        try:
            path.unlink()
        except OSError:
            pass


def _cms1500_template_version() -> str:
    """Pin finish/validate to the same CMS-1500 template the release registered."""
    try:
        import yaml

        from packages.release_selection import active_release_from_env, select_release

        manifest_path = select_release(active_release_from_env())
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        versions = manifest.get("template_versions") or {}
        version = str(versions.get("cms1500") or "").strip()
        if version:
            return version
    except Exception:  # noqa: BLE001
        pass
    release = (os.environ.get("CDP_PIPELINE_RELEASE") or "").strip().casefold()
    if release in {"extraction-v3", "v3"}:
        return "03"
    return "02-12"


def _stage_env() -> dict[str, str]:
    """Limit nested BLAS/OpenMP threads so parallel claim workers do not thrash."""
    env = dict(os.environ)
    for key in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "FLAGS_num_threads",
    ):
        env.setdefault(key, "1")
    # Default STP eval to critical-field OCR only (~5× fewer ROIs). Override
    # with CDP_OCR_FIELD_SCOPE=all for full-form extraction.
    env.setdefault("CDP_OCR_FIELD_SCOPE", "stp_critical")
    # SELECTIVE_E2_ONLY: stop after field-shaped primary (skip dual-engine tax).
    env.setdefault("CDP_OCR_SELECTIVE_CONFIRM", "1")
    # Paddle warm inference is ~50× faster than Rapid on CPU; use as STP-eval
    # primary while Rapid remains confirmation when primary is unshaped.
    env.setdefault("CDP_OCR_PRIMARY_OVERRIDE", "paddleocr")
    # Prefer inference-scoped lock: unzip/warp/JSON overlap across workers while
    # Paddle/Rapid critical sections still serialize. Process scope was a
    # conservative fallback that inflated multi-worker claim wall.
    env.setdefault("CDP_OCR_LOCK", "1")
    env.setdefault("CDP_OCR_LOCK_SCOPE", "inference")
    # Skip multi-MB keypoint/match dumps + full-image SHA256 on registration.
    env.setdefault("CDP_REGISTRATION_VERBOSE_TELEMETRY", "0")
    # Long-lived workers amortize cold start (override with =0 for subprocess-per-claim).
    env.setdefault("CDP_OCR_WORKER_POOL", "1")
    env.setdefault("CDP_APP_WORKER_POOL", "1")
    # TrOCR then Claude for DOB. Charge Document Intelligence is on (cdp43).
    env.setdefault("CDP_TROCR_DOB_RESIDUAL", "1")
    env.setdefault("CDP_AZURE_DI_DOB_RESIDUAL", "0")
    env.setdefault("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    env.setdefault("CDP_AZURE_DI_CHARGE_CORROBORATE", "1")
    env.setdefault("CDP_AZURE_DI_CHARGE_ACCEPT", "1")
    env.setdefault("CDP_GPT4O_CROP_RESIDUAL", "1")
    env.setdefault("CDP_GPT4O_CROP_ACCEPT", "1")
    # Cap empty-box-28 line vision recoveries — each line is a network round-trip.
    env.setdefault("CDP_GPT4O_EMPTY_FINANCE", "1")
    env.setdefault("CDP_GPT4O_EMPTY_FINANCE_MAX_LINES", "2")
    # Serialize Claude/gpt-4o crop residuals across parallel claim workers.
    env.setdefault("CDP_VLM_CROP_LOCK", "1")
    env.setdefault("CDP_VLM_CROP_LOCK_PATH", "/tmp/cdp_vlm_crop.lock")
    env.setdefault("CDP_VLM_CROP_TIMEOUT_SECONDS", "35")
    # Prefer Claude Sonnet for crop residual when configured (override via env).
    env.setdefault("CDP_CROP_VLM_PROVIDER", "claude")
    env.setdefault("CDP_CONFLICT_AGENT", "1")
    env.setdefault("CDP_DOB_RESIDUAL_SKIP_IF_LOCAL_SHAPED", "1")
    # SuperPoint+LightGlue for catastrophic REG — process-lifetime singleton
    # amortizes cold load; trail-aware near-miss recovers most STP regressions
    # without torch. Keep ON for STP; opt-out with =0 for pure latency smoke.
    env.setdefault("CDP_LEARNED_MATCHER", "1")
    # Name Rapid confirm gate (was 0.88 — nearly always confirmed).
    env.setdefault("CDP_OCR_NAME_CONFIRM_MIN_CONF", "0.80")
    env.setdefault("CDP_AZURE_DI_PAGE_CORNERS", "0")
    env.setdefault("CDP_PIPELINE_RELEASE", "extraction-v3")
    env.setdefault("CDP_AZURE_DI_MIN_INTERVAL_SECONDS", "0")
    env.setdefault("CDP_AZURE_DI_SLOT_PATH", "/tmp/cdp-azure-di-slot")
    env.setdefault("CDP_AZURE_DI_SERVICE_LINE_BUDGET", "1")
    env.setdefault(
        "CDP_AZURE_DI_METER_PATH",
        str(ROOT / "evaluation_results" / "azure_di_meter.jsonl"),
    )
    return env


@contextmanager
def _ocr_process_lock():
    """Whole-process OCR lock only when CDP_OCR_LOCK_SCOPE=process.

    Default cascade scope is ``inference`` — Paddle/Rapid critical sections take
    the flock inside ``packages.ocr_runtime_lock``, so unzip/warp/JSON overlap.
    """
    from packages.ocr_runtime_lock import ocr_process_lock

    with ocr_process_lock():
        yield


def _run_stage(cmd: list[str], log_path: Path) -> tuple[int, str]:
    """Stream stdout/stderr to a file to avoid pipe deadlocks with verbose app.py."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log_handle:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=_stage_env(),
            check=False,
        )
    tail = ""
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
    except OSError:
        pass
    return proc.returncode, tail


def _summarize_final(claim_out: Path) -> dict[str, Any]:
    final = json.loads((claim_out / "final" / "FinalClaim.json").read_text(encoding="utf-8"))
    decision = final.get("decision") or final
    fields: dict[str, Any] = {}
    for fd in decision.get("field_decisions") or []:
        name = fd.get("field_name")
        if name in CRITICAL:
            fields[name] = {
                "disp": fd.get("disposition"),
                "value": fd.get("selected_value"),
                "reasons": list(fd.get("reason_codes") or [])[:12],
            }
    ocr_path = claim_out / "ocr" / "OCRCandidates.json"
    service_line_charges = 0
    document_family = None
    allows_cms_geometry = None
    document_finance = None
    if ocr_path.exists():
        ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
        service_line_charges = sum(
            1
            for line in (ocr.get("service_lines") or [])
            if line.get("status") == "OBSERVED" and line.get("charges")
        )
        document_family = ocr.get("document_family")
        allows_cms_geometry = ocr.get("allows_cms_geometry")
        document_finance = ocr.get("document_finance")
        if document_family is None:
            pkg = ocr.get("package_intelligence") or {}
            pages = pkg.get("pages") or []
            if pages:
                document_family = pages[0].get("page_class")
                allows_cms_geometry = pages[0].get("allows_cms_geometry")

    blockers = list(decision.get("critical_blockers") or [])
    gaps = []
    for blocker in blockers:
        field_info = fields.get(blocker) or {}
        observed_text = str(field_info.get("value") or "")
        gap = classify_field_gap(
            blocker,
            observed_text=observed_text,
            accepted=False,
            service_line_charges=service_line_charges,
            reason_codes=field_info.get("reasons") or [],
        )
        if gap is not None:
            gaps.append(
                {
                    "field": gap.field_name,
                    "gap_class": gap.gap_class,
                    "action": gap.action,
                    "evidence": gap.evidence,
                }
            )
    completed = final.get("status") == "COMPLETED"
    review_required = bool(final.get("review_required") or decision.get("review_required"))
    engine_stats = _ocr_engine_stats(claim_out)
    return {
        "completed": completed,
        "review_required": review_required,
        "true_stp": completed and not review_required,
        "critical_blockers": blockers,
        "fields": fields,
        "gap_classes": gaps,
        "service_line_charges": service_line_charges,
        "claim_status": decision.get("claim_status") or final.get("claim_status"),
        "ocr_engine_stats": engine_stats,
        "document_family": document_family,
        "allows_cms_geometry": allows_cms_geometry,
        "document_finance": document_finance,
    }


def _process_one(
    *,
    document: str,
    out_dir: Path,
    dataset_yaml: Path,
    document_type: str,
    keep_heavy: bool,
    ocr_executor: Any = None,
    app_executor: Any = None,
) -> dict[str, Any]:
    claim_id = _claim_slug(document)
    claim_out = out_dir / "claims" / claim_id
    if claim_out.exists():
        shutil.rmtree(claim_out)
    claim_out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    logs = claim_out / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    app_out = claim_out / "application"

    if app_executor is not None:
        try:
            rc, tail = app_executor.submit(
                _app_pool_job,
                str(dataset_yaml),
                document,
                document_type,
                str(app_out),
            ).result()
        except Exception as exc:  # noqa: BLE001
            rc, tail = 1, f"{type(exc).__name__}: {exc}"
        try:
            (logs / "app.log").write_text(tail or "", encoding="utf-8")
        except OSError:
            pass
    else:
        rc, tail = _run_stage(
            [
                sys.executable,
                str(ROOT / "app.py"),
                "--dataset",
                str(dataset_yaml),
                "--document",
                document,
                "--document-type",
                document_type,
                "--output-root",
                str(app_out),
            ],
            logs / "app.log",
        )

    geometry_hits = list(app_out.glob("**/GeometryResult.json"))
    if not geometry_hits:
        reason = "geometry_missing"
        for report in app_out.glob("**/registration_report.json"):
            try:
                payload = json.loads(report.read_text(encoding="utf-8"))
                reason = (
                    payload.get("reason")
                    or (payload.get("registration") or {}).get("reason")
                    or reason
                )
            except (OSError, json.JSONDecodeError):
                pass
            break
        for doc_json in app_out.glob("**/document.json"):
            try:
                payload = json.loads(doc_json.read_text(encoding="utf-8"))
                reg = payload.get("registration") or {}
                reason = reg.get("reason") or reason
            except (OSError, json.JSONDecodeError, ValueError):
                pass
            break
        if not keep_heavy:
            _prune_document_json(app_out)
            _prune_trace(app_out)
        disposition = "REGISTRATION_FAILED"
        if rc != 0 and reason == "geometry_missing":
            disposition = "APP_FAILURE"
        # Hard blind: some REG pages are freeform (no CMS grid). Template
        # geometry cannot recover — fall back to Azure DI page text (+ optional
        # gpt-4o text agent) for critical fields instead of a geometry VLM.
        unstructured_meta: dict[str, Any] | None = None
        if disposition == "REGISTRATION_FAILED":
            try:
                from packages.extraction_recovery.unstructured_reg_fallback import (
                    run_unstructured_reg_fallback,
                    unstructured_reg_fallback_enabled,
                )
            except ImportError:
                run_unstructured_reg_fallback = None  # type: ignore
                unstructured_reg_fallback_enabled = lambda: False  # type: ignore
            if unstructured_reg_fallback_enabled() and run_unstructured_reg_fallback is not None:
                page_image = None
                try:
                    # Prefer zip bytes via existing dataset helper if present.
                    from io import BytesIO
                    from zipfile import ZipFile

                    from PIL import Image as _PILImage

                    zip_path = Path(os.environ.get("CDP_HACKATHON_ZIP") or ROOT / "data" / "Hackathon - 1000 Claims.zip")
                    if zip_path.exists():
                        with ZipFile(zip_path) as zf:
                            page_image = _PILImage.open(BytesIO(zf.read(document))).convert("RGB")
                except (OSError, ValueError, KeyError, RuntimeError):
                    page_image = None
                if page_image is not None:
                    fb = run_unstructured_reg_fallback(page_image)
                    try:
                        from packages.extraction_recovery.independent_case_router import (
                            classify_independent_case,
                            promote_unstructured_fields,
                        )
                    except ImportError:
                        classify_independent_case = None  # type: ignore
                        promote_unstructured_fields = None  # type: ignore
                    route_meta: dict[str, Any] | None = None
                    if classify_independent_case is not None:
                        route = classify_independent_case(
                            fb.di_text or "",
                            registration_ok=False,
                        )
                        route_meta = route.to_dict()
                        if route.path.value == "MAILROOM_REG":
                            disposition = "REGISTRATION_FAILED"
                            unstructured_meta = {
                                "attempted": fb.attempted,
                                "reason": "MAILROOM_OR_FAX",
                                "agent_used": fb.agent_used,
                                "fields": {},
                                "route": route_meta,
                            }
                        else:
                            disposition, blockers = promote_unstructured_fields(fb.fields)
                            unstructured_meta = {
                                "attempted": fb.attempted,
                                "reason": fb.reason,
                                "agent_used": fb.agent_used,
                                "fields": dict(fb.fields),
                                "route": route_meta,
                                "critical_blockers": blockers if disposition == "HITL" else None,
                            }
                    else:
                        # Legacy promotion if router unavailable.
                        unstructured_meta = {
                            "attempted": fb.attempted,
                            "reason": fb.reason,
                            "agent_used": fb.agent_used,
                            "fields": dict(fb.fields),
                        }
                        required = {
                            "patient_name",
                            "patient_dob",
                            "insured_id_number",
                            "total_charge",
                        }
                        if required.issubset(fb.fields):
                            disposition = "TRUE_STP"
                        elif fb.fields:
                            disposition = "HITL"
                    with contextlib.suppress(OSError, AttributeError, ValueError):
                        page_image.close()
        unstructured_hitl = (
            disposition == "HITL"
            and unstructured_meta is not None
            and bool((unstructured_meta or {}).get("fields"))
        )
        row = {
            "finished": True,
            "claim_id": claim_id,
            "document": document,
            "bundle_id": _bundle_id(document),
            "group_id": _group_id(document),
            "registration_ok": False,
            "allows_cms_geometry": False,
            # Unstructured recoveries are completed without CMS geometry.
            "completed": disposition in {"TRUE_STP", "HITL"},
            "true_stp": disposition == "TRUE_STP",
            "disposition": disposition,
            "registration_reason": reason,
            "hitl_track": "UNSTRUCTURED_DI" if unstructured_hitl else None,
            "critical_blockers": (
                list(
                    (unstructured_meta or {}).get("critical_blockers")
                    or [
                        f
                        for f in (
                            "patient_name",
                            "patient_dob",
                            "insured_id_number",
                            "total_charge",
                        )
                        if f not in (unstructured_meta or {}).get("fields", {})
                    ]
                )
                if unstructured_hitl
                else None
            ),
            "unstructured_reg_fallback": unstructured_meta,
            "app_returncode": rc,
            "error": tail if disposition == "APP_FAILURE" else None,
            "elapsed_sec": round(time.time() - started, 3),
            "ts": _utc_now(),
            "strategy_id": "independent-case-router-v1"
            if unstructured_meta and unstructured_meta.get("attempted")
            else "field-cascade-v12",
        }
        _write_json(claim_out / "result.json", row)
        return row

    geometry_dir = geometry_hits[0].parent
    if not keep_heavy:
        _prune_document_json(app_out)

    stages = [
        (
            "ocr",
            [
                sys.executable,
                "-m",
                "scripts.ocr_from_geometry",
                str(geometry_dir),
                str(claim_out / "ocr"),
            ],
        ),
        (
            "finish",
            [
                sys.executable,
                "-m",
                "scripts.finish_from_ocr",
                str(claim_out / "ocr" / "OCRCandidates.json"),
                str(claim_out),
                "--template-id",
                "cms1500",
                "--template-version",
                _cms1500_template_version(),
                "--document-family",
                "CMS1500",
            ],
        ),
    ]
    for stage_name, cmd in stages:
        if stage_name == "ocr" and ocr_executor is not None:
            logs.mkdir(parents=True, exist_ok=True)
            log_path = logs / "ocr.log"
            try:
                with _ocr_process_lock():
                    rc, tail = ocr_executor.submit(
                        _ocr_pool_job,
                        str(geometry_dir),
                        str(claim_out / "ocr"),
                    ).result()
            except Exception as exc:  # noqa: BLE001
                rc, tail = 1, f"{type(exc).__name__}: {exc}"
            try:
                log_path.write_text(tail or "", encoding="utf-8")
            except OSError:
                pass
        elif stage_name == "ocr":
            with _ocr_process_lock():
                rc, tail = _run_stage(cmd, logs / f"{stage_name}.log")
        else:
            rc, tail = _run_stage(cmd, logs / f"{stage_name}.log")
        if stage_name == "ocr" and not keep_heavy:
            # Trace is only required for OCR; free disk after that stage.
            _prune_trace(app_out)
        if rc != 0:
            row = {
                "finished": True,
                "claim_id": claim_id,
                "document": document,
                "bundle_id": _bundle_id(document),
                "group_id": _group_id(document),
                "registration_ok": True,
                "completed": False,
                "true_stp": False,
                "disposition": "STAGE_FAILURE",
                "failed_stage": stage_name,
                "error": tail,
                "ocr_engine_stats": _ocr_engine_stats(claim_out),
                "elapsed_sec": round(time.time() - started, 3),
                "ts": _utc_now(),
            }
            _write_json(claim_out / "result.json", row)
            return row

    try:
        summary = _summarize_final(claim_out)
    except Exception as exc:  # noqa: BLE001
        row = {
            "finished": True,
            "claim_id": claim_id,
            "document": document,
            "bundle_id": _bundle_id(document),
            "group_id": _group_id(document),
            "registration_ok": True,
            "completed": False,
            "true_stp": False,
            "disposition": "SUMMARY_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": round(time.time() - started, 3),
            "ts": _utc_now(),
        }
        _write_json(claim_out / "result.json", row)
        return row

    if summary["true_stp"]:
        disposition = "TRUE_STP"
        hitl_track = None
    elif summary["completed"]:
        # Field-ink HITL only when extraction completed and still needs review.
        disposition = "HITL"
        hitl_track = "FIELD_INK"
    else:
        # Completed=false must not be labeled HITL (that conflates incomplete
        # stages with field-ink review in rollups that key off disposition).
        disposition = "INCOMPLETE"
        hitl_track = None
    row = {
        "finished": True,
        "claim_id": claim_id,
        "document": document,
        "bundle_id": _bundle_id(document),
        "group_id": _group_id(document),
        "registration_ok": True,
        "completed": summary["completed"],
        "true_stp": summary["true_stp"],
        "review_required": summary["review_required"],
        "disposition": disposition,
        "hitl_track": hitl_track,
        "critical_blockers": summary["critical_blockers"],
        "fields": summary["fields"],
        "gap_classes": summary["gap_classes"],
        "service_line_charges": summary["service_line_charges"],
        "claim_status": summary["claim_status"],
        "ocr_engine_stats": summary.get("ocr_engine_stats") or {},
        "document_family": summary.get("document_family"),
        "allows_cms_geometry": summary.get("allows_cms_geometry"),
        "document_finance": summary.get("document_finance"),
        "strategy_id": "field-cascade-v12",
        "elapsed_sec": round(time.time() - started, 3),
        "ts": _utc_now(),
    }
    _write_json(claim_out / "result.json", row)
    return row


def _is_unstructured_reg_recovery(row: dict[str, Any]) -> bool:
    """True when REG was cleared via DI page-read fallback (no CMS geometry)."""
    meta = row.get("unstructured_reg_fallback")
    if not isinstance(meta, dict):
        return False
    if not meta.get("attempted") and not meta.get("fields"):
        return False
    return row.get("disposition") in {"TRUE_STP", "HITL"} and row.get("completed")


def _rollup_scope(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Operational STP / HITL rollup.

    Definitions (fail-closed, mutually exclusive dispositions):
      - TRUE_STP: (CMS registration_ok ∨ unstructured REG recovery) ∧ completed
      - HITL (field-ink): registration_ok ∧ completed ∧ field review
      - HITL (unstructured): REG fallback shaped some but not all critical fields
      - REGISTRATION_FAILED / STAGE_FAILURE / …: infra — NOT field HITL

    Primary rates use the completed denominator (CMS + unstructured recoveries):
      true_stp_rate = true_stp / completed
      hitl_rate     = field_ink_hitl / completed

    Never compute HITL as ``n - true_stp`` — that conflates registration and
    stage failures into review rate and understates STP vs completed claims.
    """
    n = len(rows)
    reg_ok = sum(1 for r in rows if r.get("registration_ok"))
    cms_completed = sum(1 for r in rows if r.get("completed") and r.get("registration_ok"))
    unstructured_completed = sum(1 for r in rows if _is_unstructured_reg_recovery(r))
    completed = cms_completed + unstructured_completed
    cms_true_stp = sum(
        1
        for r in rows
        if r.get("true_stp") and r.get("completed") and r.get("registration_ok")
    )
    unstructured_stp = sum(
        1
        for r in rows
        if r.get("true_stp")
        and _is_unstructured_reg_recovery(r)
        and not r.get("registration_ok")
    )
    true_stp = cms_true_stp + unstructured_stp
    # Field-ink HITL only — requires completed CMS-geometry extraction.
    # disposition==HITL alone is not enough (legacy unstructured-reg rows).
    field_hitl = sum(
        1
        for r in rows
        if r.get("disposition") == "HITL"
        and r.get("completed")
        and r.get("registration_ok")
        and r.get("hitl_track") != "UNSTRUCTURED_DI"
    )
    unstructured_hitl = sum(
        1
        for r in rows
        if r.get("disposition") == "HITL"
        and r.get("hitl_track") == "UNSTRUCTURED_DI"
        and _is_unstructured_reg_recovery(r)
    )
    hitl = field_hitl
    reg_hitl = sum(1 for r in rows if r.get("disposition") == "REGISTRATION_FAILED")
    infra_fail = sum(
        1
        for r in rows
        if r.get("disposition")
        in {
            "REGISTRATION_FAILED",
            "STAGE_FAILURE",
            "APP_FAILURE",
            "SUMMARY_ERROR",
            "WORKER_ERROR",
            "OCR_MISSING",
            "INCOMPLETE",
        }
    )
    # Invariant: among completed rows, STP + field HITL + unstructured HITL == completed.
    return {
        "n": n,
        "registration_ok": reg_ok,
        "registration_ok_rate": round(reg_ok / n, 6) if n else 0.0,
        "completed": completed,
        "completion_rate": round(completed / n, 6) if n else 0.0,
        "true_stp": true_stp,
        "cms_true_stp": cms_true_stp,
        "unstructured_reg_stp": unstructured_stp,
        "unstructured_reg_hitl": unstructured_hitl,
        # Primary operational STP: share of completed claims that auto-accept.
        "true_stp_rate": round(true_stp / completed, 6) if completed else 0.0,
        "true_stp_rate_of_completed": round(true_stp / completed, 6) if completed else 0.0,
        "true_stp_rate_of_all": round(true_stp / n, 6) if n else 0.0,
        "hitl": hitl,
        "field_ink_hitl": field_hitl,
        # Primary operational HITL: field-ink review share of completed claims.
        "hitl_rate": round(field_hitl / completed, 6) if completed else 0.0,
        "hitl_rate_of_completed": round(field_hitl / completed, 6) if completed else 0.0,
        # Of-all HITL is field-ink only — never (n - true_stp) / n.
        "hitl_rate_of_all": round(field_hitl / n, 6) if n else 0.0,
        "field_ink_hitl_rate_of_completed": (
            round(field_hitl / completed, 6) if completed else 0.0
        ),
        "registration_hitl": reg_hitl,
        "registration_hitl_rate": round(reg_hitl / n, 6) if n else 0.0,
        "infra_failures": infra_fail,
        "infra_failure_rate": round(infra_fail / n, 6) if n else 0.0,
        "misreported_hitl_as_n_minus_stp": round((n - true_stp) / n, 6) if n else 0.0,
    }


def _agent_gt_accuracy_block(run_dir: Path | None) -> dict[str, Any]:
    """Score cascade results against agent-confirmed labels when present.

    Hackathon ZIP has no vendor field GT. Confirmed SILVER/GOLD labels live in
    ``evaluation_data/hackathon_agent_gt/field_truth.json``.
    """
    unavailable = {
        "status": "UNAVAILABLE_NO_GROUND_TRUTH",
        "end_to_end_correct_completion_rate": None,
        "field_accuracy": None,
        "note": (
            "Hackathon 1000 ZIP has no vendor field-level labels. Provide "
            "evaluation_data/hackathon_agent_gt/field_truth.json to enable "
            "agent-confirmed accuracy scoring."
        ),
    }
    if run_dir is None:
        return unavailable
    gt_path = ROOT / "evaluation_data" / "hackathon_agent_gt" / "field_truth.json"
    if not gt_path.exists():
        return unavailable
    try:
        from scripts.score_hackathon_gt_accuracy import score as score_agent_gt

        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        scored = score_agent_gt(Path(run_dir), gt)
    except Exception as exc:  # noqa: BLE001
        return {
            **unavailable,
            "status": "AGENT_GT_SCORE_FAILED",
            "note": f"Agent GT present but scoring failed: {type(exc).__name__}: {exc}",
        }
    return {
        "status": "SCORED_VS_AGENT_CONFIRMED_LABELS",
        "gt_path": str(gt_path.relative_to(ROOT)),
        "claims_scored": scored.get("claims_scored"),
        "field_count": scored.get("field_count"),
        "exact_accuracy": scored.get("exact_accuracy"),
        "perfect_claim_exact_rate": scored.get("perfect_claim_exact_rate"),
        "false_accepts": scored.get("false_accepts"),
        "accepted_fields_scored": scored.get("accepted_fields_scored"),
        "accepted_field_precision": scored.get("accepted_field_precision"),
        "false_accept_rate": scored.get("false_accept_rate"),
        "quarantined_fields": scored.get("quarantined_fields"),
        "field_exact": scored.get("field_exact"),
        "true_stp_of_scored": scored.get("true_stp_of_scored"),
        "release_gate_eligible": scored.get("release_gate_eligible"),
        "release_gate_reason": scored.get("release_gate_reason"),
        "metric_contract": scored.get("metric_contract"),
        "end_to_end_correct_completion_rate": scored.get("perfect_claim_exact_rate"),
        "field_accuracy": scored.get("exact_accuracy"),
        "note": (
            "Accuracy vs agent-confirmed SILVER/GOLD labels (not vendor ZIP GT). "
            "Discrepancy ledger quarantines excluded from denominator. "
            "Not independent adjudicated truth — release_gate_eligible stays false."
        ),
    }


def _summarize(
    rows: list[dict[str, Any]], *, limit: int, run_dir: Path | None = None
) -> dict[str, Any]:
    n = len(rows)
    by_disp = Counter(str(r.get("disposition") or "UNKNOWN") for r in rows)
    blockers: Counter[str] = Counter()
    gaps: Counter[str] = Counter()
    auto = {name: 0 for name in CRITICAL}
    reg_reasons: Counter[str] = Counter()
    engine_attempted: Counter[str] = Counter()
    engine_observed: Counter[str] = Counter()
    engine_unavailable: Counter[str] = Counter()
    cascade_healthy = 0
    cascade_claims = 0
    tesseract_claims = 0
    by_bundle: dict[str, list[dict[str, Any]]] = {}
    by_group: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for b in row.get("critical_blockers") or []:
            blockers[str(b)] += 1
        for g in row.get("gap_classes") or []:
            gaps[str(g.get("gap_class"))] += 1
        if row.get("disposition") == "REGISTRATION_FAILED":
            reg_reasons[str(row.get("registration_reason") or "unknown")] += 1
        fields = row.get("fields") or {}
        for name in CRITICAL:
            disp = (fields.get(name) or {}).get("disp")
            if disp in AUTO:
                auto[name] += 1
        stats = row.get("ocr_engine_stats") or {}
        if stats:
            cascade_claims += 1
            if stats.get("cascade_healthy"):
                cascade_healthy += 1
            if int(stats.get("tesseract_observed") or 0) > 0:
                tesseract_claims += 1
            for eng, count in (stats.get("engines_attempted") or {}).items():
                engine_attempted[str(eng)] += int(count)
            for eng, count in (stats.get("engines_observed") or {}).items():
                engine_observed[str(eng)] += int(count)
            for eng, count in (stats.get("engines_unavailable") or {}).items():
                engine_unavailable[str(eng)] += int(count)
        doc = str(row.get("document") or "")
        bundle = str(row.get("bundle_id") or _bundle_id(doc))
        group = str(row.get("group_id") or _group_id(doc))
        by_bundle.setdefault(bundle, []).append(row)
        by_group.setdefault(group, []).append(row)

    overall = _rollup_scope(rows)
    completed = int(overall["completed"])
    return {
        "dataset": "DEVELOPMENT_DATASET_V1 / Hackathon - 1000 Claims.zip",
        "document_count_requested": limit,
        "document_count_evaluated": n,
        "strategy_id": "field-cascade-v12",
        **overall,
        "disposition_counts": dict(by_disp),
        "registration_failure_reasons": dict(reg_reasons),
        "critical_blockers": dict(blockers),
        "gap_classes": dict(gaps),
        "field_auto_of_completed": {
            name: f"{auto[name]}/{completed}" for name in CRITICAL
        },
        "field_auto_rate_of_completed": {
            name: round(auto[name] / completed, 6) if completed else 0.0
            for name in CRITICAL
        },
        "accuracy": _agent_gt_accuracy_block(run_dir),
        "ocr_cascade": {
            "claims_with_ocr": cascade_claims,
            "cascade_healthy_claims": cascade_healthy,
            "cascade_healthy_rate": (
                round(cascade_healthy / cascade_claims, 6) if cascade_claims else 0.0
            ),
            "claims_with_tesseract_observed": tesseract_claims,
            "engines_attempted": dict(engine_attempted),
            "engines_observed": dict(engine_observed),
            "engines_unavailable": dict(engine_unavailable),
            "required": (
                "paddleocr OBSERVED + rapidocr OBSERVED; tesseract fill on miss "
                "(never UNAVAILABLE)"
            ),
        },
        "by_group": {
            group: _rollup_scope(group_rows)
            for group, group_rows in sorted(by_group.items())
        },
        "by_bundle": {
            bundle: _rollup_scope(bundle_rows)
            for bundle, bundle_rows in sorted(
                by_bundle.items(), key=lambda item: (-len(item[1]), item[0])
            )
        },
        "bundle_count": len(by_bundle),
        "metric_definitions": {
            "true_stp_rate": "true_stp / completed (registration_ok CMS-geometry claims)",
            "hitl_rate": "field_ink_hitl / completed — never (n - true_stp) / n",
            "infra_failures": (
                "REGISTRATION_FAILED | STAGE_FAILURE | APP_FAILURE | "
                "SUMMARY_ERROR | WORKER_ERROR | OCR_MISSING | INCOMPLETE"
            ),
            "accuracy": (
                "When agent-confirmed labels exist: exact_accuracy / "
                "accepted_field_precision / false_accepts vs "
                "evaluation_data/hackathon_agent_gt/field_truth.json"
            ),
            "note": (
                "Primary STP/HITL rates use the completed denominator. "
                "Infra failures are reported separately and must not be folded into HITL."
            ),
        },
        "note": (
            "Operational metrics under field-cascade-v12 with paddle+rapid confirmation "
            "cascade, name/ID value-band-first, and label-contamination relief. "
            "Accuracy uses agent-confirmed labels when "
            "evaluation_data/hackathon_agent_gt/field_truth.json is present."
        ),
        "generated_at": _utc_now(),
        "run_status": "PARTIAL" if n < limit else "COMPLETE",
    }


def _preflight_latency_hygiene() -> dict[str, Any]:
    """Warn on memory pressure / orphan OCR pools that inflate claim wall time."""
    report: dict[str, Any] = {"available_mem_gb": None, "orphan_spawn_workers": 0}
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
        for line in meminfo.splitlines():
            if line.startswith("MemAvailable:"):
                kb = int(line.split()[1])
                report["available_mem_gb"] = round(kb / (1024 * 1024), 2)
                break
    except (OSError, ValueError):
        pass
    # Orphaned spawn workers (PPID 1) from prior crashed cascades hold multi-GB
    # Paddle/Rapid heaps and thrash the ≤30s latency bar.
    try:
        import subprocess as _sp

        out = _sp.check_output(
            ["ps", "-eo", "pid,ppid,etime,rss,cmd"],
            text=True,
            stderr=_sp.DEVNULL,
        )
        orphans = []
        for line in out.splitlines()[1:]:
            if "multiprocessing.spawn" not in line or "spawn_main" not in line:
                continue
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            pid, ppid, etime, rss = parts[0], parts[1], parts[2], parts[3]
            if ppid != "1":
                continue
            orphans.append({"pid": int(pid), "etime": etime, "rss_kb": int(rss)})
        report["orphan_spawn_workers"] = len(orphans)
        report["orphan_rss_gb"] = round(
            sum(o["rss_kb"] for o in orphans) / (1024 * 1024), 2
        )
        report["orphans"] = orphans[:20]
    except (OSError, ValueError, FileNotFoundError):
        pass
    return report


def _load_dotenv() -> None:
    """Load repo .env into os.environ (setdefault) for CDP_* knobs not in Settings."""
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def main() -> int:
    from workers.ocr_engine_factories import wire_package_ocr_providers

    _load_dotenv()
    wire_package_ocr_providers()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1,
                        help="Claim workers (default 1 until VLM/DI locks are shard-safe). "
                        "Use --auto-workers to size from CPUs/nodes.")
    parser.add_argument(
        "--nodes",
        type=int,
        default=None,
        help="Fleet size for node-aware claim sharding (env CDP_NODE_COUNT). Default 1.",
    )
    parser.add_argument(
        "--node-index",
        type=int,
        default=None,
        help="This node's zero-based index (env CDP_NODE_INDEX / StatefulSet ordinal).",
    )
    parser.add_argument(
        "--auto-workers",
        action="store_true",
        default=False,
        help="Auto-size --workers from pending load, CPUs, and node count.",
    )
    parser.add_argument(
        "--documents",
        default="",
        help="Comma-separated document paths to run (e.g. 'Group A/M048DJJM.036'). "
        "When set, offset/limit are ignored.",
    )
    parser.add_argument("--document-type", default="CMS1500")
    parser.add_argument("--keep-heavy", action="store_true")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    args = parser.parse_args()

    # Stamp STP product defaults onto os.environ before pools spawn. Stale shell
    # exports from a prior latency smoke (e.g. CDP_TROCR_DOB_RESIDUAL=0) would
    # otherwise win over ``_stage_env`` setdefault and suppress DOB/REG recovery.
    # Set CDP_CASCADE_RESPECT_ENV=1 to keep caller exports as-is.
    _respect = (os.environ.get("CDP_CASCADE_RESPECT_ENV") or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    _product = {
        "CDP_TROCR_DOB_RESIDUAL": "1",
        "CDP_LEARNED_MATCHER": "1",
        # Document Intelligence charge crops on cdp43 (not the F0 1/min tier).
        # DOB stays local TrOCR then Claude. Page-corner DI stays off.
        "CDP_AZURE_DI_DOB_RESIDUAL": "0",
        "CDP_AZURE_DI_CHARGE_RESIDUAL": "1",
        "CDP_AZURE_DI_CHARGE_CORROBORATE": "1",
        "CDP_AZURE_DI_CHARGE_ACCEPT": "1",
        "CDP_AZURE_DI_PAGE_CORNERS": "0",
        "CDP_AZURE_DI_MIN_INTERVAL_SECONDS": "0",
        "CDP_AZURE_DI_SLOT_PATH": "/tmp/cdp-azure-di-slot",
        "CDP_AZURE_DI_SERVICE_LINE_BUDGET": "1",
        "CDP_DOB_RESIDUAL_SKIP_IF_LOCAL_SHAPED": "1",
        "CDP_OCR_NAME_CONFIRM_MIN_CONF": "0.80",
        # Unstructured REG: DI page-read after template miss + text agent on gaps.
        # Azure OpenAI may 401; Claude text fallback covers the agent path.
        # Kill-switch: CDP_UNSTRUCTURED_REG_AGENT=0 (with CDP_CASCADE_RESPECT_ENV=1).
        "CDP_UNSTRUCTURED_REG_FALLBACK": "1",
        "CDP_UNSTRUCTURED_REG_AGENT": "1",
        # FIELD_INK DOB/ID/charge: crop-only Claude/gpt-4o after local(+TrOCR) miss.
        "CDP_GPT4O_CROP_RESIDUAL": "1",
        "CDP_GPT4O_CROP_ACCEPT": "1",
        "CDP_GPT4O_EMPTY_FINANCE": "1",
        "CDP_GPT4O_EMPTY_FINANCE_MAX_LINES": "2",
        "CDP_VLM_CROP_LOCK": "1",
        "CDP_VLM_CROP_LOCK_PATH": "/tmp/cdp_vlm_crop.lock",
        "CDP_VLM_CROP_TIMEOUT_SECONDS": "35",
        "CDP_CROP_VLM_PROVIDER": "claude",
        # When two OCR/models disagree, Claude picks the ink and clears field HITL.
        "CDP_CONFLICT_AGENT": "1",
        # OpenOCR / Monkey / PaddleOCR-VL failed for charge recovery — keep off.
        "CDP_OPENOCR_SVTR": "0",
        "CDP_MONKEYOCR": "0",
        "CDP_PADDLEOCR_VL_TABLE": "0",
        # v02-12 identity boxes sit on the insurance-type row after alignment.
        # A clean shell must not fall back to that release.
        "CDP_PIPELINE_RELEASE": "extraction-v3",
        # Adaptive spend: soft/hard cut optional work only (never unsettled charge/DOB/ID).
        "CDP_DOC_LATENCY_BUDGET": "1",
        "CDP_DOC_BUDGET_SOFT_SEC": "18",
        "CDP_DOC_BUDGET_HARD_SEC": "22",
        "CDP_CLOUD_STOP_LADDER": "1",
    }
    for key, value in _product.items():
        if _respect:
            os.environ.setdefault(key, value)
        else:
            os.environ[key] = value

    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = out_dir / "results.jsonl"
    lock = threading.Lock()

    hygiene = _preflight_latency_hygiene()
    _write_json(out_dir / "latency_preflight.json", hygiene)
    print(f"latency_preflight={json.dumps(hygiene)}", flush=True)
    avail = hygiene.get("available_mem_gb")
    orphans = int(hygiene.get("orphan_spawn_workers") or 0)
    if orphans > 0:
        print(
            f"WARNING: {orphans} orphan spawn workers (~{hygiene.get('orphan_rss_gb')} GiB) "
            "— kill them before a latency-sensitive run",
            flush=True,
        )
    if isinstance(avail, (int, float)) and avail < 3.0:
        print(
            f"WARNING: MemAvailable={avail} GiB is low for parallel OCR pools",
            flush=True,
        )

    # Run the OCR probe in a child process so a Paddle/ONNX SIGSEGV cannot
    # kill the cascade parent (seen on fresh 2000-doc PRODUCT boots).
    try:
        import subprocess as _sp

        _probe_code = (
            "import json,sys; sys.path.insert(0,%r); "
            "from scripts.run_hackathon_1000_cascade import _probe_ocr_engines; "
            "print(json.dumps(_probe_ocr_engines()))"
            % (str(ROOT),)
        )
        _probe_run = _sp.run(
            [sys.executable, "-c", _probe_code],
            capture_output=True,
            text=True,
            timeout=180,
            env=dict(os.environ),
        )
        if _probe_run.returncode == 0 and _probe_run.stdout.strip():
            engine_probe = json.loads(_probe_run.stdout.strip().splitlines()[-1])
        else:
            engine_probe = {
                "paddleocr": "ERROR",
                "rapidocr": "ERROR",
                "tesseract": "ERROR",
                "all_observed": False,
                "error": (
                    f"probe_exit={_probe_run.returncode} "
                    f"stderr={(_probe_run.stderr or '')[-400:]}"
                ),
            }
    except Exception as exc:  # noqa: BLE001
        engine_probe = {
            "paddleocr": "ERROR",
            "rapidocr": "ERROR",
            "tesseract": "ERROR",
            "all_observed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(out_dir / "engines_probe.json", engine_probe)
    print(f"engines_probe={json.dumps(engine_probe)}", flush=True)
    if not engine_probe.get("all_observed"):
        print(
            "WARNING: OCR engine probe incomplete — cascade fill may degrade",
            flush=True,
        )

    docs = _list_documents(args.zip)
    doc_filter = [
        part.strip().replace("\\", "/")
        for part in str(args.documents or "").split(",")
        if part.strip()
    ]
    # Permanent corpus binding: dataset.root must be the same archive as --zip,
    # and every selected document must exist there. Prevents APP_FAILURE floods
    # when a new Drive zip is listed via --zip but app.py still opens dataset.yaml.
    from packages.corpus_binding import CorpusBindingError, bind_corpus, write_corpus_binding
    from packages.run_profiles import detect_live_profile, write_run_manifest

    bind_docs = doc_filter or None
    try:
        binding = bind_corpus(
            dataset_yaml=args.dataset,
            zip_path=args.zip,
            documents=bind_docs,
            require_documents=bool(bind_docs),
        )
    except CorpusBindingError as exc:
        print(f"ERROR: corpus binding failed: {exc}", flush=True)
        return 2
    write_corpus_binding(out_dir, binding)
    print(f"corpus_binding={json.dumps(binding.to_dict())}", flush=True)

    if doc_filter:
        wanted = set(doc_filter)
        selected = [d for d in docs if d.replace("\\", "/") in wanted]
        missing = sorted(wanted - {d.replace("\\", "/") for d in selected})
        if missing:
            print(f"ERROR: documents not in zip: {missing}", flush=True)
            return 2
    else:
        selected = docs[args.offset : args.offset + args.limit]

    live_profile = detect_live_profile()
    write_run_manifest(
        out_dir,
        profile=live_profile,
        dataset_id=binding.dataset_id,
        extra={
            "zip": str(Path(args.zip).resolve()),
            "dataset_yaml": str(Path(args.dataset).resolve()),
            "selected": len(selected),
            "cascade_respect_env": _respect,
        },
    )
    print(f"run_profile={live_profile} gate_note=PRODUCT_required_for_STP_gate", flush=True)
    done = _load_done(ledger) if args.resume else set()
    pending_global = [d for d in selected if _claim_slug(d) not in done]
    already_done = len(selected) - len(pending_global)

    from packages.work_distribution import (
        auto_local_workers,
        plan_distribution,
        resolve_topology,
        shard_for_node,
        write_plan,
    )

    topology = resolve_topology(node_count=args.nodes, node_index=args.node_index)
    fleet_plan = plan_distribution(
        pending_global,
        node_count=topology.node_count,
        notes=(
            f"offset={args.offset}",
            f"limit={args.limit}",
            f"selected={len(selected)}",
            f"already_done={already_done}",
        ),
    )
    write_plan(fleet_plan, out_dir / "work_distribution_plan.json")
    pending = shard_for_node(pending_global, topology)
    if topology.node_count > 1:
        print(
            f"node_shard={topology.node_id} index={topology.node_index}/"
            f"{topology.node_count} claimed={len(pending)}/{len(pending_global)} "
            f"(stable_hash_mod)",
            flush=True,
        )

    workers = int(args.workers)
    auto_env = (os.environ.get("CDP_AUTO_WORKERS") or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if args.auto_workers or auto_env:
        workers = auto_local_workers(
            pending=len(pending),
            node_count=topology.node_count,
        )
        print(
            f"auto_workers={workers} (pending={len(pending)} "
            f"nodes={topology.node_count} cpus={os.cpu_count()})",
            flush=True,
        )
    args.workers = workers

    # Refresh plan with chosen local concurrency for the Ops / Scale UI.
    fleet_plan = plan_distribution(
        pending_global,
        node_count=topology.node_count,
        local_workers_per_node=int(args.workers),
        notes=(
            f"offset={args.offset}",
            f"limit={args.limit}",
            f"selected={len(selected)}",
            f"already_done={already_done}",
            f"this_node_pending={len(pending)}",
        ),
    )
    write_plan(fleet_plan, out_dir / "work_distribution_plan.json")

    print(
        f"strategy=field-cascade-v12 selected={len(selected)} "
        f"already_done={already_done} pending={len(pending)} "
        f"workers={args.workers} nodes={topology.node_count} "
        f"node_index={topology.node_index}",
        flush=True,
    )

    rows_new: list[dict[str, Any]] = []
    # Apply stage env to this process so OCR/app pool workers inherit knobs.
    for key, value in _stage_env().items():
        os.environ[key] = value
    pool_workers = max(1, min(int(args.workers), len(pending))) if pending else 1
    # Cap heavy OCR spawn processes independently of claim fan-out so we can
    # overlap Azure DI / VLM / registration without 2× Paddle RSS (~4 GiB each).
    ocr_pool_cap_raw = (os.environ.get("CDP_OCR_POOL_WORKERS") or "").strip()
    ocr_pool_workers = pool_workers
    if ocr_pool_cap_raw.isdigit():
        ocr_pool_workers = max(1, min(pool_workers, int(ocr_pool_cap_raw)))
    ocr_executor: ProcessPoolExecutor | None = None
    app_executor: ProcessPoolExecutor | None = None
    if _app_pool_enabled() and pending:
        print(
            f"app_worker_pool=on workers={pool_workers} "
            f"(amortize registration imports + template SIFT)",
            flush=True,
        )
        app_executor = _spawn_pool(pool_workers)
    if _ocr_pool_enabled() and pending:
        print(
            f"ocr_worker_pool=on workers={ocr_pool_workers} "
            f"(claim_workers={pool_workers}; amortize Paddle/Rapid cold start)",
            flush=True,
        )
        ocr_executor = _spawn_pool(ocr_pool_workers)
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {
                pool.submit(
                    _process_one,
                    document=document,
                    out_dir=out_dir,
                    dataset_yaml=args.dataset,
                    document_type=args.document_type,
                    keep_heavy=args.keep_heavy,
                    ocr_executor=ocr_executor,
                    app_executor=app_executor,
                ): document
                for document in pending
            }
            for i, fut in enumerate(as_completed(futures), start=1):
                document = futures[fut]
                try:
                    row = fut.result()
                except Exception as exc:  # noqa: BLE001
                    row = {
                        "finished": True,
                        "claim_id": _claim_slug(document),
                        "document": document,
                        "bundle_id": _bundle_id(document),
                        "group_id": _group_id(document),
                        "registration_ok": False,
                        "completed": False,
                        "true_stp": False,
                        "disposition": "WORKER_ERROR",
                        "error": f"{type(exc).__name__}: {exc}",
                        "ts": _utc_now(),
                    }
                _append_ledger(ledger, row, lock)
                rows_new.append(row)
                if i % 5 == 0 or i == len(futures):
                    roll = _rollup_scope(rows_new)
                    msg = (
                        f"progress {i}/{len(futures)} newest={row.get('claim_id')} "
                        f"batch_reg={roll['registration_ok']}/{roll['n']} "
                        f"batch_completed={roll['completed']}/{roll['n']} "
                        f"batch_true_stp={roll['true_stp']}/{roll['completed']} "
                        f"({roll['true_stp_rate']:.1%} of completed) "
                        f"batch_field_hitl={roll['field_ink_hitl']}/{roll['completed']} "
                        f"({roll['hitl_rate']:.1%} of completed) "
                        f"batch_infra={roll['infra_failures']}/{roll['n']} "
                        f"disp={row.get('disposition')}"
                    )
                    # Always land progress on disk (survives stdout pipe stalls).
                    try:
                        (out_dir / "progress.txt").write_text(
                            msg + f"\n{ _utc_now() }\n", encoding="utf-8"
                        )
                    except OSError:
                        pass
                    print(msg, flush=True)
    finally:
        _shutdown_process_pool(ocr_executor)
        _shutdown_process_pool(app_executor)

    all_rows: list[dict[str, Any]] = []
    if ledger.exists():
        with ledger.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    all_rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    by_id: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        cid = str(row.get("claim_id") or "")
        if cid:
            by_id[cid] = row
    final_rows = [by_id[_claim_slug(d)] for d in selected if _claim_slug(d) in by_id]
    summary = _summarize(final_rows, limit=len(selected), run_dir=out_dir)
    summary["workers"] = args.workers
    summary["engines_probe"] = engine_probe
    try:
        summary["out_dir"] = str(out_dir.relative_to(ROOT))
    except ValueError:
        summary["out_dir"] = str(out_dir)
    summary_path = out_dir / "summary.json"
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"wrote {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
