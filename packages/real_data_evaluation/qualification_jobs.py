"""Durable handoff to explicitly configured deployment qualification executors.

Executors receive request/receipt paths, use the request ID as their idempotency
key, and publish a sealed receipt. No command, endpoint or passing result is inferred.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from packages.real_data_evaluation.blind_workflow import content_digest


def publish(path: Path, payload: dict) -> None:
    data = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if json.loads(path.read_text()) != payload:
                raise ValueError("IMMUTABLE_EXECUTION_INPUT_CHANGED") from None
    finally:
        temporary.unlink(missing_ok=True)


def advance(directory: Path, phase: str, inputs: dict, configuration: dict) -> dict:
    """Submit once; after a crash wait for the same receipt instead of duplicating work."""
    job = configuration.get("jobs", {}).get(phase)
    if not job or configuration.get("governed") is not True:
        return {"status": "NOT_AVAILABLE", "reason": "GOVERNED_DEPLOYMENT_EXECUTOR_REQUIRED"}
    if not configuration.get("deployment_id") or not configuration.get("approval_reference"):
        raise ValueError("DEPLOYMENT_EXECUTION_PROVENANCE_REQUIRED")
    argv = job.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError("EXPLICIT_ARGUMENT_VECTOR_REQUIRED")
    executable = Path(argv[0])
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("EXPLICIT_EXECUTABLE_REQUIRED")
    if hashlib.sha256(executable.read_bytes()).hexdigest() != job.get("executable_sha256"):
        raise ValueError("EXECUTOR_BINARY_CHANGED")
    request = {
        "phase": phase,
        "inputs": inputs,
        "deployment_id": configuration["deployment_id"],
        "configuration_sha256": content_digest(configuration),
        "contract": "CDP_QUALIFICATION_EXECUTION_V1",
    }
    request["request_id"] = content_digest(request)
    folder = directory / "jobs" / phase
    folder.mkdir(parents=True, exist_ok=True)
    request_path, receipt_path = folder / "request.local.json", folder / "receipt.local.json"
    publish(request_path, request)
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("request_id") != request["request_id"] or receipt.get(
            "receipt_sha256"
        ) != content_digest({k: v for k, v in receipt.items() if k != "receipt_sha256"}):
            raise ValueError("DEPLOYMENT_RECEIPT_PROVENANCE_MISMATCH")
        if receipt.get("status") not in {
            "PASS",
            "FAIL",
            "WAITING_HUMAN",
            "IN_PROGRESS",
            "NOT_AVAILABLE",
        }:
            raise ValueError("INVALID_DEPLOYMENT_EXECUTION_STATUS")
        outputs = receipt.get("outputs", {})
        if receipt["status"] == "PASS" and not outputs:
            raise ValueError("MEASURED_OUTPUT_REQUIRED")
        for name, digest in outputs.items():
            path = (directory / name).resolve()
            path.relative_to(directory.resolve())
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("DEPLOYMENT_OUTPUT_HASH_MISMATCH")
        return {
            "status": receipt["status"],
            "request_id": request["request_id"],
            "receipt_sha256": receipt["receipt_sha256"],
            "outputs": outputs,
        }
    try:
        marker = (folder / "submitted.local.json").open("x", encoding="utf-8")
    except FileExistsError:
        return {
            "status": "IN_PROGRESS",
            "request_id": request["request_id"],
            "reason": "AWAITING_DURABLE_EXECUTOR_RECEIPT",
        }
    with marker:
        json.dump({"request_id": request["request_id"], "status": "SUBMITTING"}, marker)
        marker.flush()
        os.fsync(marker.fileno())
    # No shell expansion. Logs are private; qualification artifacts contain no stdout.
    with (folder / "executor.local.log").open("ab") as log:
        try:
            process = subprocess.Popen(
                [
                    *argv,
                    "--qualification-request",
                    str(request_path.resolve()),
                    "--qualification-receipt",
                    str(receipt_path.resolve()),
                ],
                cwd=directory.resolve(),
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError:
            # Popen failed before a child was launched; permit a later watcher retry.
            # An uncertain launch after process creation must retain its marker.
            (folder / "submitted.local.json").unlink()
            return {"status": "NOT_AVAILABLE", "reason": "EXECUTOR_START_FAILED"}
    return {"status": "IN_PROGRESS", "request_id": request["request_id"], "process_id": process.pid}
