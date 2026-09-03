from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from packages.reference_data.snapshot import SnapshotManifest


def snapshot_readiness(config_path: str | Path) -> dict:
    """Validate enabled snapshot authority without loading or exposing record contents."""
    path = Path(config_path)
    payload = yaml.safe_load(path.read_text("utf-8")) or {}
    results = []
    for provider in payload.get("providers", []):
        if provider.get("type") != "local_snapshot":
            continue
        reasons = []
        root = Path(provider["path"])
        if not root.is_absolute():
            root = (path.parent / root).resolve()
        try:
            manifest = SnapshotManifest.model_validate_json(
                (root / "manifest.json").read_text("utf-8")
            )
            records = (root / manifest.records_file).resolve()
            if root.resolve() not in records.parents:
                reasons.append("RECORDS_PATH_ESCAPES_SNAPSHOT")
            elif hashlib.sha256(records.read_bytes()).hexdigest() != manifest.records_sha256:
                reasons.append("RECORDS_CHECKSUM_MISMATCH")
            if not provider.get("enabled", False):
                reasons.append("PROVIDER_DISABLED")
            if not provider.get("authorized", False) or not manifest.authorized:
                reasons.append("PROVIDER_NOT_AUTHORIZED")
            if not manifest.independent_truth:
                reasons.append("TRUTH_NOT_INDEPENDENT")
            if not manifest.non_circular_lineage:
                reasons.append("LINEAGE_NOT_NON_CIRCULAR")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"SNAPSHOT_INVALID:{type(exc).__name__}")
            manifest = None
        results.append({
            "name": provider.get("name"),
            "domain": manifest.reference_domain if manifest else provider.get("source_kind"),
            "ready": not reasons,
            "reasons": reasons,
            "version": manifest.version if manifest else None,
            "records_sha256": manifest.records_sha256 if manifest else None,
        })
    ready_domains = sorted({item["domain"] for item in results if item["ready"]})
    required = {"AUTHORIZED_MEMBER", "AUTHORIZED_PROVIDER"}
    return {
        "ready": required.issubset(ready_domains),
        "ready_domains": ready_domains,
        "missing_domains": sorted(required - set(ready_domains)),
        "providers": results,
        "records_exposed": False,
    }
