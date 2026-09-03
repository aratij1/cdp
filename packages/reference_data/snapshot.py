from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from packages.reference_enrichment.contracts import ReferenceLookupRequest, ReferenceRecord


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str
    reference_domain: str
    version: str
    snapshot_timestamp: datetime
    records_file: str = "records.json"
    records_sha256: str
    authorized: bool = False
    independent_truth: bool = False
    non_circular_lineage: bool = False
    source_contract_id: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def authorized_snapshots_require_governance(self) -> SnapshotManifest:
        if self.authorized and not all(
            (self.independent_truth, self.non_circular_lineage, self.source_contract_id,
             self.approved_by, self.approved_at)
        ):
            raise ValueError("authorized snapshot lacks governance approval or lineage")
        return self


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class LocalSnapshotProvider:
    root: Path
    test_only: bool = True

    @property
    def manifest(self) -> SnapshotManifest:
        return SnapshotManifest.model_validate_json((self.root / "manifest.json").read_text("utf-8"))

    @property
    def name(self) -> str:
        return self.manifest.source_name

    @property
    def provider_type(self) -> str:
        return self.manifest.reference_domain.upper()

    @property
    def authorized(self) -> bool:
        return self.manifest.authorized

    def lookup(self, request: ReferenceLookupRequest) -> list[ReferenceRecord]:
        manifest = self.manifest
        records_path = (self.root / manifest.records_file).resolve()
        if self.root.resolve() not in records_path.parents:
            raise ValueError("snapshot records path escapes snapshot root")
        if _sha256(records_path) != manifest.records_sha256:
            raise ValueError("reference snapshot checksum mismatch")
        rows = json.loads(records_path.read_text("utf-8"))
        output: list[ReferenceRecord] = []
        for row in rows:
            if row.get("identity_key") != request.identity_key:
                continue
            payload = dict(row)
            payload.update(
                provider_name=manifest.source_name,
                provider_type=manifest.reference_domain.upper(),
                provider_authorized=manifest.authorized,
                dataset_version=manifest.version,
                snapshot_timestamp=manifest.snapshot_timestamp,
                snapshot_checksum=manifest.records_sha256,
                independent_truth=manifest.independent_truth,
                non_circular_lineage=manifest.non_circular_lineage,
            )
            payload.pop("identity_key", None)
            output.append(ReferenceRecord.model_validate(payload))
        return output
