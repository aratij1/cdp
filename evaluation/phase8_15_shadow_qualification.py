"""Evaluate adjudicated real-source shadow claims without serving authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.shadow_evaluation import (
    AppendOnlyShadowClaimSink,
    ClaimShadowObservation,
    qualify_shadow_claims,
)


def _groups(path: Path, splits: set[str]) -> set[str]:
    groups: set[str] = set()
    if not path.is_dir():
        return groups
    for split in splits:
        target = path / f"{split}.jsonl"
        if not target.is_file():
            continue
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.strip():
                groups.add(str(json.loads(line)["source_group_id"]))
    return groups


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("observations", type=Path)
    parser.add_argument("--correction-dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    lines = [
        line for line in args.observations.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    first = json.loads(lines[0]) if lines else {}
    if first.get("schema_version") == "shadow-claim-capture-v1":
        # Verification uses only the public hash chain; the dummy key is never
        # used because identities were fingerprinted before persistence.
        rows = AppendOnlyShadowClaimSink(
            args.observations, identity_key=b"read-only-ledger-verification"
        ).observations()
    else:
        rows = [ClaimShadowObservation.model_validate_json(line) for line in lines]
    prohibited = (
        _groups(args.correction_dataset, {"train", "calibration"})
        if args.correction_dataset else set()
    )
    report = qualify_shadow_claims(rows, prohibited_source_groups=prohibited)
    payload = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.status == "QUALIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
