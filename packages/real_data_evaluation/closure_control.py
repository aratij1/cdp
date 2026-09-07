"""Fail-closed prerequisites and deployment evidence for the closure control plane."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from packages.real_data_evaluation.blind_workflow import content_digest

DEPLOYMENT_CHECKS = (
    "database",
    "broker",
    "outbox",
    "retry",
    "dead_letter",
    "worker_restart",
    "database_restart",
    "broker_restart",
    "load",
    "concurrency",
    "security",
    "authorization",
    "secret_management",
    "audit_logging",
    "phi_controls",
    "observability",
    "backup_recovery",
)
SECURITY_CHECKS = (
    "security",
    "authorization",
    "secret_management",
    "audit_logging",
    "phi_controls",
)


def freeze_prerequisites(
    sources: dict,
    bindings: dict,
    reservation: dict,
    manifest_sha256: str,
    manifest: dict | None = None,
) -> dict:
    rows = bindings.get("bindings", [])
    by_page = {r["source_page_id"]: r for r in rows}
    assignments = reservation.get("assignments", {})
    exact = (
        bool(sources) and len(rows) == len(by_page) == len(sources) and set(by_page) == set(sources)
    )
    exact = exact and len({r.get("cdp_page_id") for r in rows}) == len(rows)
    for page, source in sources.items():
        row = by_page.get(page, {})
        exact = exact and row.get("state") == "EXACT" and bool(row.get("cdp_page_id"))
        exact = exact and row.get("package_id") == source["package_id"]
        exact = exact and row.get("rendered_page_sha256") == source["rendered_page_sha256"]
        exact = exact and row.get("cdp_page_sha256") == source["rendered_page_sha256"]
    reserved = bool(assignments) and not (set(assignments.values()) - {"DEVELOPMENT", "HOLDOUT"})
    reserved = reserved and all(s["package_id"] in assignments for s in sources.values())
    # Binding seals original bytes; the reservation seals canonical JSON.
    # Verify each original representation without rewriting either frozen input.
    reservation_digest = content_digest(manifest) if manifest is not None else manifest_sha256
    pinned = (
        bool(manifest_sha256)
        and bindings.get("blind_manifest_sha256") == manifest_sha256
        and reservation.get("blind_manifest_sha256") == reservation_digest
    )
    if manifest is not None:
        pages = manifest.get("pages", [])
        expected = {p["page_id"]: p["package_id"] for p in pages}
        pinned = (
            pinned
            and len(pages) == len(expected) == len(sources)
            and expected == {page: source["package_id"] for page, source in sources.items()}
        )
    return {
        "status": "PASS" if exact and reserved and pinned else "FAIL",
        "exact_binding": bool(exact),
        "package_reservation_valid": bool(reserved),
        "blind_manifest_unchanged": bool(pinned),
        "package_leakage": 0 if reserved else None,
    }


def deployment_evidence(
    payload: dict,
    configuration_sha256: str | None,
    truth_sha256: str | None,
    directory: Path | None = None,
) -> dict:
    provenance = bool(configuration_sha256 and truth_sha256) and (
        payload.get("scope") == "PRODUCTION_DEPLOYMENT"
        and payload.get("configuration_sha256") == configuration_sha256
        and payload.get("truth_sha256") == truth_sha256
        and bool(payload.get("run_id"))
    )
    checks = {}
    for name in DEPLOYMENT_CHECKS:
        evidence = payload.get("checks", {}).get(name, {})
        status = evidence.get("status", "NOT_AVAILABLE")
        if status not in {"PASS", "FAIL", "NOT_AVAILABLE"}:
            raise ValueError("INVALID_OPERATIONAL_CHECK_STATUS")
        if status == "PASS" and not (provenance and evidence.get("artifact_sha256")):
            status = "NOT_AVAILABLE"
        if status == "PASS" and directory is not None:
            artifact = evidence.get("artifact")
            if not isinstance(artifact, str) or not artifact:
                status = "NOT_AVAILABLE"
            else:
                path = (directory / artifact).resolve()
                if not path.is_relative_to(directory.resolve()) or not path.is_file():
                    status = "NOT_AVAILABLE"
                elif hashlib.sha256(path.read_bytes()).hexdigest() != evidence["artifact_sha256"]:
                    status = "FAIL"
        checks[name] = {"status": status, "evidence": evidence.get("artifact_sha256")}
    load = payload.get("load_metrics", {})
    if checks["load"]["status"] == "PASS":
        required = (
            "pages_per_second",
            "claims_per_second",
            "p50_ms",
            "p95_ms",
            "p99_ms",
            "queue_depth",
            "consumer_lag",
            "memory_bytes",
            "cpu_percent",
            "error_rate",
            "retry_rate",
            "duplicate_event_rate",
            "output_duplicates",
            "lost_claims",
        )
        if not all(
            type(load.get(k)) in (int, float) and math.isfinite(load[k]) and load[k] >= 0
            for k in required
        ):
            checks["load"]["status"] = "NOT_AVAILABLE"
        elif (
            load["output_duplicates"] != 0
            or load["lost_claims"] != 0
            or payload.get("bounded_retries") is not True
        ):
            checks["load"]["status"] = "FAIL"
    statuses = {v["status"] for v in checks.values()}
    security = {checks[k]["status"] for k in SECURITY_CHECKS}
    return {
        "status": "FAIL"
        if "FAIL" in statuses
        else "PASS"
        if statuses == {"PASS"}
        else "NOT_AVAILABLE",
        "security_status": "FAIL"
        if "FAIL" in security
        else "PASS"
        if security == {"PASS"}
        else "NOT_AVAILABLE",
        "checks": checks,
        "load_metrics": load,
        "provenance_valid": provenance,
    }
