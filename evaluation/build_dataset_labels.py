"""Build field-level evaluation labels from the supplied keyed claim outputs.

The reference NSF/UB92 files are used only to create evaluation truth.  OCR
inference must never read these files; keeping this conversion as a separate
command makes that boundary explicit and prevents accidental answer leakage.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evaluation.schemas import GroundTruthDataset, GroundTruthDocument, GroundTruthField

CRITICAL_FIELDS = {
    "patient_last",
    "patient_first",
    "patient_dob",
    "federal_tax_id",
    "provider_npi",
    "principal_diagnosis",
    "type_of_bill",
}


def _split(document_number: int) -> str:
    """Stable 60/20/20 split, distributed across every group."""
    remainder = document_number % 5
    return "holdout" if remainder == 0 else "validation" if remainder == 4 else "calibration"


def _field(name: str, value: Any) -> GroundTruthField:
    text = "" if value is None else str(value).strip()
    return GroundTruthField(
        field_name=name,
        expected_raw=text,
        required=name in CRITICAL_FIELDS,
        critical=name in CRITICAL_FIELDS,
    )


def _cms_documents(dataset_root: Path) -> list[GroundTruthDocument]:
    corrected_path = dataset_root / ".crops" / "all_claims_corrected.json"
    corrected = json.loads(corrected_path.read_text(encoding="utf-8"))
    documents: list[GroundTruthDocument] = []
    excluded = {"claim", "group", "file", "page", "rel_label"}
    for row in corrected:
        number = int(row["claim"].split("-")[1])
        fields = [_field(key, value) for key, value in row.items() if key not in excluded]
        documents.append(
            GroundTruthDocument(
                document_id=row["claim"],
                file_name=f"Group {row['group']}/{row['file']}",
                form_type="CMS1500" if row["group"] in {"A", "B"} else "UNSTRUCTURED",
                split=_split(number),
                fields=fields,
            )
        )
    return documents


def _slice(line: str, start: int, end: int) -> str:
    """Read inclusive, one-based fixed-width positions."""
    return line[start - 1 : end].strip()


def _ub04_documents(dataset_root: Path) -> list[GroundTruthDocument]:
    group = dataset_root / "Group C"
    reference = group / "DATAMATICS_UBH_UB_07202026 - Group C.txt"
    lines = reference.read_bytes().decode("ascii").splitlines()
    images = sorted(path.name for path in group.iterdir() if path.suffix.lower() != ".txt")

    claim_records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in lines:
        record_type = line[:2]
        if record_type == "10":
            current = {
                "federal_tax_id": _slice(line, 8, 17).lstrip("0"),
                "provider_npi": _slice(line, 22, 34).lstrip("0"),
            }
        elif record_type == "20":
            if current is None:
                raise ValueError("UB92 patient record appeared before provider record")
            current.update(
                {
                    "patient_control_number": _slice(line, 5, 24),
                    "patient_last": _slice(line, 25, 44),
                    "patient_first": _slice(line, 45, 53),
                    "patient_sex": _slice(line, 55, 55),
                    "patient_dob": _slice(line, 56, 63),
                }
            )
        elif record_type == "40" and current is not None:
            current["type_of_bill"] = _slice(line, 25, 27)
        elif record_type == "70" and current is not None:
            current["principal_diagnosis"] = _slice(line, 25, 31)
        elif record_type == "90" and current is not None:
            claim_records.append(current)
            current = None

    if len(claim_records) != len(images):
        raise ValueError(
            f"Group C mapping is ambiguous: {len(claim_records)} keyed claims, {len(images)} images"
        )

    documents = []
    for index, (image, values) in enumerate(zip(images, claim_records, strict=True), start=1):
        documents.append(
            GroundTruthDocument(
                document_id=f"C-{index:02d}",
                file_name=f"Group C/{image}",
                form_type="UB04",
                split=_split(index),
                fields=[_field(name, value) for name, value in values.items()],
            )
        )
    return documents


def build_labels(dataset_root: Path) -> GroundTruthDataset:
    corrected_path = dataset_root / ".crops" / "all_claims_corrected.json"
    if not corrected_path.exists():
        from scripts.build_ground_truth import build_consolidated_gt

        _, pydantic_gt, _ = build_consolidated_gt(dataset_dir=dataset_root)
        return pydantic_gt
    documents = _cms_documents(dataset_root) + _ub04_documents(dataset_root)
    return GroundTruthDataset(documents=sorted(documents, key=lambda item: item.document_id))


def _manifest(labels: GroundTruthDataset, dataset_root: Path) -> dict[str, dict[str, object]]:
    from scripts.build_ground_truth import _deterministic_split, scan_raw_dataset

    raw_inventory = scan_raw_dataset(dataset_root)
    if not raw_inventory:
        return {
            document.document_id: {
                "file_name": document.file_name,
                "form_type": document.form_type,
                "page_number": 1,
            }
            for document in labels.documents
        }

    labelled_ids = {d.document_id for d in labels.documents}
    manifest: dict[str, dict[str, object]] = {}
    for cid, info in sorted(raw_inventory.items()):
        manifest[cid] = {
            "claim_id": cid,
            "file_name": info["file_name"],
            "group": info["group"],
            "form_type": info["form_type"],
            "file_size": info["file_size"],
            "split": _deterministic_split(cid),
            "status": "LABELLED" if cid in labelled_ids else "PENDING",
        }
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build evaluation truth from keyed outputs")
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_data/ground_truth.json"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("evaluation_data/document_manifest.json")
    )
    args = parser.parse_args()
    labels = build_labels(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(labels.model_dump_json(indent=2), encoding="utf-8")
    args.manifest.write_text(
        json.dumps(_manifest(labels, args.dataset), indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(labels.documents)} labelled documents to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
