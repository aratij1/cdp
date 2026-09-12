"""Verification helpers for immutable, checksum-pinned extraction releases."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_release_manifest(path: Path, *, configuration_root: Path = Path(".")) -> None:
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN":
        raise ValueError("release manifest is not frozen")
    for relative, expected in manifest.get("configuration_hashes", {}).items():
        actual = sha256_file(configuration_root / relative)
        if actual != expected:
            raise ValueError(
                f"frozen configuration changed without a new release: {relative}"
            )
