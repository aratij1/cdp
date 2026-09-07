"""Read-only deployment preflight. Reports statuses only, never connection values."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

ENV_KEYS = (
    "database_url_env",
    "broker_url_env",
    "object_store_endpoint_env",
    "object_store_access_key_env",
    "object_store_secret_key_env",
    "authority_config_env",
    "pricing_config_env",
)


def probe(service: str, values: dict) -> bool:
    if service == "database":
        from sqlalchemy import create_engine, text

        # Qualification cannot silently use the workstation's in-memory SQLite default.
        if values["database_url_env"].startswith("sqlite:"):
            return False
        engine = create_engine(
            values["database_url_env"], pool_pre_ping=True, connect_args={"connect_timeout": 5}
        )
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()
    elif service == "broker":
        from aiokafka import AIOKafkaProducer

        async def check():
            producer = AIOKafkaProducer(
                bootstrap_servers=values["broker_url_env"], request_timeout_ms=5000
            )
            try:
                await asyncio.wait_for(producer.start(), 8)
            finally:
                await producer.stop()

        asyncio.run(check())
    elif service == "object_store":
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=values["object_store_endpoint_env"],
            aws_access_key_id=values["object_store_access_key_env"],
            aws_secret_access_key=values["object_store_secret_key_env"],
            config=Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 0}),
        )
        try:
            client.list_buckets()
        finally:
            client.close()
    return True


def preflight(config: dict, environ=None, checker=None) -> dict:
    environ = os.environ if environ is None else environ
    checker = checker or probe
    checks = {
        key: "CONFIGURED" if config.get(key) else "MISSING"
        for key in (
            "qualification_host",
            "environment",
            "execution_provider",
            "deployment_id",
            "approval_reference",
        )
    }
    checks["governance"] = "CONFIGURED" if config.get("governed") is True else "MISSING"
    values = {}
    for key in ENV_KEYS:
        name = config.get(key)
        configured = isinstance(name, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
        checks[key] = "CONFIGURED" if configured else "MISSING"
        values[key] = environ.get(name, "") if configured else ""
        checks[key + "_runtime"] = "CONFIGURED" if values[key] else "MISSING"
    for service in ("authority", "pricing"):
        value = values[service + "_config_env"]
        checks[service] = "CONFIGURED" if value and Path(value).is_file() else "MISSING"
    # Only contact services after the deployment owner supplies a governed environment.
    may_probe = all(v == "CONFIGURED" for v in checks.values())
    for service in ("database", "broker", "object_store"):
        checks[service] = "MISSING"
        if may_probe:
            try:
                checks[service] = "PASS" if checker(service, values) else "UNREACHABLE"
            except Exception:  # noqa: BLE001 -- suppress secret-bearing driver exceptions
                # Driver exceptions can embed passwords/URLs; deliberately discard them.
                checks[service] = "UNREACHABLE"
    return {
        "status": "PASS"
        if all(v in {"PASS", "CONFIGURED"} for v in checks.values())
        else "UNREACHABLE"
        if "UNREACHABLE" in checks.values()
        else "MISSING",
        "checks": checks,
        "scope": "READ_ONLY_CONNECTIVITY_NOT_OPERATIONAL_QUALIFICATION",
    }


def operational_extensions(payload: dict, result: dict, directory: Path) -> dict:
    """Require deployment artifacts for resume and duplicate handling, beyond connectivity."""
    import hashlib

    result = {**result, "checks": dict(result.get("checks", {}))}
    for name in ("partial_output_resume", "duplicate_event", "duplicate_output_protection"):
        evidence = payload.get("checks", {}).get(name, {})
        status = evidence.get("status", "NOT_AVAILABLE")
        if status not in {"PASS", "FAIL", "NOT_AVAILABLE"}:
            raise ValueError("INVALID_OPERATIONAL_CHECK_STATUS")
        if status == "PASS":
            artifact = evidence.get("artifact")
            path = (directory / artifact).resolve() if isinstance(artifact, str) else None
            if path is None or not path.is_relative_to(directory.resolve()) or not path.is_file():
                status = "NOT_AVAILABLE"
            elif hashlib.sha256(path.read_bytes()).hexdigest() != evidence.get("artifact_sha256"):
                status = "FAIL"
            elif result.get("status") != "PASS":
                status = "NOT_AVAILABLE"
        result["checks"][name] = {"status": status, "evidence": evidence.get("artifact_sha256")}
    states = {c["status"] for c in result["checks"].values()}
    if "FAIL" in states:
        result["status"] = "FAIL"
    elif states != {"PASS"}:
        result["status"] = "NOT_AVAILABLE"
    return result
