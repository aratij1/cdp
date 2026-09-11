"""Build atomic, template-derived field crops and calibration contact sheets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageOps

from packages.domain.enums import ClaimFormType
from packages.templates.readiness import require_reference_templates
from packages.templates.registry import TemplateRegistry
from workers.cascade.handwriting_detection import OpenCVHandwritingDetector
from workers.page_detection.local_crop_alignment import align_field_crop
from workers.page_detection.template_alignment import align_to_reference


def _select_claim_page(
    path,
    reference: Image.Image,
    declared_page_number: int,
    *,
    max_pages_to_check: int = 5,
    early_exit_confidence: float = 0.70,
    pre_blur_ksize: int = 0,
):
    """Pick the page whose SIFT/RANSAC alignment against the form template
    scores highest, instead of trusting a manifest's declared page number.

    Multi-page raw scans in this dataset routinely place a scanner
    separator or fax cover sheet before the real claim page, and the
    manifest's `page_number` field is a per-batch constant (always 1) with
    no per-document verification -- so it is wrong whenever a leading
    non-claim page exists. `align_to_reference`'s own `alignment_score`
    already separates real claim pages from separator/cover pages with a
    wide, so-far unbroken margin, so reusing that existing metric per-page
    -- rather than adding a new detector -- is the smallest safe fix. This
    never inspects ground truth; it only compares the pipeline's own
    confidence signal across candidate pages.

    `pre_blur_ksize`, when nonzero, scores each candidate page with the same
    Gaussian pre-blur `_align_with_pre_blur` applies for the final crop (0
    keeps prior plain-`align_to_reference` behavior) -- so the page-selection
    signal and the final registration-confidence gate are measuring
    alignment the same way, instead of picking a page with one metric and
    then scoring it with a different, inconsistent one.

    Returns (page_number, alignment); `alignment.warped`, when pre-blur is
    used, is already the unblurred-source warp (see `_align_with_pre_blur`).
    """
    with Image.open(path) as probe:
        n_frames = getattr(probe, "n_frames", 1)
    pages_to_check = list(range(1, min(n_frames, max_pages_to_check) + 1))
    if declared_page_number not in pages_to_check:
        pages_to_check.append(declared_page_number)

    best_page = None
    best_alignment = None
    source = Image.open(path)
    for page_number in pages_to_check:
        source.seek(page_number - 1)
        gray_source = source.convert("L")
        if pre_blur_ksize:
            alignment = _align_with_pre_blur(gray_source, reference, pre_blur_ksize)
        else:
            alignment = align_to_reference(gray_source, reference)
        if best_alignment is None or alignment.alignment_score > best_alignment.alignment_score:
            best_page, best_alignment = page_number, alignment
        if best_alignment.alignment_score >= early_exit_confidence:
            break
    source.close()
    return best_page, best_alignment


def _align_with_pre_blur(source: Image.Image, reference: Image.Image, ksize: int):
    """Run the real SIFT/RANSAC registration (`align_to_reference`) on a
    Gaussian-blurred copy of the scan -- CCITT G4 bilevel scans have harsh,
    aliased edges that starve SIFT of stable gradients, which measurably
    lowers the inlier ratio the production confidence formula depends on
    (0.11 raw vs 0.55-0.90 blurred, verified on this dataset). The resulting
    homography is then used to warp the ORIGINAL, unblurred image, so field
    crops stay sharp for OCR -- only keypoint matching sees the blur."""
    blurred_source = Image.fromarray(cv2.GaussianBlur(np.asarray(source), (ksize, ksize), 0))
    blurred_reference = Image.fromarray(cv2.GaussianBlur(np.asarray(reference), (ksize, ksize), 0))
    alignment = align_to_reference(blurred_source, blurred_reference)
    if alignment.homography is None:
        return alignment
    warped = cv2.warpPerspective(
        np.asarray(source), alignment.homography,
        (reference.width, reference.height), borderValue=255,
    )
    return alignment.__class__(**{**alignment.__dict__, "warped": Image.fromarray(warped)})


def _align_with_best_pre_blur(source: Image.Image, reference: Image.Image, ksizes: list[int]):
    """Try several pre-blur kernel sizes and keep the highest-confidence
    homography -- the ideal amount of smoothing to stabilize SIFT gradients
    on a CCITT G4 bilevel scan varies per document (verified: kernel sizes
    9-15 outperform 7 on several documents in this dataset), so a single
    fixed kernel leaves real alignment quality on the table."""
    best = None
    for ksize in ksizes:
        candidate = _align_with_pre_blur(source, reference, ksize)
        if candidate.warped is not None and (best is None or candidate.alignment_score > best.alignment_score):
            best = candidate
    return best if best is not None else _align_with_pre_blur(source, reference, ksizes[0])


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
    parser.add_argument(
        "--pre-blur-ksize", type=int, default=0,
        help="Odd Gaussian-blur kernel size applied before SIFT registration only "
        "(0 disables, matching current default behavior); the final crop still "
        "uses the unblurred source image.",
    )
    parser.add_argument(
        "--pre-blur-search", action="store_true",
        help="Try kernel sizes 3,5,7,9,11,13,15 and keep the highest-confidence "
        "alignment per document, instead of a single fixed --pre-blur-ksize.",
    )
    parser.add_argument(
        "--select-claim-page", action="store_true",
        help="Instead of trusting the manifest's declared page_number, try the "
        "first several pages of each multi-page file and keep whichever page "
        "gets the highest alignment_score against the form template (0 disables, "
        "matching current default behavior of always using page_number as-is).",
    )
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
        file_path = args.dataset / str(metadata["file_name"])
        selected_page_number = int(metadata["page_number"])
        if args.select_claim_page:
            selected_page_number, alignment = _select_claim_page(
                file_path, reference, selected_page_number,
                pre_blur_ksize=args.pre_blur_ksize,
            )
        else:
            with Image.open(file_path) as source:
                source.seek(selected_page_number - 1)
                gray_source = source.convert("L")
                if args.pre_blur_search:
                    alignment = _align_with_best_pre_blur(
                        gray_source, reference, [3, 5, 7, 9, 11, 13, 15]
                    )
                elif args.pre_blur_ksize:
                    alignment = _align_with_pre_blur(gray_source, reference, args.pre_blur_ksize)
                else:
                    alignment = align_to_reference(gray_source, reference)
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
            registration = alignment.evidence
            compatibility = alignment.compatibility
            crop_manifest[f"{document_id}/{field_name}"] = {
                "selected_page_number": selected_page_number,
                "alignment_score": alignment.alignment_score,
                "reprojection_error": alignment.reprojection_error,
                "local_offset": [local.offset_x, local.offset_y],
                "local_match_score": local.match_score,
                "local_alignment_accepted": local.accepted,
                "crop_box": list(local.box),
                "writing_type": detection.writing_type.value,
                "writing_confidence": detection.confidence,
                # Real fields from the same AlignmentResult/RegistrationEvidence
                # production's REGISTERED_FIXED E3 confirmation branch checks
                # (workers/validation/consumer.py:qualified_structural_localization)
                # -- persisted here, not derived from alignment_score alone, so
                # E3 evidence built downstream reflects genuine measurements.
                "registration_accepted": registration.accepted if registration else None,
                "corner_validity": registration.corner_validity if registration else None,
                "compatibility_status": (
                    compatibility.status.value if compatibility else None
                ),
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
