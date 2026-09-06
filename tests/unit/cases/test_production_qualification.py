import json
from pathlib import Path

import yaml

from packages.production_qualification import qualify, write_qualification
from packages.release_freeze import sha256_file


def test_qualification_fails_closed_for_unexecuted_gates(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text("answer: 42\n", encoding="utf-8")
    frozen = tmp_path / "frozen.yaml"
    frozen.write_text(
        yaml.safe_dump({"status": "FROZEN", "configuration_hashes": {str(config): sha256_file(config)}}),
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.yaml"
    candidate.write_text(
        yaml.safe_dump({"pipeline_version": "candidate", "qualification": {}}),
        encoding="utf-8",
    )

    report = qualify(candidate, frozen)

    assert report.decision == "BLOCKED"
    assert report.gates[0].status == "PASS"
    assert all(gate.status == "NOT_TESTED" for gate in report.gates[1:])


def test_qualification_detects_frozen_drift_and_writes_evidence(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text("changed: true\n", encoding="utf-8")
    frozen = tmp_path / "frozen.yaml"
    frozen.write_text(
        yaml.safe_dump({"status": "FROZEN", "configuration_hashes": {str(config): "bad-hash"}}),
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.yaml"
    candidate.write_text(
        yaml.safe_dump({"pipeline_version": "candidate", "qualification": {"security_assessment": "PASS"}}),
        encoding="utf-8",
    )

    report = qualify(candidate, frozen)
    output = tmp_path / "qualification.json"
    write_qualification(report, output)

    assert report.decision == "BLOCKED"
    assert report.gates[0].status == "FAIL"
    assert '"decision": "BLOCKED"' in output.read_text(encoding="utf-8")


def test_qualification_does_not_trust_candidate_declared_pass(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text("answer: 42\n", encoding="utf-8")
    frozen = tmp_path / "frozen.yaml"
    frozen.write_text(
        yaml.safe_dump({"status": "FROZEN", "configuration_hashes": {str(config): sha256_file(config)}}),
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.yaml"
    candidate.write_text(
        yaml.safe_dump(
            {
                "pipeline_version": "candidate",
                "qualification": {"security_assessment": "PASS"},
            }
        ),
        encoding="utf-8",
    )

    report = qualify(candidate, frozen)

    security_gate = next(gate for gate in report.gates if gate.name == "security_assessment")
    assert security_gate.status == "NOT_TESTED"


def test_qualification_requires_verified_holdout_artifact(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text("answer: 42\n", encoding="utf-8")
    frozen = tmp_path / "frozen.yaml"
    frozen.write_text(
        yaml.safe_dump({"status": "FROZEN", "configuration_hashes": {str(config): sha256_file(config)}}),
        encoding="utf-8",
    )
    artifact = tmp_path / "holdout.json"
    artifact.write_text(
        json.dumps(
            {
                "status": "PASS",
                "metrics": {
                    "complete_claim_accuracy": 0.99,
                    "critical_false_accepts": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.yaml"
    candidate.write_text(
        yaml.safe_dump(
            {
                "pipeline_version": "candidate",
                "qualification_artifacts": {"vnext_holdout_accuracy": str(artifact)},
            }
        ),
        encoding="utf-8",
    )

    report = qualify(candidate, frozen)

    accuracy_gate = next(gate for gate in report.gates if gate.name == "vnext_holdout_accuracy")
    assert accuracy_gate.status == "PASS"
