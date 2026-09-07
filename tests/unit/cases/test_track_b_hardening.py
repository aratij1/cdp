"""Synthetic negative-path hardening tests; no actual authority or deployment evidence."""

import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from evaluation.track_b_inputs import CANDIDATE, digest, owner_approval, prepare
from evaluation.track_b_preflight import ENV_KEYS, REQUIRED_JOBS, preflight
from packages.real_data_evaluation.blind_workflow import content_digest
from tests.track_b_helpers import approve_csv, governed_registry


def deployment_contract(directory):
    executable = Path(sys.executable).resolve()
    job = {
        "argv": [str(executable), "-c", "pass"],
        "executable_sha256": digest(executable),
        "max_attempts": 2,
    }
    config = {key: key.upper() for key in ENV_KEYS}
    config.update(
        governed=True,
        qualification_host="synthetic.invalid",
        environment="synthetic",
        execution_provider="CPU",
        deployment_id="synthetic",
        approval_reference="synthetic-owner",
    )
    attestation = {
        "governed": True,
        "candidate_commit_sha": CANDIDATE,
        "deployment_id": "synthetic",
        "approval_reference": "synthetic-owner",
        "pipeline_configuration_sha256": "a" * 64,
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "deployment_attestation.local.json").write_text(json.dumps(attestation))
    config["cdp_services"] = {
        "qualification_environment": True,
        "candidate_commit_sha": CANDIDATE,
        "pipeline_configuration_sha256": "a" * 64,
        "deployment_attestation_sha256": content_digest(attestation),
        "ingestion_url": "https://synthetic.invalid",
        "tenant_id": "synthetic",
        "authorization_env": "SYNTHETIC_AUTH",
        "deployment_id": "synthetic",
        "database_url_env": config["database_url_env"],
        "ub04_canary_fingerprints": {k: "b" * 64 for k in ("one", "two", "three")},
    }
    config["jobs"] = {k: copy.deepcopy(job) for k in REQUIRED_JOBS}
    config["broker_probe"] = {
        **job,
        "required_env": ["SYNTHETIC_KAFKA_SECURITY"],
        "timeout_seconds": 2,
    }
    env = {config[key]: "SECRET_SENTINEL" for key in ENV_KEYS}
    env.update(SYNTHETIC_AUTH="SECRET_SENTINEL", SYNTHETIC_KAFKA_SECURITY="SECRET_SENTINEL")
    provider = directory / "synthetic-config.json"
    provider.write_text('{"synthetic":true}')
    for name in ("authority", "pricing"):
        env[config[name + "_config_env"]] = str(provider)
    return config, env


@pytest.fixture
def ui_context(tmp_path, monkeypatch):
    from evaluation.annotation_app import qualification_review as ui

    data = tmp_path / "evaluation_results/qualification_closure"
    registry = governed_registry(tmp_path, data, monkeypatch)
    (data / "blind_source_views.local.json").write_text(
        json.dumps([{"page_id": "page", "package_id": "pkg", "rendered_page_sha256": "a" * 64}])
    )
    monkeypatch.setattr(ui, "DATA", data)
    monkeypatch.setattr(ui, "ROOT", tmp_path)
    app = FastAPI()
    app.include_router(ui.router)
    return ui, TestClient(app), tmp_path / "config/qualification/reviewer_registry.yaml", registry


def login(client):
    return client.post(
        "/qualification-review/login",
        data={"reviewer": "one", "access_code": "synthetic-one"},
        follow_redirects=False,
    )


