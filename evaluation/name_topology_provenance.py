"""Fail-closed provenance for the frozen engineering experiment."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def validated_baseline_sha(root: Path) -> str:
    seal = json.loads(
        (root / "docs/closure/name_topology_generalization/fitted_result_freeze.json").read_text()
    )
    expected = seal["baseline_commit"]
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", expected) or actual != expected:
        raise ValueError("CHECKOUT_PROVENANCE_MISMATCH")
    return actual
