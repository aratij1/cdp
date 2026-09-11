"""Build document_manifest.json and ground_truth.json for the `claims/` dataset.

Reads the offline labels produced by ``scripts/build_labels_from_fixed_width.py``
(``evaluation_results/offline_labels/labels.jsonl`` and ``splits.v1.json``) and the
real image files under ``claims/`` (Groups A/B/C/D) and emits, using the
pipeline's own schemas:

- ``evaluation_data/document_manifest.json``: ``{document_id: {file_name,
  form_type, page_number}}`` -- the exact shape consumed by
  ``evaluation.build_field_crops``, ``evaluation.run_atomic_ocr`` and
  ``evaluation.run_unstructured_family_cascade`` (see
  ``evaluation/build_dataset_labels.py`` for the precedent this mirrors).
- ``evaluation_data/ground_truth.json``: a ``GroundTruthDataset`` (see
  ``evaluation/schemas.py``), field names translated from the fixed-width
  canonical names into the atomic field-crop vocabulary used by
  ``config/evaluation/field_contract.yaml`` and the CMS1500/UB04 templates.

This script does not read or write anything under ``dataset_raw/`` and never
duplicates the labelling logic in ``scripts/build_labels_from_fixed_width.py``
(document identity/order/hash there is reused byte-for-byte: sorted image
iteration per group, sha256 of ``f"{group}/{image_name}"``).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from evaluation.schemas import GroundTruthDataset, GroundTruthDocument, GroundTruthField

# Fixed-width (NSF / UB92) canonical_field_name -> atomic field-crop name used
# by config/evaluation/field_contract.yaml and the CMS1500/UB04 templates.
# Only fields the pipeline actually extracts atomically are mapped; every
# other labelled fixed-width field has no atomic-crop counterpart and is
# intentionally left out of ground truth (the pipeline was never asked to
# extract it).
CMS1500_FIELD_MAP = {
    "patient_last_name": "patient_last",
    "patient_first_name": "patient_first",
    "patient_address_1": "patient_addr1",
    "patient_address_2": "patient_addr2",
    "patient_city": "patient_city",
    "patient_state": "patient_state",
    "patient_zip_code": "patient_zip",
    "patient_relationship_to_insured": "rel_code",
    "insured_address_line_1": "insured_addr1",
    "insured_address_line_2": "insured_addr2",
    "insured_city": "insured_city",
    "insured_state": "insured_state",
    "insured_zip": "insured_zip",
    "patient_date_of_birth": "patient_dob",
    "insured_identification_number": "insured_id_number",
    "total_claim_charges": "total_charge",
    "provider_tax_id": "federal_tax_id",
    "diagnosis_code_1": "diagnosis_codes",
}

UB04_FIELD_MAP = {
    "federal_tax_number_or_ein": "federal_tax_id",
    "federal_tax_number_ein": "federal_tax_id",
    "medicare_provider_number": "provider_npi",
    "patient_control_number": "patient_control_number",
    "patient_last_name": "patient_last",
    "patient_first_name": "patient_first",
    "patient_sex": "patient_sex",
    "patient_birthdate": "patient_dob",
    "type_of_bill": "type_of_bill",
    "principal_diagnosis_code": "principal_diagnosis",
}

# Same critical-field notion used by scripts/build_labels_from_fixed_width.py,
# reused rather than reinvented; applied to the *translated* (atomic) field
# name plus the same substring-match semantics.
CRITICAL_TOKENS = {
    "patient_name", "patient_first", "patient_last", "date_of_birth",
    "member_id", "provider_npi", "tax_id", "diagnosis",
}

GROUP_FORM_TYPE = {
    "A": "CMS1500",
    "B": "CMS1500",
    "C": "UB04",
    "D": "UNSTRUCTURED",
}


def _windows_copy_number(path: Path) -> int:
    """Order "Name.ext", "Name (2).ext", ... by copy number, matching the
    same fix in scripts/build_labels_from_fixed_width.py -- plain lexical
    sort puts "(10)/(11)/(12)" before "(2)" and the bare file last, breaking
    the 1:1 pairing with labels.jsonl's claim-record order."""
    match = re.search(r"\((\d+)\)", path.stem)
    return 1 if match is None else int(match.group(1))


def _images(dataset: Path, group: str) -> list[Path]:
    directory = dataset / f"Group {group}"
    return sorted(
        (path for path in directory.iterdir()
         if path.suffix.lower() not in {".txt", ".json", ".csv"}),
        key=_windows_copy_number,
    )


def _is_critical(field_name: str, criticality_value: str) -> bool:
    # The source label's ``criticality`` was computed against the raw
    # fixed-width canonical field name (e.g. "federal_tax_number_or_ein",
    # "medicare_provider_number"), which rarely shares a CRITICAL_TOKENS
    # substring with the *translated* atomic field name used here (e.g.
    # "federal_tax_id", "provider_npi") -- so an explicit "critical" from the
    # source is honored, but "standard" is not treated as a strong negative;
    # CRITICAL_TOKENS is re-evaluated against the translated name either way.
    if criticality_value == "critical":
        return True
    return any(token in field_name for token in CRITICAL_TOKENS)


