"""Freeze and verify the immutable Phase 8.12 validation replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from evaluation.phase8_12_tesseract_confirmation import canonical_replay

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "evaluation/baselines/phase8_12"
SOURCE = ROOT / "evaluation_results/phase8_11/candidate"
CONFIRMATION = ROOT / "evaluation_results/phase8_12/tesseract_confirmation/candidates.jsonl"
AS_OF_DATE = "2026-08-24"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def semantic_digest(path: Path) -> str:
    """Hash JSON output independent of set-to-list ordering."""
    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in sorted(value.items())}
        if isinstance(value, list):
            items = [normalize(item) for item in value]
            return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return value

    content = path.read_text("utf-8")
    value = (
        [json.loads(line) for line in content.splitlines() if line.strip()]
        if path.suffix == ".jsonl"
        else json.loads(content)
    )
    payload = json.dumps(normalize(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _files(base: Path) -> list[Path]:
    return sorted(path for path in base.rglob("*") if path.is_file() and path.name != "manifest.json")


def freeze() -> dict:
    inputs = BASELINE / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE / "extraction_records.jsonl", inputs / "extraction_records.jsonl")
    for source in ("source_a", "source_b", "source_c"):
        target = inputs / source
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / source / "policy_replay_input.jsonl", target / "policy_replay_input.jsonl")
    shutil.copyfile(CONFIRMATION, inputs / "candidates.jsonl")
    ids = sorted({
        item["document_id"]
        for source in ("SOURCE_A", "SOURCE_B", "SOURCE_C")
        for item in json.loads(
            (ROOT / "evaluation_data/phase8_8_generalization" / source / "manifest.json")
            .read_text("utf-8")
        )["documents"]
        if item["dataset_role"] == "VALIDATION"
    })
    (inputs / "validation_document_ids.json").write_text(json.dumps(ids, indent=2) + "\n", "utf-8")
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        shutil.copyfile(inputs / "candidates.jsonl", output / "candidates.jsonl")
        metrics = canonical_replay(
            output=output, replay_root=inputs,
            extraction_input=inputs / "extraction_records.jsonl",
            validation_ids_path=inputs / "validation_document_ids.json",
            as_of_date=__import__("datetime").date.fromisoformat(AS_OF_DATE),
        )
        output_hashes = {
            path.name: semantic_digest(path) for path in _files(output)
            if path.name.startswith("canonical_")
        }
    manifest = {
        "schema_version": "1.0", "phase": "8.12", "immutable": True,
        "evaluation_as_of_date": AS_OF_DATE, "locked_holdout_accessed": False,
        "input_hashes": {str(path.relative_to(BASELINE)).replace("\\", "/"): digest(path) for path in _files(inputs)},
        "output_hashes": output_hashes, "expected_metrics": metrics,
        "replay_command": "python -m evaluation.phase8_12_reproducibility replay",
    }
    (BASELINE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    return manifest


def replay() -> dict:
    manifest = json.loads((BASELINE / "manifest.json").read_text("utf-8"))
    mismatches = [name for name, expected in manifest["input_hashes"].items() if digest(BASELINE / name) != expected]
    if mismatches:
        raise SystemExit(f"immutable input hash mismatch: {mismatches}")
    inputs = BASELINE / "inputs"
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        shutil.copyfile(inputs / "candidates.jsonl", output / "candidates.jsonl")
        metrics = canonical_replay(
            output=output, replay_root=inputs,
            extraction_input=inputs / "extraction_records.jsonl",
            validation_ids_path=inputs / "validation_document_ids.json",
            as_of_date=__import__("datetime").date.fromisoformat(manifest["evaluation_as_of_date"]),
        )
        hashes = {path.name: semantic_digest(path) for path in _files(output) if path.name.startswith("canonical_")}
    if metrics != manifest["expected_metrics"] or hashes != manifest["output_hashes"]:
        raise SystemExit("Phase 8.12 replay differs from the frozen baseline")
    return {"status": "PASS", "metrics": metrics, "output_hashes": hashes}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "replay"))
    args = parser.parse_args()
    print(json.dumps(freeze() if args.action == "freeze" else replay(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
