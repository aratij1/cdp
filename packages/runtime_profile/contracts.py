from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

import yaml
from pydantic import ConfigDict

from packages.domain.common import DomainModel

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_RUNTIME_PROFILE_PATH = ROOT / "config/runtime_profiles/canonical_runtime_v1.yaml"
HISTORICAL_PHASE8_10_PROFILE_PATH = ROOT / "config/runtime_profiles/historical_phase8_10.yaml"


class RuntimeProfileStatus(StrEnum):
    RUNTIME = "RUNTIME"
    HISTORICAL_ONLY = "HISTORICAL_ONLY"


def canonical_file_sha256(path: Path) -> str:
    """Hash repository text independently of checkout line-ending policy."""
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class RuntimeDecisionProfile(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: str
    profile_version: str
    profile_status: RuntimeProfileStatus
    evidence_policy_path: str
    evidence_policy_sha256: str
    field_policy_path: str
    field_policy_sha256: str
    route_registry_path: str
    route_registry_sha256: str
    route_mode: str
    criticality_config_path: str
    criticality_config_sha256: str
    claim_policy_path: str
    claim_policy_sha256: str
    reference_config_path: str
    reference_config_sha256: str
    created_at: datetime
    calibration_registry_path: str | None = None
    calibration_registry_sha256: str | None = None

    @classmethod
    def load(cls, path: str | Path = CANONICAL_RUNTIME_PROFILE_PATH) -> RuntimeDecisionProfile:
        profile = cls.model_validate(yaml.safe_load(Path(path).read_text("utf-8")))
        profile.verify_hashes()
        return profile

    def resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else ROOT / path

    def verify_hashes(self) -> None:
        for path_field, hash_field in (
            ("evidence_policy_path", "evidence_policy_sha256"),
            ("field_policy_path", "field_policy_sha256"),
            ("route_registry_path", "route_registry_sha256"),
            ("criticality_config_path", "criticality_config_sha256"),
            ("claim_policy_path", "claim_policy_sha256"),
            ("reference_config_path", "reference_config_sha256"),
        ):
            path = self.resolve(getattr(self, path_field))
            actual = canonical_file_sha256(path)
            expected = getattr(self, hash_field)
            if actual != expected:
                raise ValueError(f"RUNTIME_PROFILE_HASH_MISMATCH:{path_field}:{expected}:{actual}")
        if bool(self.calibration_registry_path) != bool(self.calibration_registry_sha256):
            raise ValueError("RUNTIME_PROFILE_CALIBRATION_PATH_HASH_MUST_BE_PAIRED")
        if self.calibration_registry_path and self.calibration_registry_sha256:
            path = self.resolve(self.calibration_registry_path)
            actual = canonical_file_sha256(path)
            if actual != self.calibration_registry_sha256:
                raise ValueError(
                    "RUNTIME_PROFILE_HASH_MISMATCH:calibration_registry_path:"
                    f"{self.calibration_registry_sha256}:{actual}"
                )

    def decision_identity(self) -> dict[str, str]:
        return {
            "runtime_profile_id": f"{self.profile_id}@{self.profile_version}",
            "evidence_policy_hash": self.evidence_policy_sha256,
            "route_registry_hash": self.route_registry_sha256,
            "route_mode": self.route_mode,
            "field_policy_hash": self.field_policy_sha256,
            "claim_policy_hash": self.claim_policy_sha256,
        }

    def matches_runtime(self, runtime: RuntimeDecisionProfile) -> bool:
        return (
            self.profile_status is RuntimeProfileStatus.RUNTIME
            and runtime.profile_status is RuntimeProfileStatus.RUNTIME
            and self.model_dump(mode="json") == runtime.model_dump(mode="json")
        )