@pytest.mark.parametrize("state", ["missing", "invalid", "stale", "expired"])
def test_registry_revocation_denies_login_and_session_writes(ui_context, state):
    ui, client, path, _ = ui_context
    assert login(client).status_code == 303
    if state == "missing":
        path.unlink()
    elif state == "invalid":
        path.write_text("reviewers: [")
    elif state == "stale":
        path.write_text(path.read_text() + "\n# changed contract\n")
    else:
        import yaml

        data = yaml.safe_load(path.read_text())
        data["reviewers"][0]["effective_to"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        path.write_text(yaml.safe_dump(data))
    expected = {"missing": "MISSING", "invalid": "INVALID", "stale": "STALE", "expired": "INVALID"}[
        state
    ]
    assert ui.governed_registry()["contract_status"] == expected
    assert login(client).status_code in (403, 503)
    token = client.cookies.get("qualification_session")
    response = client.post(
        "/qualification-review/draft/0",
        headers={"X-Review-Session": token},
        json={"annotation": {"fields": {}}, "complete": False},
    )
    assert response.status_code == 403
    assert client.get("/qualification-review/adjudication/0").status_code == 403
    assert (ui.DATA / "reviewer_registry.local.json").exists()


def test_missing_runtime_code_revokes_existing_session(ui_context, monkeypatch):
    _, client, _, _ = ui_context
    assert login(client).status_code == 303
    monkeypatch.delenv("SYNTHETIC_ONE_ACCESS")
    token = client.cookies.get("qualification_session")
    assert (
        client.post(
            "/qualification-review/draft/0",
            headers={"X-Review-Session": token},
            json={"annotation": {"fields": {}}, "complete": False},
        ).status_code
        == 403
    )


def test_access_codes_are_not_stored(ui_context):
    ui, client, _, _ = ui_context
    assert login(client).status_code == 303
    token = client.cookies.get("qualification_session")
    assert (
        client.post(
            "/qualification-review/draft/0",
            headers={"X-Review-Session": token},
            json={"annotation": {"fields": {}}, "complete": False},
        ).status_code
        == 200
    )
    assert all(b"synthetic-one" not in p.read_bytes() for p in ui.DATA.iterdir() if p.is_file())


def test_controller_does_not_use_stale_cache_without_yaml(tmp_path):
    private = tmp_path / "evaluation_results/qualification_closure"
    private.mkdir(parents=True)
    (private / "reviewer_registry.local.json").write_text(
        json.dumps(
            {
                "identity_verified": True,
                "policy_id": "stale",
                "authorized_reviewers": ["one", "two"],
                "adjudicators": ["third"],
            }
        )
    )
    assert prepare(tmp_path)["registry"]["identity_verified"] is False


@pytest.mark.parametrize(
    "field",
    [
        "candidate_commit_sha",
        "qualification_environment",
        "pipeline_configuration_sha256",
        "deployment_attestation_sha256",
        "ingestion_url",
        "tenant_id",
        "authorization_env",
    ],
)
def test_contract_missing_service_field_never_probes(tmp_path, field):
    config, env = deployment_contract(tmp_path)
    config["cdp_services"].pop(field)

    def reject(*args):
        raise AssertionError("external probe forbidden")

    report = preflight(config, env, reject, directory=tmp_path)
    assert report["status"] == "INVALID_CONTRACT" and report["contract"]["status"] == "INVALID"


@pytest.mark.parametrize(
    "mutation",
    [
        "job",
        "relative_executable",
        "executable_hash",
        "approval",
        "attestation",
        "broker_probe",
        "canaries",
    ],
)
def test_contract_mismatch_never_activates(tmp_path, mutation):
    config, env = deployment_contract(tmp_path)
    if mutation == "job":
        config["jobs"].pop("RAW")
    if mutation == "relative_executable":
        config["jobs"]["RAW"]["argv"][0] = "python"
    if mutation == "executable_hash":
        config["jobs"]["RAW"]["executable_sha256"] = "0" * 64
    if mutation == "approval":
        config["approval_reference"] = ""
    if mutation == "attestation":
        (tmp_path / "deployment_attestation.local.json").write_text("{}")
    if mutation == "broker_probe":
        config.pop("broker_probe")
    if mutation == "canaries":
        config["cdp_services"]["ub04_canary_fingerprints"] = {}
    assert (
        preflight(config, env, lambda *args: True, directory=tmp_path)["status"]
        == "INVALID_CONTRACT"
    )


def test_only_complete_contract_and_connectivity_pass(tmp_path):
    config, env = deployment_contract(tmp_path)
    calls = []
    report = preflight(
        config, env, lambda name, values: calls.append(name) or True, directory=tmp_path
    )
    assert report["status"] == "PASS" and report["contract"]["status"] == "VALID"
    assert calls == ["database", "broker", "object_store"]
    env.pop("SYNTHETIC_KAFKA_SECURITY")
    calls.clear()
    assert (
        preflight(config, env, lambda *args: calls.append(args) or True, directory=tmp_path)[
            "connectivity"
        ]
        == "MISSING"
    )
    assert not calls


def test_broker_probe_preserves_environment_and_suppresses_output(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from evaluation.track_b_preflight import probe

    config, env = deployment_contract(tmp_path)

    def run(argv, **kwargs):
        assert kwargs["env"]["SYNTHETIC_KAFKA_SECURITY"] == "SECRET_SENTINEL"
        assert kwargs["stdout"] == kwargs["stderr"] == -3
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("evaluation.track_b_preflight.subprocess.run", run)
    assert probe("broker", {"broker_probe": config["broker_probe"], "probe_environment": env})


@pytest.mark.parametrize(
    "mutation", ["hash", "role", "owner", "reference", "future", "naive", "policy"]
)
def test_owner_receipt_invalidations(tmp_path, mutation):
    csv = tmp_path / "owner.csv"
    csv.write_text("synthetic")
    receipt = approve_csv(tmp_path, csv)
    assert owner_approval(tmp_path, digest(csv))["status"] == "PASS"
    if mutation == "hash":
        csv.write_text("changed")
    if mutation == "role":
        receipt["owner_role"] = "REVIEWER"
    if mutation == "owner":
        receipt["owner_id"] = "not-the-owner"
    if mutation == "reference":
        receipt["approval_reference"] = ""
    if mutation == "future":
        receipt["approved_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    if mutation == "naive":
        receipt["approved_at"] = "2026-01-01T00:00:00"
    if mutation == "policy":
        receipt["policy_id"] = ""
    (tmp_path / "membership_owner_approval.local.json").write_text(json.dumps(receipt))
    assert owner_approval(tmp_path, digest(csv))["status"] == "INVALID"


def job_config(script, max_attempts=2):
    exe = Path(sys.executable).resolve()
    return {
        "governed": True,
        "deployment_id": "synthetic",
        "approval_reference": "synthetic",
        "jobs": {
            "RAW": {
                "argv": [str(exe), str(script)],
                "executable_sha256": digest(exe),
                "max_attempts": max_attempts,
            }
        },
    }


def test_dead_executor_and_bounded_retry(tmp_path):
    from evaluation.track_b_jobs import PROCESSES, advance

    script = tmp_path / "die.py"
    script.write_text("raise SystemExit(3)")
    config = job_config(script)
    one = advance(tmp_path, "RAW", {}, config)
    PROCESSES[one["process_id"]].wait(timeout=10)
    failed = advance(tmp_path, "RAW", {}, config)
    assert failed["status"] == "EXECUTOR_FAILED" and failed["retryable"]
    two = advance(tmp_path, "RAW", {}, config)
    assert two["attempt"] == 2
    PROCESSES[two["process_id"]].wait(timeout=10)
    assert advance(tmp_path, "RAW", {}, config)["status"] == "EXECUTOR_FAILED"
    assert advance(tmp_path, "RAW", {}, config)["attempt"] == 2
    assert len(list((tmp_path / "jobs/RAW/attempts").glob("*/failure.local.json"))) == 2
    altered = copy.deepcopy(config)
    altered["approval_reference"] = "different"
    with pytest.raises(ValueError):
        advance(tmp_path, "RAW", {}, altered)


def test_launch_failure_is_recorded_and_retry_bounded(tmp_path, monkeypatch):
    from evaluation.track_b_jobs import advance

    script = tmp_path / "synthetic.py"
    script.write_text("pass")
    config = job_config(script)

    def fail(*args, **kwargs):
        raise OSError("SECRET_SENTINEL")

    monkeypatch.setattr("evaluation.track_b_jobs.subprocess.Popen", fail)
    assert advance(tmp_path, "RAW", {}, config)["attempt"] == 1
    assert advance(tmp_path, "RAW", {}, config)["attempt"] == 2
    result = advance(tmp_path, "RAW", {}, config)
    assert result["attempt"] == 2 and "SECRET_SENTINEL" not in json.dumps(result)


def test_receipt_overrides_markers_and_never_relaunches(tmp_path, monkeypatch):
    from evaluation.track_b_jobs import PROCESSES, advance

    script = tmp_path / "receipt.py"
    script.write_text("""import json,hashlib,sys
from pathlib import Path
request=Path(sys.argv[sys.argv.index('--qualification-request')+1])
receipt=Path(sys.argv[sys.argv.index('--qualification-receipt')+1])
r=json.loads(request.read_text());out=Path.cwd()/'synthetic-result.json';out.write_text('{}')
p={'request_id':r['request_id'],'status':'PASS','outputs':{out.name:hashlib.sha256(out.read_bytes()).hexdigest()}}
p['receipt_sha256']=hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':')).encode()).hexdigest()
receipt.write_text(json.dumps(p))
""")
    config = job_config(script)
    first = advance(tmp_path, "RAW", {}, config)
    PROCESSES[first["process_id"]].wait(timeout=10)

    def reject(*args, **kwargs):
        raise AssertionError("must not relaunch")

    monkeypatch.setattr("evaluation.track_b_jobs.subprocess.Popen", reject)
    assert advance(tmp_path, "RAW", {}, config)["status"] == "PASS"
    assert advance(tmp_path, "RAW", {}, config)["status"] == "PASS"
    assert len(list((tmp_path / "jobs/RAW/attempts").glob("*"))) == 1


def test_unknown_legacy_launch_never_retries(tmp_path):
    from evaluation.track_b_jobs import advance

    script = tmp_path / "synthetic.py"
    script.write_text("pass")
    config = job_config(script)
    folder = tmp_path / "jobs/RAW"
    folder.mkdir(parents=True)
    (folder / "submitted.local.json").write_text("{}")
    result = advance(tmp_path, "RAW", {}, config)
    assert result["status"] == "EXECUTOR_FAILED" and result["retryable"] is False


def test_concurrent_refresh_submits_only_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from evaluation.track_b_jobs import PROCESSES, advance

    script = tmp_path / "sleep.py"
    script.write_text("import time; time.sleep(0.5)")
    config = job_config(script)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(lambda _: advance(tmp_path, "RAW", {}, config), range(2)))
    assert all(o["status"] == "IN_PROGRESS" for o in outputs)
    assert len(list((tmp_path / "jobs/RAW/attempts").glob("*/submitted.local.json"))) == 1
    process_id = next(o["process_id"] for o in outputs if "process_id" in o)
    PROCESSES[process_id].wait(timeout=10)
