"""Sealed inputs and package-restricted reference materialization."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from evaluation.name_topology_provenance import validated_baseline_sha
from workers.page_detection.text_extraction import TextLine

DOC = Path("docs/closure/non_name_cohort")
PRIVATE = Path("evaluation_results/non_name_cohort")


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read(p):
    return json.loads(Path(p).read_text())


def write(p, v):
    Path(p).write_text(json.dumps(v, indent=2) + "\n")


def verify(root):
    validated_baseline_sha(root)
    for p, h in read(root / DOC / "frozen_input_hashes.json").items():
        if digest(root / p) != h:
            raise ValueError("FROZEN_NAME_OR_BASELINE_INPUT_CHANGED: " + p)


def aliases(root, split):
    return {r["claim_alias"] for r in read(root / DOC / f"{split}_manifest.json")["claims"]}


def reference_subset(path, allowed):
    """Materialize only allowed top-level records of the sealed pretty JSON list.

    The first property is claim_alias. Disallowed records are streamed past;
    they are never accumulated or passed to json.loads in the coding path.
    """
    active = False
    block = []
    waiting = False
    with Path(path).open() as source:
        for line in source:
            if line.rstrip() == "  {":
                waiting = True
                active = False
                block = []
                continue
            if waiting:
                match = re.fullmatch(r'    "claim_alias": "([A-Z0-9_]+)",\s*', line)
                if not match:
                    raise ValueError("REFERENCE_LAYOUT_CHANGED")
                active = match[1] in allowed
                waiting = False
                if active:
                    block = ["{\n", line]
                continue
            if line.rstrip() in {"  },", "  }"}:
                if active:
                    block.append("}")
                    yield json.loads("".join(block))
                active = False
                block = []
            elif active:
                block.append(line)


def refs(root, split):
    if split not in {"dev", "validation"}:
        raise ValueError("INVALID_REFERENCE_PARTITION")
    if split == "validation":
        path = root / DOC / "non_name_strategy_freeze.json"
        if not path.exists():
            raise ValueError("VALIDATION_REFERENCE_ACCESS_BEFORE_FREEZE")
        for name, expected in read(path)["implementation_hashes"].items():
            if digest(root / name) != expected:
                raise ValueError("FROZEN_STRATEGY_CHANGED")
    allowed = aliases(root, split)
    freeze = read(root / "docs/closure/name_topology_generalization/fitted_result_freeze.json")
    entry = freeze["entries"][
        "evaluation_results/governed_30_root_collapse/root_collapse_records.local.json"
    ]
    path = root / entry["snapshot"]
    if digest(path) != entry["sha256"]:
        raise ValueError("REFERENCE_SNAPSHOT_CHANGED")
    return {
        (r["claim_alias"], r["field"]): r["reference_value"]
        for r in reference_subset(path, allowed)
    }


def pages(root, split):
    allowed = (
        aliases(root, split)
        if split != "full"
        else aliases(root, "dev") | aliases(root, "validation")
    )
    seal = read(root / "docs/closure/name_topology_generalization/fitted_result_freeze.json")
    catalog_name = "evaluation_results/governed_30_cohort/reviewed_pages.local.json"
    if digest(root / catalog_name) != seal["entries"][catalog_name]["sha256"]:
        raise ValueError("SOURCE_FORM_CATALOG_CHANGED")
    for p in read(root / catalog_name):
        if p["claim_alias"] not in allowed:
            continue
        token_path = Path(p["token_path"]).as_posix()
        if (
            digest(root / token_path) != seal["entries"][token_path]["sha256"]
            or digest(p["image_path"]) != p["source_sha256"]
        ):
            raise ValueError("SOURCE_OR_TOKEN_CHANGED")
        data = read(root / token_path)
        if data["image_sha256"] != p["source_sha256"] or data.get("rotation", 0) != p["rotation"]:
            raise ValueError("SOURCE_FRAME_MISMATCH")
        yield p, [TextLine(**t) for t in data["tokens"]]
