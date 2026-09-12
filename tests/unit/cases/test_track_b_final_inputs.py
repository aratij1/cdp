"""Synthetic governance and connectivity tests; no qualification claims."""

import csv
import json
from datetime import UTC, datetime

import pytest
import yaml

from evaluation.track_b_inputs import digest, ingest_membership, registry_contract
from evaluation.track_b_preflight import ENV_KEYS, preflight


def roster():
    return {
        "identity_verified": True,
        "policy_id": "synthetic",
        "reviewers": [
            {
                "reviewer_id": name,
                "role": role,
                "enabled": True,
                "independence_group": name,
                "qualification_scope": ["TRACK_B_150"],
                "effective_from": "2026-01-01T00:00:00Z",
                "effective_to": "2027-01-01T00:00:00Z",
                "provenance": "synthetic-only",
                "access_token_env": "SYNTHETIC_" + name.upper() + "_ACCESS",
            }
            for name, role in [("a", "REVIEWER"), ("b", "REVIEWER"), ("c", "ADJUDICATOR")]
        ],
    }


def test_registry_requires_real_operator_enablement(tmp_path):
    p = tmp_path / "registry.yaml"
    p.write_text("identity_verified: false\nreviewers: []")
    assert not registry_contract(p)["identity_verified"]


@pytest.mark.parametrize(
    "mutation", ["same_identity", "same_group", "expired", "owner_only", "no_provenance"]
)
def test_registry_rejects_invalid_independence(tmp_path, mutation):
    data = roster()
    if mutation == "same_identity":
        data["reviewers"][1]["reviewer_id"] = " A "
    if mutation == "same_group":
        data["reviewers"][2]["independence_group"] = "a"
    if mutation == "expired":
        data["reviewers"][0]["effective_to"] = "2025-01-01T00:00:00Z"
    if mutation == "owner_only":
        data["reviewers"] = data["reviewers"][:1]
    if mutation == "no_provenance":
        data["reviewers"][0]["provenance"] = ""
    p = tmp_path / "registry.yaml"
    p.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError):
        registry_contract(p, datetime(2026, 9, 7, tzinfo=UTC))


def test_valid_registry_projects_existing_contract(tmp_path):
    p = tmp_path / "registry.yaml"
    p.write_text(yaml.safe_dump(roster()))
    result = registry_contract(p, datetime(2026, 9, 7, tzinfo=UTC))
    assert result["authorized_reviewers"] == ["a", "b"] and result["adjudicators"] == ["c"]


def test_missing_deployment_never_contacts_services():
    def reject(*args):
        raise AssertionError("must not contact target")

    result = preflight({}, {}, reject)
    assert result["status"] == "INVALID_CONTRACT"


def test_preflight_does_not_emit_secret_exceptions(tmp_path):
    config = {key: key.upper() for key in ENV_KEYS}
    config.update(
        governed=True,
        qualification_host="synthetic.invalid",
        environment="test",
        execution_provider="CPU",
        deployment_id="synthetic",
        approval_reference="synthetic",
    )
    path = tmp_path / "config.json"
    path.write_text("{}")
    env = {value: "SECRET_SENTINEL" for value in config.values() if isinstance(value, str)}
    env[config["authority_config_env"]] = str(path)
    env[config["pricing_config_env"]] = str(path)

    def fail(*args):
        raise RuntimeError("SECRET_SENTINEL")

    from tests.unit.cases.test_track_b_hardening import deployment_contract

    config, env = deployment_contract(tmp_path)
    result = preflight(config, env, fail, directory=tmp_path)
    assert result["status"] == "UNREACHABLE" and "SECRET_SENTINEL" not in json.dumps(result)


