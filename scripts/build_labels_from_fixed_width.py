"""Offline-only label builder from supplied fixed-width keyed outputs.

This module is deliberately located under ``scripts`` and must never be imported
by runtime extraction code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from packages.specification_registry import SpecificationRegistry

CRITICAL_TOKENS = {
    "patient_name", "patient_first", "patient_last", "date_of_birth",
    "member_id", "provider_npi", "tax_id", "diagnosis",
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _split(index: int) -> str:
    remainder = index % 5
    return "holdout" if remainder == 0 else "validation" if remainder == 4 else "calibration"


def _document_hash(group: str, image_name: str) -> str:
    return hashlib.sha256(f"{group}/{image_name}".encode()).hexdigest()


def _output_files(dataset: Path) -> list[tuple[str, str, Path]]:
    result = []
    for group_dir in sorted(dataset.glob("Group ?")):
        for path in group_dir.glob("*.txt"):
            output_format = "ub92" if "_UB_" in path.name.upper() else "nsf"
            result.append((group_dir.name[-1], output_format, path))
    return result


def _windows_copy_number(path: Path) -> int:
    """Order "Name.ext", "Name (2).ext", "Name (3).ext", ... by copy number.

    These images come from a Windows Explorer "Save As" / copy sequence, so
    the unsuffixed file is claim 1 and "(N)" is claim N -- plain lexical
    sort instead puts "(10)", "(11)", "(12)" before "(2)" and the bare file
    last, silently mis-pairing every claim record with the wrong image.
    """
    match = re.search(r"\((\d+)\)", path.stem)
    return 1 if match is None else int(match.group(1))


def _images(dataset: Path, group: str) -> list[Path]:
    directory = dataset / f"Group {group}"
    return sorted(
        (path for path in directory.iterdir()
         if path.suffix.lower() not in {".txt", ".json", ".csv"}),
        key=_windows_copy_number,
    )


def _claim_chunks(lines: list[str], output_format: str) -> list[list[str]]:
    start_type = "10" if output_format == "ub92" else "BA0"
    chunks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith(start_type):
            if current:
                chunks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current:
        chunks.append(current)
    return chunks


def build_labels(dataset: Path, registry: SpecificationRegistry) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    for group, output_format, output_path in _output_files(dataset):
        specs = registry.load_all(output_format)
        lines = output_path.read_bytes().decode("ascii").splitlines()
        chunks = _claim_chunks(lines, output_format)
        images = _images(dataset, group)
        if len(chunks) != len(images):
            raise ValueError(
                f"Group {group}: {len(chunks)} keyed claims cannot be deterministically "
                f"associated with {len(images)} image documents"
            )
        for index, (chunk, image) in enumerate(zip(chunks, images, strict=True), start=1):
            document_id = _document_hash(group, image.name)
            for line in chunk:
                record_type = line[:2] if output_format == "ub92" else line[:3]
                spec = specs.get(record_type)
                if spec is None or len(line) != spec.record_length:
                    continue
                for field in spec.fields:
                    raw = line[field.start_position - 1:field.end_position]
                    canonical = _slug(field.field_name)
                    labels.append({
                        "document_id_hash": document_id,
                        "group": group,
                        "form_type": (
                            "UB_INSTITUTIONAL" if output_format == "ub92"
                            else "CMS1500_OR_ATTACHMENT"
                        ),
                        "output_format": output_format,
                        "record_type": record_type,
                        "field_number": field.field_number,
                        "canonical_field_name": canonical,
                        "expected_raw_value": raw,
                        "expected_normalized_value": raw.strip(),
                        "criticality": (
                            "critical"
                            if any(token in canonical for token in CRITICAL_TOKENS)
                            else "standard"
                        ),
                        "source_output_position": {
                            "start": field.start_position,
                            "end": field.end_position,
                        },
                        "split": _split(index),
                        "reviewer_verification_status": "pending",
                    })
    return labels


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation_results/offline_labels/labels.jsonl"),
    )
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=Path("evaluation_results/offline_labels/splits.v1.json"),
    )
    args = parser.parse_args()
    labels = build_labels(args.dataset, SpecificationRegistry())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(label) + "\n" for label in labels),
        encoding="utf-8",
    )
    split_manifest = {
        "version": "1",
        "unit": "complete_document",
        "documents": {
            label["document_id_hash"]: label["split"] for label in labels
        },
    }
    args.split_manifest.write_text(json.dumps(split_manifest, indent=2), encoding="utf-8")
    print(
        f"Wrote {len(labels)} offline labels for "
        f"{len(split_manifest['documents'])} documents"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
