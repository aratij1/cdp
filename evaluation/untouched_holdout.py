"""Dataset-level governance and immutable freezing for an untouched holdout."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


REQUIRED_CONDITIONS = {
    "clean_digital", "office_scan", "fax_scan", "low_dpi", "high_dpi",
    "skew", "rotation", "perspective_distortion", "cropped_edges",
    "compression_artifacts", "low_contrast", "noise", "handwriting",
    "multiple_fonts", "multi_page_bundle", "attachment", "duplicate_page",
    "negative_non_claim", "realistic_blank_fields", "optional_fields",
    "service_line_table", "unstructured_attachment",
}
REQUIRED_FAMILIES = {"CMS1500", "UB04"}


class HoldoutAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    source_id: str
    document_sha256: str
    page_sha256: list[str]
    truth_sha256: str
    perceptual_hash: str | None = None
    document_family: str
    image_quality_bucket: str
    field_counts: dict[str, int] = Field(default_factory=dict)
    criticality_counts: dict[str, int] = Field(default_factory=dict)
    conditions: set[str] = Field(default_factory=set)

    @field_validator("document_sha256", "truth_sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("expected lowercase SHA-256")
        return value.lower()

    @field_validator("page_sha256")
    @classmethod
    def valid_page_sha256(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("at least one page SHA-256 is required")
        for value in values:
            if len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value.lower()
            ):
                raise ValueError("expected lowercase page SHA-256")
        return [value.lower() for value in values]


class HoldoutAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    separate_source: bool
    never_threshold_tuned: bool
    never_prompt_tuned: bool
    never_used_for_ocr_selection: bool
    never_used_for_registration_adjustment: bool
    never_used_for_roi_tuning: bool
    never_used_for_preprocessing_tuning: bool
    never_used_for_policy_tuning: bool
    never_used_for_blocking_field_tuning: bool
    never_used_for_route_selection: bool
    never_used_for_confidence_calibration: bool
    never_used_for_reference_matching_tuning: bool
    never_inspected_during_development: bool
    attested_by: str
    evidence_reference: str

    def complete(self) -> bool:
        governed = self.model_dump(exclude={"attested_by", "evidence_reference"})
        return all(governed.values())


class FrozenHoldoutManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_version: str
    created_at: str
    source_description: str
    status: str = "FROZEN"
    assets: list[HoldoutAsset]
    attestation: HoldoutAttestation
    composition: dict[str, int]
    sample_targets: dict
    manifest_sha256: str


class UntouchedHoldoutBuilder:
    def __init__(
        self,
        *,
        development_hashes: set[str],
        development_perceptual_hashes: set[str],
        development_source_ids: set[str],
        minimum_documents: int = 100,
        minimum_pages: int = 0,
        minimum_fields: int = 0,
        minimum_documents_by_family: dict[str, int] | None = None,
        minimum_observations_by_field: dict[str, int] | None = None,
        minimum_observations_by_criticality: dict[str, int] | None = None,
        minimum_documents_by_quality: dict[str, int] | None = None,
    ) -> None:
        self.development_hashes = development_hashes
        self.development_perceptual_hashes = development_perceptual_hashes
        self.development_source_ids = development_source_ids
        self.minimum_documents = minimum_documents
        self.minimum_pages = minimum_pages
        self.minimum_fields = minimum_fields
        self.minimum_documents_by_family = minimum_documents_by_family or {}
        self.minimum_observations_by_field = minimum_observations_by_field or {}
        self.minimum_observations_by_criticality = minimum_observations_by_criticality or {}
        self.minimum_documents_by_quality = minimum_documents_by_quality or {}

    def freeze(
        self,
        assets: list[HoldoutAsset],
        attestation: HoldoutAttestation,
        *,
        dataset_version: str,
        source_description: str,
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
            "source_description": source_description,
            "status": "FROZEN",
            "assets": [asset.model_dump(mode="json") for asset in ordered],
            "attestation": attestation.model_dump(mode="json"),
            "composition": composition,
            "sample_targets": self.sample_targets(),
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
        if sum(len(asset.page_sha256) for asset in assets) < self.minimum_pages:
            errors.append("INSUFFICIENT_PAGES")
        if sum(sum(asset.field_counts.values()) for asset in assets) < self.minimum_fields:
            errors.append("INSUFFICIENT_FIELDS")
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
        family_counts = {
            family: sum(asset.document_family == family for asset in assets)
            for family in self.minimum_documents_by_family
        }
        if any(
            family_counts[family] < target
            for family, target in self.minimum_documents_by_family.items()
        ):
            errors.append("INSUFFICIENT_DOCUMENT_FAMILY_SAMPLE")
        field_counts = {
            field: sum(asset.field_counts.get(field, 0) for asset in assets)
            for field in self.minimum_observations_by_field
        }
        if any(
            field_counts[field] < target
            for field, target in self.minimum_observations_by_field.items()
        ):
            errors.append("INSUFFICIENT_FIELD_SAMPLE")
        criticality_counts = {
            level: sum(asset.criticality_counts.get(level, 0) for asset in assets)
            for level in self.minimum_observations_by_criticality
        }
        if any(
            criticality_counts[level] < target
            for level, target in self.minimum_observations_by_criticality.items()
        ):
            errors.append("INSUFFICIENT_CRITICALITY_SAMPLE")
        quality_counts = {
            bucket: sum(asset.image_quality_bucket == bucket for asset in assets)
            for bucket in self.minimum_documents_by_quality
        }
        if any(
            quality_counts[bucket] < target
            for bucket, target in self.minimum_documents_by_quality.items()
        ):
            errors.append("INSUFFICIENT_IMAGE_QUALITY_SAMPLE")
        return errors

    def sample_targets(self) -> dict:
        return {
            "minimum_documents": self.minimum_documents,
            "minimum_pages": self.minimum_pages,
            "minimum_fields": self.minimum_fields,
            "minimum_documents_by_family": self.minimum_documents_by_family,
            "minimum_observations_by_field": self.minimum_observations_by_field,
            "minimum_observations_by_criticality": self.minimum_observations_by_criticality,
            "minimum_documents_by_quality": self.minimum_documents_by_quality,
        }

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
        composition = {
            key: sum(key == asset.document_family or key in asset.conditions for asset in assets)
            for key in sorted(keys)
        }
        composition["documents"] = len(assets)
        composition["pages"] = sum(len(asset.page_sha256) for asset in assets)
        composition["fields"] = sum(sum(asset.field_counts.values()) for asset in assets)
        return composition

    @staticmethod
    def _digest(payload: dict) -> str:
        normalized = json.loads(json.dumps(payload, default=list))
        for asset in normalized.get("assets", []):
            asset["conditions"] = sorted(asset.get("conditions", []))
        canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(canonical).hexdigest()
