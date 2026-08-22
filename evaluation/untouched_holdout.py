"""Dataset-level governance and immutable freezing for an untouched holdout."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


REQUIRED_CONDITIONS = {
    "clean_scan", "fax", "low_contrast", "rotation", "skew", "cropped_edges",
    "poor_dpi", "handwriting", "multi_page", "attachment", "difficult_table",
    "unstructured", "duplicate", "negative_non_claim",
}
REQUIRED_FAMILIES = {"CMS1500", "UB04"}


class HoldoutAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    source_id: str
    document_sha256: str
    truth_sha256: str
    perceptual_hash: str | None = None
    document_family: str
    conditions: set[str] = Field(default_factory=set)

    @field_validator("document_sha256", "truth_sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("expected lowercase SHA-256")
        return value.lower()


class HoldoutAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    separate_source: bool
    never_threshold_tuned: bool
    never_prompt_tuned: bool
    never_used_for_ocr_selection: bool
    never_used_for_registration_adjustment: bool
    never_inspected_during_development: bool
    attested_by: str
    evidence_reference: str

    def complete(self) -> bool:
        return all((self.separate_source, self.never_threshold_tuned, self.never_prompt_tuned,
                    self.never_used_for_ocr_selection,
                    self.never_used_for_registration_adjustment,
                    self.never_inspected_during_development))


class FrozenHoldoutManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_version: str
    created_at: str
    status: str = "FROZEN"
    assets: list[HoldoutAsset]
    attestation: HoldoutAttestation
    composition: dict[str, int]
    manifest_sha256: str


class UntouchedHoldoutBuilder:
    def __init__(
        self,
        *,
        development_hashes: set[str],
        development_perceptual_hashes: set[str],
        development_source_ids: set[str],
        minimum_documents: int = 100,
    ) -> None:
        self.development_hashes = development_hashes
        self.development_perceptual_hashes = development_perceptual_hashes
        self.development_source_ids = development_source_ids
        self.minimum_documents = minimum_documents

    def freeze(
        self,
        assets: list[HoldoutAsset],
        attestation: HoldoutAttestation,
        *,
        dataset_version: str,
        output: Path,
    ) -> FrozenHoldoutManifest:
        errors = self.audit(assets, attestation)
        if errors:
            raise ValueError("holdout is not freeze-eligible: " + ", ".join(errors))
        if output.exists():
            raise FileExistsError("frozen holdout manifest is immutable; use a new dataset version")
        ordered = sorted(assets, key=lambda asset: asset.asset_id)
        composition = self._composition(ordered)
        payload = {
            "dataset_version": dataset_version,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "FROZEN",
            "assets": [asset.model_dump(mode="json") for asset in ordered],
            "attestation": attestation.model_dump(mode="json"),
            "composition": composition,
        }
        digest = self._digest(payload)
        manifest = FrozenHoldoutManifest(**payload, manifest_sha256=digest)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return manifest

    def audit(self, assets: list[HoldoutAsset], attestation: HoldoutAttestation) -> list[str]:
        errors: list[str] = []
        if not attestation.complete():
            errors.append("INCOMPLETE_UNTOUCHED_ATTESTATION")
        if len(assets) < self.minimum_documents:
            errors.append("INSUFFICIENT_DOCUMENTS")
        if len({asset.asset_id for asset in assets}) != len(assets):
            errors.append("DUPLICATE_ASSET_ID")
        if any(asset.document_sha256 in self.development_hashes for asset in assets):
            errors.append("EXACT_DEVELOPMENT_OVERLAP")
        if any(asset.perceptual_hash in self.development_perceptual_hashes
               for asset in assets if asset.perceptual_hash):
            errors.append("PERCEPTUAL_DEVELOPMENT_OVERLAP")
        if any(asset.source_id in self.development_source_ids for asset in assets):
            errors.append("DEVELOPMENT_SOURCE_REUSED")
        families = {asset.document_family for asset in assets}
        if not REQUIRED_FAMILIES <= families:
            errors.append("MISSING_DOCUMENT_FAMILY")
        conditions = set().union(*(asset.conditions for asset in assets)) if assets else set()
        if not REQUIRED_CONDITIONS <= conditions:
            errors.append("MISSING_COMPOSITION_CONDITION")
        return errors

    @staticmethod
    def verify(path: Path) -> FrozenHoldoutManifest:
        raw = json.loads(path.read_text("utf-8"))
        expected = raw.pop("manifest_sha256")
        if raw.get("status") != "FROZEN" or UntouchedHoldoutBuilder._digest(raw) != expected:
            raise ValueError("frozen holdout manifest integrity check failed")
        return FrozenHoldoutManifest(**raw, manifest_sha256=expected)

    @staticmethod
    def _composition(assets: list[HoldoutAsset]) -> dict[str, int]:
        keys = REQUIRED_CONDITIONS | REQUIRED_FAMILIES
        return {key: sum(key == asset.document_family or key in asset.conditions for asset in assets)
                for key in sorted(keys)}

    @staticmethod
    def _digest(payload: dict) -> str:
        normalized = json.loads(json.dumps(payload, default=list))
        for asset in normalized.get("assets", []):
            asset["conditions"] = sorted(asset.get("conditions", []))
        canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(canonical).hexdigest()
