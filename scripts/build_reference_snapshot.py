"""Build a checksummed reference snapshot without printing record contents."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from packages.reference_enrichment.lineage import FORBIDDEN_ORIGINS

REQUIRED_KEYS = {
    "identity_key", "source_record_id", "source_lineage", "reference_attributes",
    "field_values", "record_status",
}


def build_snapshot(
    source: Path,
    destination: Path,
    *,
    source_name: str,
    reference_domain: str,
    version: str,
    source_contract_id: str | None = None,
    approved_by: str | None = None,
    independent_truth: bool = False,
    non_circular_lineage: bool = False,
) -> dict:
    if destination.exists():
        raise ValueError("snapshot destination already exists")
    rows = json.loads(source.read_text("utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("snapshot source must be a non-empty JSON array")
    identities = set()
    prepared = []
    for row in rows:
        missing = REQUIRED_KEYS - set(row)
        if missing:
            raise ValueError(f"snapshot record missing keys: {sorted(missing)}")
        identity = str(row["identity_key"])
        if identity in identities:
            raise ValueError("snapshot contains duplicate identity keys")
        identities.add(identity)
        lineage = {str(item).lower() for item in row["source_lineage"]}
        if not lineage or lineage & FORBIDDEN_ORIGINS:
            raise ValueError("snapshot record has missing or circular source lineage")
        payload = dict(row)
        payload["response_hash"] = hashlib.sha256(
            json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        prepared.append(payload)
    authorized = bool(source_contract_id and approved_by)
    if authorized and not (independent_truth and non_circular_lineage):
        raise ValueError("authorization requires independent, non-circular truth assertions")
    encoded = json.dumps(prepared, sort_keys=True, separators=(",", ":")).encode()
    destination.mkdir(parents=True)
    (destination / "records.json").write_bytes(encoded)
    manifest = {
        "source_name": source_name,
        "reference_domain": reference_domain.upper(),
        "version": version,
        "snapshot_timestamp": datetime.now(UTC).isoformat(),
        "records_file": "records.json",
        "records_sha256": hashlib.sha256(encoded).hexdigest(),
        "authorized": authorized,
        "independent_truth": independent_truth,
        "non_circular_lineage": non_circular_lineage,
        "source_contract_id": source_contract_id,
        "approved_by": approved_by,
        "approved_at": datetime.now(UTC).isoformat() if authorized else None,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    return {"records": len(prepared), "authorized": authorized, "records_sha256": manifest["records_sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--reference-domain", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-contract-id")
    parser.add_argument("--approved-by")
    parser.add_argument("--independent-truth", action="store_true")
    parser.add_argument("--non-circular-lineage", action="store_true")
    args = parser.parse_args()
    report = build_snapshot(
        args.source, args.destination, source_name=args.source_name,
        reference_domain=args.reference_domain, version=args.version,
        source_contract_id=args.source_contract_id, approved_by=args.approved_by,
        independent_truth=args.independent_truth,
        non_circular_lineage=args.non_circular_lineage,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
