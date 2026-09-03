"""Phase 8.1 component benchmark for the PHI-free engineering golden pack."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from PIL import Image

from packages.document_taxonomy.taxonomy import DocumentClass
from packages.domain.enums import ValidationStatus
from packages.extraction_geometry import FormIdentityDecision, FormIdentityStatus
from packages.local_evidence_cascade import decide_local_candidate
from packages.page_observation import (
    PageObservation,
    PageObservationService,
    line_clustered_reading_order,
)
from packages.templates import TemplateRegistry
from workers.page_detection.text_extraction import (
    RapidOCRFullPageTextExtractor,
    RapidOCRTextExtractor,
)
from workers.standard_form_extraction import (
    StandardFormExtractionService,
    StandardFormProcessingService,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evaluation_data/phase8_1_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V1"
DEFAULT_OUTPUT = ROOT / "evaluation_results/phase8_1"
ARCHIVE_SHA256 = "27adda09b553900c047ebdadef70a57d2a450ad0baa5989d7fe4a65fb2518119"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _canonical(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().upper().split())


def _containment(predicted, truth) -> float:
    if not predicted:
        return 0.0
    x0, y0, x1, y1 = predicted
    tx0, ty0, tx1, ty1 = truth
    intersection = max(0, min(x1, tx1)-max(x0, tx0)) * max(0, min(y1, ty1)-max(y0, ty0))
    truth_area = max(1, (tx1-tx0)*(ty1-ty0))
    return intersection/truth_area


def _excess(predicted, truth) -> float:
    if not predicted:
        return 1.0
    area = max(1, (predicted[2]-predicted[0])*(predicted[3]-predicted[1]))
    truth_area = max(1, (truth[2]-truth[0])*(truth[3]-truth[1]))
    return max(0.0, (area-truth_area)/truth_area)


def _tokens_text(observation: PageObservation, bbox) -> tuple[str, float]:
    if not bbox:
        return "", 0.0
    x0, y0, x1, y1 = bbox
    tokens = [token for token in observation.ocr_tokens
              if x0 <= (token.bbox[0]+token.bbox[2])/2 <= x1
              and y0 <= (token.bbox[1]+token.bbox[3])/2 <= y1]
    tokens = line_clustered_reading_order(tokens)
    return (" ".join(token.text for token in tokens),
            statistics.fmean(token.confidence for token in tokens) if tokens else 0.0)


def _load_truth(dataset: Path):
    with (dataset/"field_truth.csv").open(newline="", encoding="utf-8") as handle:
        fields = list(csv.DictReader(handle))
    with (dataset/"ub04_service_line_truth.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return fields, rows


def _verify(dataset: Path, manifest: dict) -> None:
    with (dataset / "field_truth.csv").open(newline="", encoding="utf-8") as handle:
        truth_rows = sum(1 for _ in csv.DictReader(handle))
    if (
        manifest["document_count"] != len(manifest["documents"])
        or manifest["field_truth_rows"] != truth_rows
    ):
        raise ValueError("unexpected golden manifest cardinality")
    failures = [row["document_id"] for row in manifest["documents"]
                if _sha(dataset/row["file"]) != row["sha256"]]
    if failures:
        raise ValueError(f"golden image hash mismatch: {failures}")


def _observation(doc: dict, image: Image.Image, service: PageObservationService,
                 cache_dir: Path, reuse: bool) -> PageObservation:
    path = cache_dir/f"{doc['document_id']}.json"
    if reuse and path.is_file():
        return PageObservation.model_validate_json(path.read_text("utf-8"))
    result = service.observe(doc["document_id"], image, page_sha256=doc["sha256"])
    path.write_text(result.model_dump_json(), "utf-8")
    return result


def run(dataset: Path = DEFAULT_DATASET, output: Path = DEFAULT_OUTPUT, *,
        run_id: str = "baseline", reuse_observations: bool = False,
        observation_cache: Path | None = None) -> dict:
    manifest = json.loads((dataset/"manifest.json").read_text("utf-8"))
    _verify(dataset, manifest)
    fields, row_truth = _load_truth(dataset)
    fields_by_doc: dict[str, list[dict]] = defaultdict(list)
    rows_by_doc: dict[str, list[dict]] = defaultdict(list)
    for row in fields:
        fields_by_doc[row["document_id"]].append(row)
    for row in row_truth:
        rows_by_doc[row["document_id"]].append(row)

    output.mkdir(parents=True, exist_ok=True)
    cache_dir = observation_cache or output/"observations"
    cache_dir.mkdir(exist_ok=True)
    observation_service = PageObservationService(
        RapidOCRFullPageTextExtractor(), preprocessing_version="document-preparation-v1"
    )
    templates = TemplateRegistry.load_from_directory()
    extractor = StandardFormExtractionService(RapidOCRTextExtractor())
    processor = StandardFormProcessingService(observation_service, extractor)
    field_records = []
    service_records = []
    latencies = []
    stage_latencies: dict[str, list[float]] = defaultdict(list)
    full_page_calls = 0
    for number, doc in enumerate(manifest["documents"], 1):
        started = time.perf_counter()
        image = Image.open(dataset/doc["file"]).convert("RGB")
        family = "CMS1500" if doc["family"].startswith("CMS") else "UB04"
        observation_started = time.perf_counter()
        observation = _observation(doc, image, observation_service, cache_dir, reuse_observations)
        stage_latencies["full_page_observation"].append(
            (time.perf_counter() - observation_started) * 1000
        )
        full_page_calls += 0 if reuse_observations else observation.full_page_ocr_calls
        identity = FormIdentityDecision(
            family=DocumentClass.CMS1500 if family == "CMS1500" else DocumentClass.UB04,
            status=FormIdentityStatus.VERIFIED, score=1,
        )
        template = templates.get("cms1500", "02-12") if family == "CMS1500" else templates.get("ub04", "2014")
        processing = processor.process(
            image, template, 1, identity, page_id=doc["document_id"],
            page_sha256=doc["sha256"], observation=observation,
        )
        for stage, elapsed_ms in processing.diagnostics.stage_ms.items():
            stage_latencies[stage].append(float(elapsed_ms))
        structure = processing.ub_structure
        defs = processing.field_definitions
        rois = processing.roi_results
        locations = processing.field_locations
        extracted = processing.fields
        extracted_by_name = {item.field_name: item for item in extracted}
        for truth in fields_by_doc[doc["document_id"]]:
            name = truth["field_name"]
            definition = defs[name]
            bbox = rois[name].bbox
            truth_box = tuple(json.loads(truth["bbox_json"]))
            containment = _containment(bbox, truth_box)
            excess = _excess(bbox, truth_box)
            expected_in_region = containment >= .95
            localized = expected_in_region and excess <= 30
            raw, confidence = _tokens_text(observation, bbox)
            decision = decide_local_candidate(raw, definition.datatype)
            predicted = extracted_by_name.get(name)
            final = predicted.normalized_value if predicted else None
            final_decision = decide_local_candidate(
                predicted.raw_value if predicted else "", definition.datatype
            )
            truth_decision = decide_local_candidate(truth["expected_value"], definition.datatype)
            expected = truth_decision.normalized_value or truth["expected_value"]
            exact = _canonical(final) == _canonical(expected)
            ocr_exact = expected_in_region and _canonical(decision.normalized_value) == _canonical(expected)
            secondary_invoked = bool(
                predicted and "HIGH_RESOLUTION_REGIONAL_OCR" in predicted.validation_reasons
            )
            candidate_trace = extractor.last_candidate_trace.get(name, {})
            false_accept = bool(
                predicted and predicted.validation_status != ValidationStatus.INVALID
                and final_decision.accepted and not exact
            )
            if not bbox or not expected_in_region:
                layer = "FIELD_LOCALIZATION"
            elif not ocr_exact:
                layer = "OCR"
            elif not exact:
                layer = "NORMALIZATION_OR_PARSER"
            else:
                layer = "PASS"
            field_records.append({
                "document_id": doc["document_id"], "family": family, "variant": doc["variant"],
                "dataset_role": doc.get("dataset_role", "UNSPECIFIED"),
                "field_name": name, "critical": definition.blocking,
                "structural_confidence": rois[name].field_structural_confidence,
                "roi_mode": rois[name].mode.value, "predicted_bbox": bbox,
                "localization_evidence": locations[name].model_dump(mode="json"),
                "wrong_crop_suspected": locations[name].wrong_crop_suspected,
                "truth_bbox": truth_box, "truth_containment": containment,
                "crop_excess_ratio": excess, "localized": localized,
                "expected_value_in_region": expected_in_region, "raw_ocr": raw,
                "ocr_confidence": confidence, "ocr_exact_given_correct_region": ocr_exact,
                "expected": expected, "final": final, "exact": exact,
                "primary_accepted": decision.accepted,
                "secondary_selected": decision.secondary_engine,
                "secondary_invoked": secondary_invoked,
                "candidate_trace": candidate_trace,
                "ocr_candidates": [
                    item.model_dump(mode="json") for item in (predicted.candidates if predicted else [])
                ],
                "final_accepted": final_decision.accepted,
                "false_accept": false_accept,
                "failure_layer": layer,
            })
        if family == "UB04" and structure is not None:
            result = processing.ub_reconstruction
            predicted_rows = {line.line_number: line for line in result.lines}
            for truth in rows_by_doc[doc["document_id"]]:
                index = int(truth["row_index"])
                predicted = predicted_rows.get(index)
                values = {
                    "revenue_code": predicted.revenue_code if predicted else None,
                    "description": predicted.description if predicted else None,
                    "hcpcs": predicted.hcpcs if predicted else None,
                    "service_date": predicted.service_date.strftime("%m/%d/%Y") if predicted and predicted.service_date else None,
                    "units": str(predicted.units) if predicted and predicted.units is not None else None,
                    "charge": f"{predicted.charge:.2f}" if predicted and predicted.charge is not None else None,
                }
                cells = {name: _canonical(values[name]) == _canonical(truth[name])
                         for name in values}
                service_records.append({
                    "document_id": doc["document_id"], "variant": doc["variant"],
                    "row_index": index, "row_detected": predicted is not None,
                    "exact_row": bool(predicted) and all(cells.values()), "cells": cells,
                    "expected_values": {name: truth[name] for name in values},
                    "predicted_values": values,
                    "failure_layer": ("PASS" if predicted and all(cells.values()) else
                                      "TABLE_RECONSTRUCTION" if not predicted else "COLUMN_ASSIGNMENT"),
                })
        latencies.append((time.perf_counter()-started)*1000)
        print(
            f"{run_id}: {number}/{manifest['document_count']} {doc['document_id']}",
            flush=True,
        )

    by_family = {}
    for family in ("CMS1500", "UB04"):
        scoped = [row for row in field_records if row["family"] == family]
        by_family[family] = {
            "fields": len(scoped),
            "localization_accuracy": sum(row["localized"] for row in scoped)/max(1, len(scoped)),
            "expected_value_in_region": sum(
                row["expected_value_in_region"] for row in scoped
            ) / max(1, len(scoped)),
            "ocr_accuracy_given_correct_localization": (
                sum(row["ocr_exact_given_correct_region"] for row in scoped) /
                max(1, sum(row["expected_value_in_region"] for row in scoped))
            ),
            "final_field_accuracy": sum(row["exact"] for row in scoped) / max(1, len(scoped)),
        }
    critical = [row for row in field_records if row["critical"]]
    service_cells = [value for row in service_records for value in row["cells"].values()]
    report = {
        "dataset_id": manifest["dataset_id"],
        "archive_sha256": (
            ARCHIVE_SHA256
            if manifest["dataset_id"] == "CDP_GOLDEN_ENGINEERING_PACK_V1"
            else manifest.get("archive_sha256")
        ),
        "run_id": run_id, "phase8_path_changed_before_baseline": False if run_id == "baseline" else None,
        "documents": manifest["document_count"], "field_truth_rows": len(field_records),
        "by_family": by_family,
        "critical_field_accuracy": sum(row["exact"] for row in critical)/len(critical),
        "ub_service_lines": {
            "truth_rows": len(service_records),
            "row_detection_recall": sum(
                row["row_detected"] for row in service_records
            ) / max(1, len(service_records)),
            "exact_row_accuracy": sum(
                row["exact_row"] for row in service_records
            ) / max(1, len(service_records)),
            "column_cell_accuracy": sum(service_cells) / max(1, len(service_cells)),
            "failure_layers": dict(Counter(row["failure_layer"] for row in service_records)),
        },
        "latency_ms": {"p50": _percentile(latencies, .5), "p95": _percentile(latencies, .95),
                       "p99": _percentile(latencies, .99), "max": max(latencies)},
        "stage_latency_ms": {
            stage: {
                "samples": len(values),
                "p50": _percentile(values, .50),
                "p95": _percentile(values, .95),
                "max": max(values),
            }
            for stage, values in sorted(stage_latencies.items())
        },
        "full_page_ocr_calls_per_page": full_page_calls / manifest["document_count"],
        "secondary_ocr_selection_rate": sum(bool(row["secondary_selected"]) for row in field_records)/len(field_records),
        "secondary_ocr_invocation_rate": sum(row["secondary_invoked"] for row in field_records)/len(field_records),
        "false_accepts": sum(row["false_accept"] for row in field_records),
        "false_accept_rate": sum(row["false_accept"] for row in field_records) / len(field_records),
        "cloud_calls": 0, "common_path_cloud_cost_usd": 0,
        "failure_layers": dict(Counter(row["failure_layer"] for row in field_records)),
        "gate": {
            "cms_priority_ge_90": by_family["CMS1500"]["final_field_accuracy"] >= .90,
            "ub_priority_ge_85": by_family["UB04"]["final_field_accuracy"] >= .85,
            "critical_ge_90": sum(row["exact"] for row in critical)/len(critical) >= .90,
            "false_accepts_zero": not any(row["false_accept"] for row in field_records),
            "false_accept_rate_le_1pct": (
                sum(row["false_accept"] for row in field_records) / len(field_records) <= .01
            ),
        },
    }
    run_dir = output/run_id
    run_dir.mkdir(exist_ok=True)
    (run_dir/"metrics.json").write_text(json.dumps(report, indent=2)+"\n", "utf-8")
    (run_dir/"field_records.jsonl").write_text("".join(json.dumps(row, default=str)+"\n" for row in field_records), "utf-8")
    (run_dir/"service_line_records.jsonl").write_text("".join(json.dumps(row, default=str)+"\n" for row in service_records), "utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run-id", default="baseline")
    parser.add_argument("--reuse-observations", action="store_true")
    parser.add_argument("--observation-cache", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.dataset, args.output, run_id=args.run_id,
                         reuse_observations=args.reuse_observations,
                         observation_cache=args.observation_cache), indent=2))


if __name__ == "__main__":
    main()
