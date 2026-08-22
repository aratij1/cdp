"""Build atomic, template-derived field crops and calibration contact sheets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageOps

from packages.domain.enums import ClaimFormType
from packages.templates.readiness import require_reference_templates
from packages.templates.registry import TemplateRegistry
from workers.cascade.handwriting_detection import OpenCVHandwritingDetector
from workers.page_detection.local_crop_alignment import align_field_crop
from workers.page_detection.template_alignment import align_to_reference


def _contact_sheet(items: list[tuple[str, Image.Image]], target: Path) -> None:
    if not items:
        return
    tile_width, tile_height = 420, 110
    sheet = Image.new("RGB", (tile_width * 3, tile_height * ((len(items) + 2) // 3)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (document_id, crop) in enumerate(items):
        x = index % 3 * tile_width
        y = index // 3 * tile_height
        preview = ImageOps.contain(crop.convert("RGB"), (tile_width - 12, tile_height - 26))
        sheet.paste(preview, (x + 6, y + 20))
        draw.text((x + 6, y + 3), document_id, fill="black")
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, "PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset_raw"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("evaluation_data/document_manifest.json")
    )
    parser.add_argument("--templates", type=Path, default=Path("config/templates"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/field_crops"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    registry = TemplateRegistry.load_from_directory(args.templates)
    required_form_types = {
        ClaimFormType(metadata["form_type"])
        for metadata in manifest.values()
        if metadata["form_type"] != "UNSTRUCTURED"
    }
    require_reference_templates(registry, required_form_types)
    contract = yaml.safe_load(
        Path("config/evaluation/field_contract.yaml").read_text(encoding="utf-8")
    )
    contact_items: dict[tuple[str, str], list[tuple[str, Image.Image]]] = {}
    crop_manifest: dict[str, dict] = {}
    detector = OpenCVHandwritingDetector()

    for document_id, metadata in sorted(manifest.items()):
        form_type = metadata["form_type"]
        if form_type == "UNSTRUCTURED":
            continue
        enum_type = ClaimFormType(form_type)
        template = registry.latest_for_form_type(enum_type)
        reference = registry.load_reference_image(template)
        if reference is None:
            raise FileNotFoundError(f"Missing reference image for {template.template_id}")
        with Image.open(args.dataset / str(metadata["file_name"])) as source:
            source.seek(int(metadata["page_number"]) - 1)
            alignment = align_to_reference(source.convert("L"), reference)
        if alignment.warped is None:
            raise RuntimeError(f"Alignment failed for {document_id}")
        document_dir = args.output / document_id
        document_dir.mkdir(parents=True, exist_ok=True)
        contract_fields = contract["forms"][form_type]["fields"]
        for field_name in contract_fields:
            region = template.field_region(field_name)
            if region is None:
                continue
            local = align_field_crop(alignment.warped, reference, region)
            crop = local.crop
            crop.save(document_dir / f"{field_name}.png", "PNG", optimize=True)
            detection = detector.classify(crop)
            crop_manifest[f"{document_id}/{field_name}"] = {
                "alignment_score": alignment.alignment_score,
                "reprojection_error": alignment.reprojection_error,
                "local_offset": [local.offset_x, local.offset_y],
                "local_match_score": local.match_score,
                "local_alignment_accepted": local.accepted,
                "crop_box": list(local.box),
                "writing_type": detection.writing_type.value,
                "writing_confidence": detection.confidence,
            }
            contact_items.setdefault((form_type, field_name), []).append((document_id, crop))

    for (form_type, field_name), items in contact_items.items():
        _contact_sheet(
            items,
            args.output / "_contact_sheets" / form_type / f"{field_name}.png",
        )
    (args.output / "crop_manifest.json").write_text(
        json.dumps(crop_manifest, indent=2), encoding="utf-8"
    )
    print(f"Wrote atomic crops and {len(contact_items)} contact sheets to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
