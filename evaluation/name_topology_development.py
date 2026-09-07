"""Source-only development and immutable freeze; no reference loader exists here."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from evaluation.name_topology_provenance import validated_baseline_sha
from evaluation.name_topology_rule import NameFieldTopology, is_name_label

DOC = Path("docs/closure/name_topology_generalization")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dev_sources(root: Path):
    split = json.loads((root / DOC / "name_topology_dev.json").read_text())
    aliases = {c["claim_alias"] for c in split["claims"]}
    catalog = json.loads(
        (root / "evaluation_results/governed_30_cohort/reviewed_pages.local.json").read_text()
    )
    for page in catalog:
        if page["claim_alias"] not in aliases:
            continue
        path = root / page["token_path"]
        data = json.loads(path.read_text())
        if (
            data["image_sha256"] != page["source_sha256"]
            or data.get("rotation", 0) != page["rotation"]
        ):
            raise ValueError("TOKEN_SOURCE_OR_FRAME_MISMATCH")
        if sha(Path(page["image_path"])) != page["source_sha256"]:
            raise ValueError("SOURCE_HASH_MISMATCH")
        yield page, data["tokens"]


def derive(root: Path) -> list[NameFieldTopology]:
    samples: dict[tuple[str, str], list[tuple[float, float, float, float]]] = {}
    for page, tokens in dev_sources(root):
        # Only form types actually represented by source-reviewed DEV packages.
        if page["form_type"] != "CMS1500":
            continue
        for field, (left, right) in {
            "patient_name": (0.01, 0.36),
            "insured_name": (0.58, 0.95),
        }.items():
            for token in tokens:
                x0, y0, x1, y1 = (
                    token["x0"] / page["width"],
                    token["y0"] / page["height"],
                    token["x1"] / page["width"],
                    token["y1"] / page["height"],
                )
                if left <= x0 < x1 <= right and 0.12 < y0 < 0.17 and is_name_label(token["text"]):
                    samples.setdefault((page["form_type"], field), []).append((x0, y0, x1, y1))
    result = []
    for (form, field), boxes in sorted(samples.items()):
        left = min(b[0] for b in boxes) - 0.008
        right = 0.36 if field == "patient_name" else min(0.96, max(b[2] for b in boxes) + 0.025)
        top = min(b[1] for b in boxes) - 0.015
        bottom = max(b[3] for b in boxes) + 0.04
        result.append(NameFieldTopology(form, field, (max(0, left), top, right, bottom)))
    return result


def freeze(root: Path) -> dict:
    baseline = validated_baseline_sha(root)
    code = [
        "evaluation/name_topology_rule.py",
        "evaluation/name_topology_development.py",
        "evaluation/name_topology_provenance.py",
        "workers/field_candidates/source_reviewed_anchor.py",
    ]
    rules = derive(root)
    value = {
        "version": "name-topology-dev-v1",
        "baseline_commit": baseline,
        "dev_manifest_sha256": sha(root / DOC / "name_topology_dev.json"),
        "validation_manifest_sha256": sha(root / DOC / "name_topology_validation.json"),
        "implementation_hashes": {name: sha(root / name) for name in code},
        "topologies": [asdict(rule) for rule in rules],
        "unsupported_contracts": [
            {"form_type": "UB", "field_name": field, "reason": "NO_DEV_UB_PACKAGE"}
            for field in ("patient_name", "insured_name")
        ],
        "development_reference_reads": 0,
        "development_validation_token_reads": 0,
        "historical_exposure": "ALL_30_PREVIOUSLY_USED; INHERITED_ASSEMBLER_PREVIOUSLY_FITTED",
        "gate": {
            "minimum_name_recall_gain_percentage_points": 20,
            "maximum_new_alternatives_per_field": 4,
            "maximum_mean_candidate_delta": 2,
            "no_recall_loss": True,
            "untouched_validation_required": True,
            "wrong_form_proposals_allowed": 0,
            "new_ocr_calls_allowed": 0,
        },
    }
    path = root / DOC / "name_topology_freeze.json"
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError("TOPOLOGY_ALREADY_FROZEN; REFUSING_PARAMETER_CHANGE")
    else:
        path.write_text(json.dumps(value, indent=2) + "\n")
    return value


if __name__ == "__main__":
    print(json.dumps(freeze(Path.cwd()), indent=2))
