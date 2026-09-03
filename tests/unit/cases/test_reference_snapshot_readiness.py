import json

import yaml

from packages.reference_data import snapshot_readiness
from scripts.build_reference_snapshot import build_snapshot


def _row(identity: str) -> dict:
    return {
        "identity_key": identity,
        "source_record_id": f"record-{identity}",
        "source_lineage": ["payer-eligibility-export"],
        "reference_attributes": {"member_id": identity, "dob": "1980-01-01", "name": "JANE DOE", "zip": "10001"},
        "field_values": {"member_id": identity, "patient_name": "JANE DOE"},
        "record_status": "ACTIVE",
    }


def test_authorized_snapshot_and_config_are_ready_without_exposing_records(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps([_row("M-1")]), "utf-8")
    snapshot = tmp_path / "member"
    build_snapshot(
        source, snapshot, source_name="payer", reference_domain="AUTHORIZED_MEMBER",
        version="2026-09-01", source_contract_id="contract-1", approved_by="data-governance",
        independent_truth=True, non_circular_lineage=True,
    )
    config = tmp_path / "reference.yaml"
    config.write_text(yaml.safe_dump({"providers": [{
        "name": "payer", "type": "local_snapshot", "path": "member",
        "source_kind": "AUTHORIZED_MEMBER", "authorized": True, "enabled": True,
    }]}), "utf-8")
    report = snapshot_readiness(config)
    assert report["providers"][0]["ready"]
    assert report["records_exposed"] is False
    assert report["missing_domains"] == ["AUTHORIZED_PROVIDER"]


def test_builder_rejects_circular_prediction_lineage(tmp_path):
    row = _row("M-1")
    row["source_lineage"] = ["cdp-prediction"]
    source = tmp_path / "source.json"
    source.write_text(json.dumps([row]), "utf-8")
    try:
        build_snapshot(
            source, tmp_path / "member", source_name="payer",
            reference_domain="AUTHORIZED_MEMBER", version="v1",
        )
    except ValueError as exc:
        assert "circular source lineage" in str(exc)
    else:
        raise AssertionError("circular snapshot was accepted")
