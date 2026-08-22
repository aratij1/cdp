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


def _declared_gate(name: str, value: object) -> Gate:
    normalized = str(value).upper()
    if normalized in {"PASS", "TESTED"}:
        return Gate(name, "PASS", f"candidate manifest declares {value}")
    if normalized in {"FAIL", "BLOCKED"}:
        return Gate(name, "FAIL", f"candidate manifest declares {value}")
    return Gate(name, "NOT_TESTED", f"candidate manifest declares {value}")


def qualify(candidate_path: Path, frozen_path: Path) -> Qualification:
    candidate = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    declared = candidate.get("qualification", {})
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
    gates.extend(_declared_gate(label, declared.get(key, "NOT_TESTED")) for key, label in mappings.items())
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
