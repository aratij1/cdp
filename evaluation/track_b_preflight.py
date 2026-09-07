"""Read-only deployment preflight. Reports statuses only, never connection values."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

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
        # The deployment owns its Kafka TLS/SASL/OAuth/mTLS setup. No plaintext fallback.
        contract = values["broker_probe"]
        from evaluation.track_b_jobs import executable

        executable(contract)
        result = subprocess.run(
            contract["argv"],
            timeout=contract.get("timeout_seconds", 10),
            env=values["probe_environment"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0
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


REQUIRED_JOBS = {"TARGET_LATENCY", "OPERATIONAL_PREFLIGHT", "RAW", "OPERATIONAL", "HITL_FINAL"}


def contract_preflight(config: dict, directory: Path | None = None) -> dict:
    from evaluation.track_b_inputs import CANDIDATE, read
    from evaluation.track_b_jobs import executable
    from packages.real_data_evaluation.blind_workflow import content_digest

    checks = {}

    def require(key, condition):
        checks[key] = "VALID" if condition else "INVALID"

    def sha(value):
        return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None

    def env(value):
        return isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", value) is not None

    for key in (
        "qualification_host",
        "environment",
        "execution_provider",
        "deployment_id",
        "approval_reference",
    ):
        require(key, isinstance(config.get(key), str) and bool(config[key].strip()))
    require("governed", config.get("governed") is True)
    settings = config.get("cdp_services", {})
    if not isinstance(settings, dict):
        settings = {}
    require("qualification_environment", settings.get("qualification_environment") is True)
    require("candidate_commit_sha", settings.get("candidate_commit_sha") == CANDIDATE)
    require(
        "service_deployment_id",
        settings.get("deployment_id") == config.get("deployment_id")
        and bool(config.get("deployment_id")),
    )
    for key in ("pipeline_configuration_sha256", "deployment_attestation_sha256"):
        require(key, sha(settings.get(key)))
    try:
        url = urlsplit(settings.get("ingestion_url", ""))
        valid_url = (
            url.scheme in {"http", "https"}
            and bool(url.hostname)
            and not (url.username or url.password or url.query or url.fragment)
        )
    except (TypeError, ValueError):
        valid_url = False
    require("ingestion_url", valid_url)
    require(
        "tenant_id",
        isinstance(settings.get("tenant_id"), str) and bool(settings["tenant_id"].strip()),
    )
    auth_required = settings.get("authorization_required", True)
    require(
        "authorization_env",
        type(auth_required) is bool
        and (env(settings.get("authorization_env")) or auth_required is False),
    )
    for key in ENV_KEYS:
        require(key, env(config.get(key)))
    require(
        "database_env_consistency",
        settings.get("database_url_env") == config.get("database_url_env"),
    )
    canaries = settings.get("ub04_canary_fingerprints", {})
    require(
        "ub_canaries",
        isinstance(canaries, dict)
        and len(canaries) == 3
        and all(isinstance(k, str) and k and sha(v) for k, v in canaries.items()),
    )
    jobs = config.get("jobs", {})
    for phase in REQUIRED_JOBS:
        try:
            job = jobs[phase]
            executable(job)
            maximum = job.get("max_attempts", 1)
            valid = type(maximum) is int and 1 <= maximum <= 5
        except (KeyError, ValueError, TypeError, AttributeError, OSError):
            valid = False
        require("job_" + phase, valid)
    broker = config.get("broker_probe", {})
    try:
        executable(broker)
        timeout = broker.get("timeout_seconds", 10)
        valid_probe = (
            type(timeout) is int
            and 1 <= timeout <= 60
            and isinstance(broker.get("required_env"), list)
            and all(env(n) for n in broker["required_env"])
        )
    except (ValueError, TypeError, AttributeError, OSError):
        valid_probe = False
    require("broker_probe", valid_probe)
    try:
        attestation = read(directory / "deployment_attestation.local.json") if directory else {}
        valid_attestation = (
            attestation.get("governed") is True
            and content_digest(attestation) == settings.get("deployment_attestation_sha256")
            and attestation.get("candidate_commit_sha") == CANDIDATE
            and all(
                attestation.get(k) == config.get(k) and bool(config.get(k))
                for k in ("deployment_id", "approval_reference")
            )
            and attestation.get("pipeline_configuration_sha256")
            == settings.get("pipeline_configuration_sha256")
        )
    except (ValueError, TypeError, AttributeError, OSError):
        valid_attestation = False
    require("deployment_attestation", valid_attestation)
    return {
        "status": "VALID" if all(v == "VALID" for v in checks.values()) else "INVALID",
        "checks": checks,
    }


def preflight(config: dict, environ=None, checker=None, *, directory: Path | None = None) -> dict:
    environ = os.environ if environ is None else environ
    checker = checker or probe
    contract = contract_preflight(config, directory)
    if contract["status"] != "VALID":
        return {
            "status": "INVALID_CONTRACT",
            "contract": contract,
            "connectivity": "MISSING",
            "checks": {},
        }
    checks = {}
    values = {key: environ.get(config[key], "") for key in ENV_KEYS}
    for key, value in values.items():
        checks[key + "_runtime"] = "CONFIGURED" if value else "MISSING"
    auth = config["cdp_services"].get("authorization_env")
    if auth:
        checks["authorization_env_runtime"] = "CONFIGURED" if environ.get(auth) else "MISSING"
    for name in config["broker_probe"]["required_env"]:
        checks["broker_env_" + name] = "CONFIGURED" if environ.get(name) else "MISSING"
    for service in ("authority", "pricing"):
        value = values[service + "_config_env"]
        checks[service] = "CONFIGURED" if value and Path(value).is_file() else "MISSING"
    values["broker_probe"] = config["broker_probe"]
    values["probe_environment"] = dict(environ)
    may_probe = all(v == "CONFIGURED" for v in checks.values())
    for service in ("database", "broker", "object_store"):
        checks[service] = "MISSING"
        if may_probe:
            try:
                checks[service] = "PASS" if checker(service, values) else "UNREACHABLE"
            except Exception:  # noqa: BLE001 -- driver exceptions may contain secrets
                checks[service] = "UNREACHABLE"
    connectivity = (
        "PASS"
        if all(v in {"PASS", "CONFIGURED"} for v in checks.values())
        else "UNREACHABLE"
        if "UNREACHABLE" in checks.values()
        else "MISSING"
    )
    return {
        "status": connectivity,
        "contract": contract,
        "connectivity": connectivity,
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
