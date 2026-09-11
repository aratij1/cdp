"""Extract CMS1500 service-line charges via the real
`StandardFormExtractionService.extract_service_lines`, so
`packages.deterministic_evidence`'s existing total_charge-vs-service-lines
cross-field check (`_cross_field`, "CLAIM_TOTAL_CONFIRMED") has real data to
compare against -- today it silently never fires in the `claims/` eval
harness because no service-line OCR pass exists there.

Re-runs the same alignment as `evaluation/build_field_crops.py` (same
pre-blur search) since the warped, aligned full page is not persisted by
that script; only the service-line region is OCRed here, with PaddleOCR
(no cascade), keeping this additive and independent of the atomic field
OCR pipeline.

Writes `{document_id: "12345.67"}` (decimal string sum of charge_amount
across all detected service-line rows) so it can be merged into
evaluation/claims_decision_replay.py's per-document claim_values under the
key `service_line_charges` (a single already-summed value, matching how
`_cross_field` parses it: `Decimal(item)` per comma-split token -- one
token here since it is pre-summed).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from evaluation.build_field_crops import _align_with_best_pre_blur
from packages.domain.enums import ClaimFormType
from packages.templates.registry import TemplateRegistry
from workers.page_detection.text_extraction import PaddleOCRTextExtractor
from workers.standard_form_extraction.extractor import StandardFormExtractionService

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("claims"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("evaluation_data/document_manifest.json")
    )
    parser.add_argument("--templates", type=Path, default=Path("config/templates"))
    parser.add_argument(
        "--output", type=Path, default=Path("evaluation_data/service_line_totals.json")
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    registry = TemplateRegistry.load_from_directory(args.templates)
    extractor = StandardFormExtractionService(PaddleOCRTextExtractor())

    totals: dict[str, str] = {}
    for document_id, metadata in sorted(manifest.items()):
        form_type = metadata["form_type"]
        if form_type != "CMS1500":
            continue
        template = registry.latest_for_form_type(ClaimFormType(form_type))
        if template.service_line_region is None:
            continue
        reference = registry.load_reference_image(template)
        if reference is None:
            continue
        with Image.open(args.dataset / str(metadata["file_name"])) as source:
            source.seek(int(metadata["page_number"]) - 1)
            gray_source = source.convert("L")
            alignment = _align_with_best_pre_blur(
                gray_source, reference, [3, 5, 7, 9, 11, 13, 15]
            )
        if alignment is None or alignment.warped is None:
            continue
        lines = extractor.extract_service_lines(
            alignment.warped, template, int(metadata["page_number"])
        )
        charge_lines = [line.charge_amount for line in lines if line.charge_amount is not None]
        if charge_lines:
            totals[document_id] = str(sum(charge_lines))
        print(
            f"{document_id}: {len(lines)} service lines, "
            f"{len(charge_lines)} with a charge amount, "
            f"total={totals.get(document_id)}"
        )

    args.output.write_text(json.dumps(totals, indent=2), encoding="utf-8")
    print(f"Wrote {len(totals)} document service-line totals to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