def build(dataset: Path, labels_path: Path, splits_path: Path) -> tuple[dict, GroundTruthDataset]:
    labels = [json.loads(line) for line in labels_path.read_text(encoding="utf-8").splitlines() if line]
    splits = json.loads(splits_path.read_text(encoding="utf-8"))["documents"]

    manifest: dict[str, dict[str, object]] = {}

    # document_id_hash values in labels.jsonl were computed from the
    # dataset_raw/ image names (see scripts/build_labels_from_fixed_width.py
    # ``_document_hash``); sorted per-group iteration order is stable and 1:1
    # with claim record order, so the Nth sorted image in claims/Group X
    # corresponds to the Nth sorted image in dataset_raw/Group X and
    # therefore to the same document_id_hash. Document order per group is
    # taken directly from labels.jsonl's own row order below.
    # is not orderable on its own (dict has no guaranteed group ordering equal
    # to image order), so instead derive per-group document order directly
    # from labels.jsonl's own row order (build_labels_from_fixed_width.py
    # emits labels for claim 1..N in the same sorted-image order used here).
    group_doc_order: dict[str, list[str]] = {}
    for row in labels:
        group = row["group"]
        doc_id = row["document_id_hash"]
        order = group_doc_order.setdefault(group, [])
        if doc_id not in order:
            order.append(doc_id)

    for group in ("A", "B", "C", "D"):
        images = _images(dataset, group)
        doc_ids = group_doc_order.get(group, [])
        if len(doc_ids) != len(images):
            raise ValueError(
                f"Group {group}: {len(doc_ids)} labelled documents vs "
                f"{len(images)} image files in {dataset / f'Group {group}'}"
            )
        for image, document_id in zip(images, doc_ids, strict=True):
            manifest[document_id] = {
                "file_name": f"Group {group}/{image.name}",
                "form_type": GROUP_FORM_TYPE[group],
                "page_number": 1,
            }

    # Group rows by document, translate field names, build GroundTruthDocument.
    by_document: dict[str, list[dict]] = {}
    for row in labels:
        by_document.setdefault(row["document_id_hash"], []).append(row)

    documents: list[GroundTruthDocument] = []
    for document_id, rows in by_document.items():
        metadata = manifest[document_id]
        form_type = metadata["form_type"]
        field_map = (
            UB04_FIELD_MAP if form_type == "UB04"
            else CMS1500_FIELD_MAP if form_type in {"CMS1500", "UNSTRUCTURED"}
            else {}
        )
        fields: dict[str, GroundTruthField] = {}
        for row in rows:
            atomic_name = field_map.get(row["canonical_field_name"])
            if atomic_name is None:
                continue
            if atomic_name in fields:
                # Multiple fixed-width rows can map to the same atomic field
                # (e.g. duplicated payer segments); keep the first non-blank.
                if fields[atomic_name].expected_raw:
                    continue
            critical = _is_critical(atomic_name, row["criticality"])
            fields[atomic_name] = GroundTruthField(
                field_name=atomic_name,
                expected_raw=row["expected_raw_value"].strip(),
                expected_normalized=row["expected_normalized_value"],
                required=critical,
                critical=critical,
            )
        split = splits.get(document_id, "holdout")
        documents.append(
            GroundTruthDocument(
                document_id=document_id,
                file_name=metadata["file_name"],
                form_type=form_type,
                split=split,
                fields=list(fields.values()),
            )
        )

    documents.sort(key=lambda item: item.document_id)
    return manifest, GroundTruthDataset(documents=documents)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("claims"))
    parser.add_argument(
        "--labels", type=Path, default=Path("evaluation_results/offline_labels/labels.jsonl")
    )
    parser.add_argument(
        "--splits", type=Path, default=Path("evaluation_results/offline_labels/splits.v1.json")
    )
    parser.add_argument(
        "--manifest-output", type=Path, default=Path("evaluation_data/document_manifest.json")
    )
    parser.add_argument(
        "--ground-truth-output", type=Path, default=Path("evaluation_data/ground_truth.json")
    )
    parser.add_argument(
        "--exclude-groups", nargs="*", default=[],
        help="Group letters (A/B/C/D) to omit, e.g. when a form type's "
        "canonical reference template is not available for real geometric "
        "alignment (see packages/templates/readiness.py).",
    )
    args = parser.parse_args()

    manifest, ground_truth = build(args.dataset, args.labels, args.splits)
    if args.exclude_groups:
        excluded = {group.upper() for group in args.exclude_groups}
        excluded_ids = {
            doc_id for doc_id, meta in manifest.items()
            if meta["file_name"].split("/", 1)[0].split(" ")[-1] in excluded
        }
        manifest = {k: v for k, v in manifest.items() if k not in excluded_ids}
        ground_truth = ground_truth.model_copy(
            update={
                "documents": [
                    document for document in ground_truth.documents
                    if document.document_id not in excluded_ids
                ]
            }
        )

    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    args.ground_truth_output.parent.mkdir(parents=True, exist_ok=True)
    args.ground_truth_output.write_text(ground_truth.model_dump_json(indent=2), encoding="utf-8")

    print(
        f"Wrote {len(manifest)} manifest entries to {args.manifest_output} and "
        f"{len(ground_truth.documents)} ground-truth documents "
        f"({sum(len(d.fields) for d in ground_truth.documents)} fields) "
        f"to {args.ground_truth_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
