"""Truth-blind baseline run for the frozen engineering holdout.

Inference reads only document ids and image paths. Ground truth is opened
after all predictions have been persisted, preventing label leakage into
routing or extraction.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from evaluation.ingest_engineering_holdout import DEFAULT_DATASET, DEFAULT_OUTPUT
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.extraction_geometry import FormIdentityDecision, FormIdentityStatus
from packages.roi_resolution import ROIResolutionRequest, ROIResolver
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from workers.cascade.tesseract_adapter import TesseractTextExtractor, for_field_type
from workers.document_preparation.preprocessing import (
    apply_orientation,
    denoise,
    deskew,
    detect_orientation,
    detect_skew_angle,
)
from workers.page_detection.router import PageRoutingService
from workers.page_detection.text_extraction import RapidOCRTextExtractor
from workers.standard_form_extraction.consumer import _resolve_geometry
from workers.standard_form_extraction.extractor import StandardFormExtractionService
from workers.unstructured_extraction.anchor_cropper import extract_anchor_crops
from workers.unstructured_extraction.family_router import DocumentFamilyRouter


def _prepare(path: Path) -> Image.Image:
    image = Image.open(path).convert("L")
    image = apply_orientation(image, detect_orientation(image))
    image = deskew(image, detect_skew_angle(image))
    return denoise(image)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentile))]


def _normalized(value: object) -> str:
    return "".join(character.casefold() for character in str(value or "") if character.isalnum())


def _infer(dataset: Path, output: Path, *, limit: int | None = None) -> list[dict]:
    with (dataset / "index.csv").open(newline="", encoding="utf-8") as stream:
        # Deliberately retain only these two columns: family, quality and all
        # truth-bearing metadata are unavailable to inference.
        inputs = [
            {"document_id": row["document_id"], "path": row["path"]}
            for row in csv.DictReader(stream)
        ]
    if limit is not None:
        inputs = inputs[:limit]

    registry = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    cms = registry.get("cms1500", "02-12")
    ub = registry.get("ub04", "2014")
    page_ocr = TesseractTextExtractor(psm=11)
    router = PageRoutingService(
        cms, ub, page_ocr,
        registry.load_reference_image(cms), registry.load_reference_image(ub),
    )
    standard = StandardFormExtractionService(RapidOCRTextExtractor())
    family_router = DocumentFamilyRouter.from_yaml(Path("config/unstructured_document_families.yaml"))
    family_config = family_router._families  # same loaded, immutable runtime configuration

    predictions: list[dict] = []
    for position, item in enumerate(inputs, start=1):
        wall_started, cpu_started = time.perf_counter(), time.process_time()
        image = _prepare(dataset / item["path"])
        route = router.route_single_page(image)
        fields: dict[str, dict] = {}
        alignment_method = None
        if route.template is not None:
            template = route.template
            family = (
                DocumentClass.CMS1500 if template.template_id == "cms1500"
                else DocumentClass.UB04
            )
            ready, geometry = _resolve_geometry(
                image, template, registry.load_reference_image(template),
                FormIdentityDecision(
                    family=family, status=FormIdentityStatus.VERIFIED, score=1.0,
                    template_version=template.version,
                ),
            )
            alignment_method = (
                geometry.registration.algorithm if geometry.registration else geometry.mode.value
            )
            if ready is not None and geometry.authorizes_fixed_roi:
                resolver = ROIResolver()
                rois = {
                    region.field_name: resolver.resolve(ROIResolutionRequest(
                        field_name=region.field_name, page_width=ready.width,
                        page_height=ready.height, geometry=geometry,
                        fixed_region=(region.x0, region.y0, region.x1, region.y1),
                    ))
                    for region in template.field_regions
                }
                for field in standard.extract_fields_from_resolved_rois(
                    ready, template, 1, geometry, rois
                ):
                    fields[field.field_name] = {
                        "value": field.normalized_value or field.raw_value,
                        "raw_value": field.raw_value,
                        "confidence": field.confidence,
                        "method": field.extraction_method.value,
                    }
        else:
            # Reuse the page-routing OCR evidence. This changes cost only;
            # both live consumers use the same psm-11 Tesseract adapter.
            lines = page_ocr.extract(image)
            decision = family_router.route({1: lines})
            if decision.family and not decision.needs_review:
                specs = family_config[decision.family].get("fields", {})
                crops = extract_anchor_crops(image, lines, specs)
                for name, crop in crops.items():
                    spec = specs[name]
                    extractor = for_field_type(spec.get("field_type", "text"))
                    crop_lines = extractor.extract(crop.crop)
                    value = " ".join(line.text for line in sorted(crop_lines, key=lambda x: (x.y0, x.x0)))
                    fields[name] = {
                        "value": value, "raw_value": value,
                        "confidence": statistics.fmean(x.confidence for x in crop_lines) if crop_lines else 0.0,
                        "method": extractor.engine_name,
                    }
        predictions.append({
            "document_id": item["document_id"],
            "route": route.bundle_type.value,
            "route_reasons": route.reason_codes,
            "alignment_method": alignment_method,
            "fields": fields,
            "wall_seconds": time.perf_counter() - wall_started,
            "cpu_seconds": time.process_time() - cpu_started,
        })
        print(f"[{position}/{len(inputs)}] {item['document_id']} {route.bundle_type.value}", flush=True)

    output.mkdir(parents=True, exist_ok=True)
    prediction_path = output / ("predictions.json" if limit is None else f"predictions_pilot_{limit}.json")
    prediction_path.write_text(json.dumps(predictions, indent=2), "utf-8")
    return predictions


def _score(predictions: list[dict], output: Path, *, limit: int | None = None) -> dict:
    # Ground truth is intentionally loaded only after inference is complete.
    truth_payload = json.loads((output / "canonical_ground_truth.json").read_text("utf-8"))
    truth = {item["document_id"]: item for item in truth_payload["documents"]}
    correct = total = 0
    by_form: dict[str, Counter] = defaultdict(Counter)
    by_quality: dict[str, Counter] = defaultdict(Counter)
    route_counts = Counter()
    latencies, cpu_times = [], []
    misses = Counter()
    for prediction in predictions:
        expected = truth[prediction["document_id"]]
        route_counts[prediction["route"]] += 1
        latencies.append(prediction["wall_seconds"])
        cpu_times.append(prediction["cpu_seconds"])
        for field in expected["fields"]:
            total += 1
            name = field["field_name"]
            actual = prediction["fields"].get(name, {}).get("value", "")
            matched = _normalized(actual) == _normalized(field["expected_raw"])
            correct += int(matched)
            by_form[expected["form_type"]]["total"] += 1
            by_form[expected["form_type"]]["correct"] += int(matched)
            by_quality[expected["image_quality_bucket"]]["total"] += 1
            by_quality[expected["image_quality_bucket"]]["correct"] += int(matched)
            if not matched:
                misses[f"{expected['form_type']}.{name}"] += 1
    ratio = lambda counter: counter["correct"] / counter["total"] if counter["total"] else None
    report = {
        "dataset_status": "FROZEN_ENGINEERING_HOLDOUT",
        "production_promotion_authority": False,
        "truth_blind_inference": True,
        "documents": len(predictions),
        "field_observations": total,
        "raw_exact_accuracy": correct / total if total else None,
        "raw_exact_correct": correct,
        "accuracy_by_form": {key: ratio(value) for key, value in sorted(by_form.items())},
        "accuracy_by_quality": {key: ratio(value) for key, value in sorted(by_quality.items())},
        "route_counts": dict(route_counts),
        "top_error_fields": dict(misses.most_common()),
        "mean_wall_seconds": statistics.fmean(latencies) if latencies else None,
        "p95_wall_seconds": _percentile(latencies, .95),
        "mean_cpu_seconds": statistics.fmean(cpu_times) if cpu_times else None,
        "safe_accuracy": None,
        "field_hitl_rate": None,
        "claim_stp_rate": None,
        "claim_hitl_rate": None,
        "qualification_notes": [
            "This first report measures unchanged raw extraction only; canonical evidence decisions are not inferred from OCR confidence.",
            "Claim STP is unqualified because UB04 federal_tax_no truth is absent.",
            "This synthetic corpus cannot authorize production promotion.",
        ],
    }
    report_path = output / ("baseline_report.json" if limit is None else f"baseline_report_pilot_{limit}.json")
    report_path.write_text(json.dumps(report, indent=2), "utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    predictions = _infer(args.dataset, args.output, limit=args.limit)
    print(json.dumps(_score(predictions, args.output, limit=args.limit), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
