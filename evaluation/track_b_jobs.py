"""Durable bounded executor recovery for the frozen qualification job contract."""

from __future__ import annotations

import socket
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psutil

from evaluation.claim_inventory import _publish
from evaluation.qualification_state import mapped
from evaluation.track_b_inputs import digest, read
from packages.real_data_evaluation.blind_workflow import content_digest
from packages.real_data_evaluation.qualification_jobs import advance as receipt_advance
from packages.real_data_evaluation.qualification_jobs import publish

PROCESSES: dict[int, subprocess.Popen] = {}


def executable(job: dict) -> Path:
    argv = job.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) and v for v in argv):
        raise ValueError("EXPLICIT_ARGUMENT_VECTOR_REQUIRED")
    path = Path(argv[0])
    if not path.is_absolute() or not path.is_file():
        raise ValueError("EXPLICIT_EXECUTABLE_REQUIRED")
    if digest(path) != job.get("executable_sha256"):
        raise ValueError("EXECUTOR_BINARY_CHANGED")
    return path


def liveness(marker: dict) -> str:
    if marker.get("host_id") != content_digest(socket.gethostname()):
        return "UNKNOWN"
    pid = marker.get("pid")
    if type(pid) is not int:
        return "UNKNOWN"
    local = PROCESSES.get(pid)
    if local is not None and local.poll() is not None:
        PROCESSES.pop(pid, None)
        return "DEAD"
    if not marker.get("process_created_at"):
        return "UNKNOWN"
    try:
        process = psutil.Process(pid)
        if (
            process.create_time() != marker["process_created_at"]
            or process.status() == psutil.STATUS_ZOMBIE
        ):
            return "DEAD"
        return "ALIVE"
    except psutil.NoSuchProcess:
        return "DEAD"
    except psutil.AccessDenied:
        return "UNKNOWN"


def advance(directory: Path, phase: str, inputs: dict, configuration: dict) -> dict:
    job = configuration.get("jobs", {}).get(phase)
    if not job or configuration.get("governed") is not True:
        return {
            "status": "NOT_AVAILABLE",
            "executor_state": "NOT_SUBMITTED",
            "reason": "GOVERNED_DEPLOYMENT_EXECUTOR_REQUIRED",
        }
    executable(job)
    if not configuration.get("deployment_id") or not configuration.get("approval_reference"):
        raise ValueError("DEPLOYMENT_EXECUTION_PROVENANCE_REQUIRED")
    maximum = job.get("max_attempts", 1)
    if type(maximum) is not int or not 1 <= maximum <= 5:
        raise ValueError("BOUNDED_EXECUTOR_ATTEMPTS_REQUIRED")
    request = {
        "phase": phase,
        "inputs": inputs,
        "deployment_id": configuration["deployment_id"],
        "configuration_sha256": content_digest(configuration),
        "contract": "CDP_QUALIFICATION_EXECUTION_V1",
    }
    request["request_id"] = content_digest(request)
    directory = mapped(directory / "jobs").parent
    folder = mapped(directory / "jobs") / phase
    folder.mkdir(parents=True, exist_ok=True)
    # OS-released SQLite lock serializes launches across UI and watcher refreshes.
    with sqlite3.connect(folder / "lifecycle.local.sqlite3", timeout=30) as lock:
        lock.execute("CREATE TABLE IF NOT EXISTS serialization (id INTEGER)")
        lock.execute("BEGIN IMMEDIATE")
        publish(folder / "request.local.json", request)
        if (folder / "receipt.local.json").exists():
            return receipt_advance(directory, phase, inputs, configuration)
        attempts = sorted((folder / "attempts").glob("*/submitted.local.json"))
        attempt = len(attempts) + 1
        if attempts:
            previous = attempts[-1].parent
            submitted = read(previous / "submitted.local.json")
            if (
                any(
                    submitted.get(k) != request[k]
                    for k in ("request_id", "configuration_sha256", "deployment_id")
                )
                or submitted.get("executor_sha256") != job["executable_sha256"]
            ):
                raise ValueError("EXECUTOR_ATTEMPT_IDENTITY_CHANGED")
            failed = read(previous / "failure.local.json")
            if not failed:
                running = read(previous / "running.local.json")
                state = liveness(running) if running else "UNKNOWN"
                if state == "ALIVE":
                    return {
                        "status": "IN_PROGRESS",
                        "executor_state": "IN_PROGRESS",
                        "request_id": request["request_id"],
                        "attempt": submitted["attempt"],
                    }
                failed = {
                    **submitted,
                    "status": "EXECUTOR_FAILED",
                    "executor_state": "FAILED",
                    "ended_at": datetime.now(UTC).isoformat(),
                    "retryable": state == "DEAD",
                    "reason": "EXECUTOR_EXITED_WITHOUT_RECEIPT"
                    if state == "DEAD"
                    else "EXECUTOR_LIVENESS_UNCONFIRMED",
                }
                publish(previous / "failure.local.json", failed)
                _publish(folder / "failure.local.json", failed)
                return failed
            if not failed.get("retryable") or submitted["attempt"] >= maximum:
                return failed
        elif (folder / "submitted.local.json").exists():
            # Historical markers contain no PID/creation time. Never guess they are dead.
            return {
                "status": "EXECUTOR_FAILED",
                "executor_state": "FAILED",
                "request_id": request["request_id"],
                "reason": "LEGACY_EXECUTOR_LIVENESS_UNCONFIRMED",
                "retryable": False,
            }
        attempt_dir = folder / "attempts" / f"{attempt:04d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        submitted = {
            **request,
            "pid": None,
            "started_at": datetime.now(UTC).isoformat(),
            "attempt": attempt,
            "executor_sha256": job["executable_sha256"],
            "host_id": content_digest(socket.gethostname()),
        }
        publish(attempt_dir / "submitted.local.json", submitted)
        if not (folder / "submitted.local.json").exists():
            publish(folder / "submitted.local.json", submitted)
        try:
            process = subprocess.Popen(
                [
                    *job["argv"],
                    "--qualification-request",
                    str((folder / "request.local.json").resolve()),
                    "--qualification-receipt",
                    str((folder / "receipt.local.json").resolve()),
                ],
                cwd=mapped(directory).resolve(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            failure = {
                **submitted,
                "status": "EXECUTOR_FAILED",
                "executor_state": "FAILED",
                "ended_at": datetime.now(UTC).isoformat(),
                "reason": "EXECUTOR_START_FAILED",
                "retryable": True,
            }
            publish(attempt_dir / "failure.local.json", failure)
            _publish(folder / "failure.local.json", failure)
            return failure
        PROCESSES[process.pid] = process
        try:
            created = psutil.Process(process.pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            created = None
        running = {**submitted, "pid": process.pid, "process_created_at": created}
        publish(attempt_dir / "running.local.json", running)
        _publish(folder / "running.local.json", running)
        return {
            "status": "IN_PROGRESS",
            "executor_state": "IN_PROGRESS",
            "request_id": request["request_id"],
            "attempt": attempt,
            "process_id": process.pid,
        }
