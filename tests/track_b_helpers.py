"""Explicit synthetic governing contracts for control-plane tests."""

import json
from datetime import UTC, datetime, timedelta

import yaml

from evaluation.track_b_inputs import current_registry, digest, registry_contract


def governed_registry(root, private, monkeypatch=None):
    now = datetime.now(UTC)
    rows = [
        {
            "reviewer_id": name,
            "role": role,
            "enabled": True,
            "independence_group": name,
            "qualification_scope": ["TRACK_B_150"],
            "effective_from": (now - timedelta(days=1)).isoformat(),
            "effective_to": (now + timedelta(days=30)).isoformat(),
            "provenance": "synthetic-only",
            "access_token_env": "SYNTHETIC_" + name.upper() + "_ACCESS",
        }
        for name, role in [("one", "REVIEWER"), ("two", "REVIEWER"), ("third", "ADJUDICATOR")]
    ]
    path = root / "config/qualification/reviewer_registry.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {"identity_verified": True, "policy_id": "synthetic-test", "reviewers": rows}
        )
    )
    private.mkdir(parents=True, exist_ok=True)
    (private / "reviewer_registry.local.json").write_text(json.dumps(registry_contract(path)))
    if monkeypatch:
        for row in rows:
            monkeypatch.setenv(row["access_token_env"], "synthetic-" + row["reviewer_id"])
    return current_registry(root, private)


def approve_csv(private, csv_path):
    receipt = {
        "owner_id": "Ashish Singh",
        "owner_role": "SOURCE_DATA_OWNER",
        "csv_sha256": digest(csv_path),
        "approved_at": datetime.now(UTC).isoformat(),
        "approval_reference": "synthetic-only",
        "policy_id": "synthetic-only",
    }
    (private / "membership_owner_approval.local.json").write_text(json.dumps(receipt))
    return receipt
