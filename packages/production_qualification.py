"""Fail-closed production qualification evidence for CDP releases."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml

from packages.release_freeze import verify_release_manifest

GateStatus = Literal["PASS", "FAIL", "NOT_TESTED"]


@dataclass(frozen=True)
class Gate:
    name: str
    status: GateStatus
    evidence: str


@dataclass(frozen=True)
class Qualification:
    candidate: str
    generated_at: str
    decision: Literal["PROMOTABLE", "BLOCKED"]
    gates: tuple[Gate, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _artifact_gate(name: str, value: object, candidate_path: Path) -> Gate:
    if not isinstance(value, str) or not value.strip():
        return Gate(name, "NOT_TESTED", "no verified evidence artifact referenced")

    artifact_path = Path(value)
    if not artifact_path.is_absolute():
        artifact_path = candidate_path.parent.parent.parent / artifact_path
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Gate(name, "FAIL", f"unable to read evidence artifact: {exc}")

    if payload.get("status") != "PASS":
        return Gate(name, "FAIL", f"evidence artifact status is {payload.get('status', 'MISSING')}")

    if name == "vnext_holdout_accuracy":
        metrics = payload.get("metrics", payload)
        accuracy = metrics.get("complete_claim_accuracy")
        false_accepts = metrics.get("critical_false_accepts")
        if not isinstance(accuracy, (int, float)) or accuracy < 0.99:
            return Gate(name, "FAIL", "complete claim accuracy is below 0.99")
        if false_accepts != 0:
            return Gate(name, "FAIL", "critical false accepts must be zero")

    return Gate(name, "PASS", str(artifact_path))


def qualify(candidate_path: Path, frozen_path: Path) -> Qualification:
    candidate = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    artifacts = candidate.get("qualification_artifacts", {})
    gates: list[Gate] = []
    try:
        verify_release_manifest(frozen_path)
    except (OSError, ValueError, TypeError) as exc:
        gates.append(Gate("frozen_release_integrity", "FAIL", str(exc)))
    else:
        gates.append(Gate("frozen_release_integrity", "PASS", str(frozen_path)))

    mappings = {
        "vnext_holdout_accuracy": "vnext_holdout_accuracy",
        "full_pipeline_load_test": "full_pipeline_load",
        "kubernetes_keda_test": "kubernetes_keda",
        "disaster_recovery_test": "disaster_recovery",
        "security_assessment": "security_assessment",
    }
    gates.extend(
        _artifact_gate(label, artifacts.get(key), candidate_path)
        for key, label in mappings.items()
    )
    promotable = bool(gates) and all(gate.status == "PASS" for gate in gates)
    return Qualification(
        candidate=str(candidate.get("pipeline_version", candidate_path.stem)),
        generated_at=datetime.now(UTC).isoformat(),
        decision="PROMOTABLE" if promotable else "BLOCKED",
        gates=tuple(gates),
    )


def write_qualification(report: Qualification, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