def fixture_csv(root):
    private = root / "evaluation_results/qualification_closure"
    private.mkdir(parents=True)
    out = root / "evaluation_results/real_release"
    out.mkdir(parents=True)
    row = {
        "review_page_alias": "page-0001",
        "source_hash_alias": "hash-0001",
        "claim_alias_to_fill": "",
        "owner_confirmation": "",
        "membership_status": "UNBOUND",
    }
    p = out / "150_cohort_missing_membership.csv"
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)
    binding = {"source_page_id": "page", "state": "EXACT"}
    lookup = private / "blind_lineage_alias_lookup.local.json"
    lookup.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "review_page_alias": "page-0001",
                        "source": {"page_id": "page"},
                        "binding": binding,
                    }
                ]
            }
        )
    )
    (private / "source_page_bindings.local.json").write_text(json.dumps({"bindings": [binding]}))
    (private / "membership_lineage_seal.local.json").write_text(
        json.dumps(
            {
                "lookup_sha256": digest(lookup),
                "columns": ["review_page_alias", "source_hash_alias"],
                "rows": {
                    "page-0001": {
                        "review_page_alias": "page-0001",
                        "source_hash_alias": "hash-0001",
                    }
                },
            }
        )
    )
    return p, private


def test_unapproved_membership_never_materializes_authority(tmp_path):
    _, private = fixture_csv(tmp_path)
    report = ingest_membership(tmp_path)
    assert report["unbound_pages"] == 1 and report["owner_approval"] == "PENDING"
    assert not (private / "claim_membership.local.json").exists()


@pytest.mark.parametrize("replacement", ["hash-0002", "page-9999"])
def test_owner_cannot_rewrite_lineage(tmp_path, replacement):
    p, _ = fixture_csv(tmp_path)
    before = "hash-0001" if replacement.startswith("hash") else "page-0001"
    p.write_text(p.read_text().replace(before, replacement))
    with pytest.raises(ValueError):
        ingest_membership(tmp_path)


def test_approved_csv_materializes_exact_claim_and_rejects_later_rewrite(tmp_path, monkeypatch):
    from evaluation import two_track_isolation

    p, private = fixture_csv(tmp_path)
    asset = tmp_path / "synthetic.bin"
    asset.write_bytes(b"synthetic-source")
    binding = {
        "source_page_id": "page",
        "cdp_page_id": "cdp-page",
        "state": "EXACT",
        "package_id": "package",
        "source_asset_sha256": digest(asset),
        "rendered_page_sha256": "a" * 64,
        "cdp_page_sha256": "a" * 64,
    }
    lookup = private / "blind_lineage_alias_lookup.local.json"
    lookup.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "review_page_alias": "page-0001",
                        "source": {
                            "page_id": "page",
                            "package_id": "package",
                            "source_asset_path": str(asset),
                            "source_asset_sha256": digest(asset),
                        },
                        "binding": binding,
                    }
                ]
            }
        )
    )
    (private / "source_page_bindings.local.json").write_text(json.dumps({"bindings": [binding]}))
    seal = private / "membership_lineage_seal.local.json"
    data = json.loads(seal.read_text())
    data["lookup_sha256"] = digest(lookup)
    seal.write_text(json.dumps(data))
    with p.open(newline="") as f:
        rows = list(csv.DictReader(f))
    rows[0].update(
        claim_alias_to_fill="claim-1",
        owner_confirmation="CONFIRM",
        membership_status="EXACT",
        document_alias="doc-1",
        page_role="CLAIM_FORM",
        claim_page_order="1",
        membership_provenance="synthetic-owner-evidence",
        owner_approved_at="2026-01-01T00:00:00Z",
        claim_complete_confirmed="YES",
    )
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    monkeypatch.setattr(
        two_track_isolation,
        "_build",
        lambda root: {"status": "PASS", "source_seals_verified": True},
    )
    from tests.track_b_helpers import approve_csv

    approve_csv(private, p)
    report = ingest_membership(tmp_path)
    assert report["exact_claims"] == 1 and report["owner_approval"] == "PASS"
    assert (private / "claim_membership.local.json").exists()
    p.write_text(p.read_text().replace("claim-1", "claim-2"))
    with pytest.raises(ValueError, match="APPROVED_MEMBERSHIP_CHANGED"):
        ingest_membership(tmp_path)


def test_review_provenance_required_and_bound_to_source(tmp_path):
    from evaluation.track_b_review_provenance import record, verify

    row = {
        "page_id": "p",
        "reviewer_id": "a",
        "source_sha256": "b" * 64,
        "annotation": {"fields": {}},
    }
    assert not verify(tmp_path, [row], [])
    record(tmp_path, "REVIEW_COMPLETE", "p", "a", "b" * 64, row["annotation"], round_name="1")
    assert verify(tmp_path, [row], [])
    row["source_sha256"] = "c" * 64
    assert not verify(tmp_path, [row], [])


def test_final_report_keeps_cached_cost_out_and_exposes_percentages(tmp_path):
    from evaluation.track_b_report import build

    out = tmp_path / "docs/qualification/track_b_completion"
    out.mkdir(parents=True)
    (out / "track_a_freeze.json").write_text(json.dumps({"runtime_hashes": {}}))
    report = build(
        tmp_path,
        {
            "scoring": {
                "raw": {"accuracy": 0.5, "accuracy_numerator": 1, "accuracy_denominator": 2},
                "post_hitl": {"critical_accuracy": 1},
            },
            "cost": {"paid_ai_cost_per_page": "0", "scope": "CACHED_ENGINEERING_ONLY"},
        },
    )
    assert report["raw_metrics"]["Field accuracy"]["percentage"] == 50
    assert report["cost"] == {} and report["status"] == "EXTERNAL_INPUT_REQUIRED"
    assert report["post_hitl"]["critical_accuracy"] == 1


def test_operational_resume_and_duplicate_evidence_cannot_be_omitted(tmp_path):
    from evaluation.track_b_preflight import operational_extensions

    assert (
        operational_extensions({}, {"status": "PASS", "checks": {}}, tmp_path)["status"]
        == "NOT_AVAILABLE"
    )


def test_operational_extensions_require_actual_hashes(tmp_path):
    from evaluation.track_b_preflight import operational_extensions

    artifact = tmp_path / "synthetic-evidence.json"
    artifact.write_text("{}")
    payload = {
        "checks": {
            k: {"status": "PASS", "artifact": artifact.name, "artifact_sha256": digest(artifact)}
            for k in ("partial_output_resume", "duplicate_event", "duplicate_output_protection")
        }
    }
    assert (
        operational_extensions(payload, {"status": "PASS", "checks": {}}, tmp_path)["status"]
        == "PASS"
    )
    artifact.write_text('{"changed":true}')
    assert (
        operational_extensions(payload, {"status": "PASS", "checks": {}}, tmp_path)["status"]
        == "FAIL"
    )


def test_governed_login_requires_identity_specific_access_code(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from evaluation.annotation_app import qualification_review as ui

    data = tmp_path / "evaluation_results/qualification_closure"
    data.mkdir(parents=True)
    contract = tmp_path / "config/qualification/reviewer_registry.yaml"
    contract.parent.mkdir(parents=True)
    roster_data = roster()
    for entry in roster_data["reviewers"]:
        entry["access_token_env"] = "SYNTHETIC_" + entry["reviewer_id"].upper() + "_ACCESS"
    contract.write_text(yaml.safe_dump(roster_data))
    (data / "reviewer_registry.local.json").write_text(json.dumps(registry_contract(contract)))
    (data / "blind_source_views.local.json").write_text("[]")
    monkeypatch.setattr(ui, "DATA", data)
    monkeypatch.setenv("SYNTHETIC_A_ACCESS", "synthetic-a")
    monkeypatch.setenv("SYNTHETIC_B_ACCESS", "synthetic-b")
    app = FastAPI()
    app.include_router(ui.router)
    client = TestClient(app)
    for code in ("", "synthetic-a"):
        assert (
            client.post(
                "/qualification-review/login",
                data={"reviewer": "b", "access_code": code},
                follow_redirects=False,
            ).status_code
            == 403
        )
    assert (
        client.post(
            "/qualification-review/login",
            data={"reviewer": "b", "access_code": "synthetic-b"},
            follow_redirects=False,
        ).status_code
        == 303
    )
