from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from PIL import Image

from packages.claim_decision import ClaimDecisionContext, ClaimDecisionService
from packages.criticality import CriticalityPolicy, DEFAULT_CRITICALITY_PATH
from packages.domain.enums import ClaimFormType
from packages.evidence_decision import DecisionContext, EvidenceDecisionService
from packages.field_verification import verify_field
from packages.ocr.contracts import OCRCandidate
from packages.templates.registry import TemplateRegistry
from workers.page_detection.text_extraction import RapidOCRTextExtractor
from workers.standard_form_extraction.consumer import _align_or_rescale
from workers.standard_form_extraction.extractor import StandardFormExtractionService

from .build_manifest import RESULT_ROOT, ROOT, build_manifest
from .metrics import percentile, ratio
from .routing_benchmark import PHASE_ROOT


ACTUAL_TO_TRUTH = {
    "patient_dob": "dob", "insured_id_number": "member_id",
    "federal_tax_id": "federal_tax_no", "patient_account_no": "account_no",
    "patient_control_number": "account_no", "patient_sex": "sex",
    "diagnosis_codes": "diagnosis", "insured_unique_id": "member_id",
    "provider_name_address": "provider_name", "billing_provider_info": "provider_name",
    "rel_code": "relationship",
}
CRITICAL_FIELDS = {"patient_name", "insured_id_number", "member_id", "provider_npi",
                   "total_charge", "principal_diagnosis", "diagnosis", "type_of_bill"}


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9.]", "", str(value or "").upper())


def _iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    x0, y0, x1, y1 = left
    a0, b0, a1, b1 = right
    intersection = max(0, min(x1, a1) - max(x0, a0)) * max(0, min(y1, b1) - max(y0, b0))
    union = max(0, x1 - x0) * max(0, y1 - y0) + max(0, a1 - a0) * max(0, b1 - b0) - intersection
    return ratio(intersection, union)


def _select(records, family: str, public_count: int = 12, representative_count: int = 3):
    public = [row for row in records if row.expected_family == family and
              row.source_dataset.startswith("SYNTHETIC_PUBLIC")]
    representative = [row for row in records if row.expected_family == family and
                      row.source_dataset == "PRODUCTION_HOLDOUT_V2_REPRESENTATIVE"]
    # Stable interleaving avoids selecting only one quality bucket.
    public.sort(key=lambda row: (row.quality_bucket, row.document_id))
    representative.sort(key=lambda row: (row.quality_bucket, row.document_id))
    return public[:public_count] + representative[:representative_count]


def _truth_name(field_name: str, truth: dict[str, Any]) -> str | None:
    if field_name in truth:
        return field_name
    alias = ACTUAL_TO_TRUTH.get(field_name)
    return alias if alias in truth else None


def _field_candidate(field, canonical: str, registration_confidence: float | None):
    verification = verify_field(canonical, field.normalized_value or field.raw_value)
    candidate = OCRCandidate(
        value=field.normalized_value or field.raw_value, raw_value=field.raw_value or "",
        engine="rapidocr", model_name="RapidOCR-ONNX", model_version="rapidocr-onnxruntime",
        preprocessing_variant="truth_route_rescale_only", raw_confidence=field.confidence,
        calibrated_confidence=None, bounding_box=field.bounding_box, latency_ms=0,
        validation_results=(verification.reason_code,), evidence_reference="template:regional",
        registration_confidence=registration_confidence,
    )
    return candidate, verification


def _standard_document(record, template, extractor, decisions, criticality, claims) -> dict[str, Any]:
    started = time.perf_counter()
    with Image.open(ROOT / record.image_path) as opened:
        source = opened.convert("L")
        source.load()
    resized = source.resize((template.reference_dimensions.width_px,
                             template.reference_dimensions.height_px))
    registration_started = time.perf_counter()
    ready, registration_method, registration = _align_or_rescale(resized, template, None)
    registration_ms = (time.perf_counter() - registration_started) * 1000
    truth = {key: value for key, value in record.truth_fields.items() if key != "service_lines"}
    regions = [region for region in template.field_regions if _truth_name(region.field_name, truth)]
    scoped = template.model_copy(update={"field_regions": regions})
    ocr_started = time.perf_counter()
    extracted = extractor.extract_fields(ready, scoped, 1)
    ocr_ms = (time.perf_counter() - ocr_started) * 1000
    field_rows, field_decisions = [], []
    for field in extracted:
        canonical = _truth_name(field.field_name, truth)
        if canonical is None:
            continue
        expected = truth[canonical]
        actual = field.normalized_value or field.raw_value
        exact = _norm(actual) == _norm(expected)
        raw_exact = _norm(field.raw_value) == _norm(expected)
        crop_iou = None
        if field.field_name in record.crop_boxes:
            raw_truth = record.crop_boxes[field.field_name]
            scale_x = ready.width / source.width
            scale_y = ready.height / source.height
            truth_box = tuple(round(value * (scale_x if index % 2 == 0 else scale_y))
                              for index, value in enumerate(raw_truth))
            crop_iou = _iou((field.bounding_box.x0, field.bounding_box.y0,
                             field.bounding_box.x1, field.bounding_box.y1), truth_box)
        candidate, verification = _field_candidate(field, canonical, None)
        decision = decisions.decide(DecisionContext(
            field_name=canonical, document_family=record.expected_family,
            criticality=criticality.for_field(canonical), candidates=[candidate],
            deterministic_evidence={verification.reason_code} if verification.valid else set(),
            hard_validation_passed=verification.valid, registration_confidence=None,
            structural_evidence_source=None,
        ))
        field_decisions.append(decision)
        field_rows.append({"document_id": record.document_id, "source_dataset": record.source_dataset,
            "quality_bucket": record.quality_bucket, "family": record.expected_family,
            "field_name": canonical, "source_field_name": field.field_name,
            "expected": str(expected), "raw": field.raw_value, "normalized": actual,
            "raw_exact": raw_exact, "final_exact": exact, "critical": canonical in CRITICAL_FIELDS,
            "crop_iou": crop_iou, "crop_correct": crop_iou is None or crop_iou >= .50,
            "ocr_correct_given_correct_crop": bool(exact and (crop_iou is None or crop_iou >= .50)),
            "parser_success": bool(str(field.raw_value or "").strip()),
            "normalization_correct": exact, "confidence": field.confidence,
            "disposition": decision.disposition.value,
            "auto_accepted": decision.disposition.value in {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"},
            "bbox": field.bounding_box.model_dump(mode="json")})
    claim = claims.decide(ClaimDecisionContext(
        claim_id=record.document_id, document_family=record.expected_family,
        field_decisions=field_decisions, registration_integrity_valid=False,
        enforce_configured_required_fields=True,
    )) if field_decisions else None
    service_payload = None
    if record.expected_family == "UB04" and record.truth_fields.get("service_lines"):
        table_started = time.perf_counter()
        service_lines, reconstruction = extractor.extract_ub04_service_lines(
            ready, template, 1, registration_confidence=0.0,
            claim_total=record.truth_fields.get("total_charge"))
        service_payload = {
            "truth_rows": len(record.truth_fields["service_lines"]),
            "detected_rows": len(service_lines),
            "row_detection_correct": len(service_lines) == len(record.truth_fields["service_lines"]),
            "reconstruction": reconstruction.model_dump(mode="json") if reconstruction else None,
            "latency_ms": (time.perf_counter() - table_started) * 1000,
        }
    return {"document_id": record.document_id, "image_path": record.image_path,
        "source_dataset": record.source_dataset, "quality_bucket": record.quality_bucket,
        "expected_family": record.expected_family, "truth_route_forced": True,
        "registration_method": registration_method, "registration_configured": False,
        "registration_success": False, "registration_evidence": (registration.model_dump(mode="json")
                                                                    if registration else None),
        "fields": field_rows, "service_lines": service_payload,
        "claim_decision": claim.model_dump(mode="json") if claim else None,
        "latency_ms": {"registration": registration_ms, "field_ocr": ocr_ms,
                       "total": (time.perf_counter() - started) * 1000},
        "regional_ocr_cost": extractor.last_field_ocr_cost, "cloud_api_calls": 0}


def _aggregate(documents: list[dict[str, Any]]) -> dict[str, Any]:
    best = {}
    for document in documents:
        for field in document["fields"]:
            key = (document["document_id"], field["field_name"])
            if key not in best or field["confidence"] > best[key]["confidence"]:
                best[key] = field
    fields = list(best.values())
    critical = [field for field in fields if field["critical"]]
    accepted = [field for field in fields if field["auto_accepted"]]
    crops = [field for field in fields if field["crop_iou"] is not None]
    tables = [doc["service_lines"] for doc in documents if doc["service_lines"]]
    by_family = {}
    for family in ("CMS1500", "UB04"):
        family_fields = [field for field in fields if field["family"] == family]
        family_docs = [doc for doc in documents if doc["expected_family"] == family]
        by_family[family] = {"documents": len(family_docs), "fields": len(family_fields),
            "field_exact_match": ratio(sum(field["final_exact"] for field in family_fields), len(family_fields)),
            "critical_exact_match": ratio(sum(field["final_exact"] for field in family_fields if field["critical"]),
                                            sum(field["critical"] for field in family_fields)),
            "p95_latency_ms": percentile((doc["latency_ms"]["total"] for doc in family_docs), .95)}
    return {
        "evidence_class": "ENGINEERING_BENCHMARK_ONLY", "production_promotion_authority": False,
        "truth_route_forced": True, "documents": len(documents), "fields": len(fields),
        "registration_configured_rate": ratio(sum(doc["registration_configured"] for doc in documents), len(documents)),
        "registration_success_rate": ratio(sum(doc["registration_success"] for doc in documents), len(documents)),
        "crop_correctness": ratio(sum(field["crop_correct"] for field in crops), len(crops)),
        "raw_ocr_exact_match": ratio(sum(field["raw_exact"] for field in fields), len(fields)),
        "ocr_accuracy_given_correct_crop": ratio(sum(field["ocr_correct_given_correct_crop"] for field in fields
                                                       if field["crop_correct"]),
                                                   sum(field["crop_correct"] for field in fields)),
        "normalization_correctness": ratio(sum(field["normalization_correct"] for field in fields), len(fields)),
        "parser_success_rate": ratio(sum(field["parser_success"] for field in fields), len(fields)),
        "field_exact_match": ratio(sum(field["final_exact"] for field in fields), len(fields)),
        "critical_exact_match": ratio(sum(field["final_exact"] for field in critical), len(critical)),
        "safe_field_coverage": ratio(sum(field["auto_accepted"] and field["final_exact"] for field in fields), len(fields)),
        "field_hitl_rate": ratio(sum(not field["auto_accepted"] for field in fields), len(fields)),
        "false_accepts": sum(field["auto_accepted"] and not field["final_exact"] for field in fields),
        "critical_false_accepts": sum(field["critical"] and field["auto_accepted"] and
                                      not field["final_exact"] for field in fields),
        "claim_stp_rate": ratio(sum((doc["claim_decision"] or {}).get("disposition") == "STP_ELIGIBLE"
                                    for doc in documents), len(documents)),
        "ub_service_lines": {"documents": len(tables),
            "row_detection_accuracy": ratio(sum(table["row_detection_correct"] for table in tables), len(tables)),
            "truth_rows": sum(table["truth_rows"] for table in tables),
            "detected_rows": sum(table["detected_rows"] for table in tables)},
        "p50_latency_ms": percentile((doc["latency_ms"]["total"] for doc in documents), .50),
        "p95_latency_ms": percentile((doc["latency_ms"]["total"] for doc in documents), .95),
        "by_family": by_family, "cloud_api_calls": 0, "cloud_cost_usd": 0.0,
        "limitations": ["Registration reference images are not configured in the frozen runtime; rescale-only is measured honestly.",
                        "Extraction sample is deterministic and bounded to 15 pages per standard family (12 public synthetic + 3 representative observation)."],
    }


def _end_to_end(extraction_docs: list[dict[str, Any]]) -> dict[str, Any]:
    routing_path = RESULT_ROOT / "routing_details.jsonl"
    routes = {row["document_id"]: row for row in
              (json.loads(line) for line in routing_path.read_text("utf-8").splitlines())}
    scoped_docs = [doc for doc in extraction_docs if doc["document_id"] in routes]
    best = {}
    for doc in scoped_docs:
        for field in doc["fields"]:
            key = (doc["document_id"], field["field_name"])
            if key not in best or field["confidence"] > best[key]["confidence"]:
                best[key] = field
    fields = list(best.values())
    end_correct = 0
    for doc in scoped_docs:
        route_correct = routes.get(doc["document_id"], {}).get("predicted_processing_route") == {
            "CMS1500": "CMS_STANDARD_EXTRACTOR", "UB04": "UB_STANDARD_EXTRACTOR"}[doc["expected_family"]]
        end_correct += sum(field["final_exact"] and route_correct for key, field in best.items()
                           if key[0] == doc["document_id"])
    route_correct_docs = sum(routes[doc["document_id"]].get("predicted_processing_route") == {
        "CMS1500": "CMS_STANDARD_EXTRACTOR", "UB04": "UB_STANDARD_EXTRACTOR"}[doc["expected_family"]]
                             for doc in scoped_docs)
    return {"evidence_class": "ENGINEERING_BENCHMARK_ONLY", "production_promotion_authority": False,
        "documents": len(scoped_docs), "extraction_documents_total": len(extraction_docs),
        "documents_without_completed_routing_baseline": len(extraction_docs) - len(scoped_docs),
        "fields": len(fields),
        "layer_1_processing_route_accuracy": ratio(route_correct_docs, len(scoped_docs)),
        "layer_2_extraction_accuracy_given_truth_route": ratio(sum(field["final_exact"] for field in fields), len(fields)),
        "layer_3_end_to_end_field_accuracy": ratio(end_correct, len(fields)),
        "note": "Layer 3 requires the canonical runtime route to reach the correct fixed extractor."}


def run() -> dict[str, Any]:
    manifest = build_manifest()
    registry = TemplateRegistry.load_from_directory()
    templates = {"CMS1500": registry.latest_for_form_type(ClaimFormType.CMS1500),
                 "UB04": registry.latest_for_form_type(ClaimFormType.UB04)}
    extractor = StandardFormExtractionService(RapidOCRTextExtractor())
    decisions = EvidenceDecisionService(route_mode="runtime")
    criticality = CriticalityPolicy.load(DEFAULT_CRITICALITY_PATH)
    claims = ClaimDecisionService.load()
    selected = _select(manifest.records, "CMS1500") + _select(manifest.records, "UB04")
    documents = []
    checkpoint = RESULT_ROOT / "extraction_details.jsonl"
    completed = {}
    if checkpoint.exists():
        for line in checkpoint.read_text("utf-8").splitlines():
            row = json.loads(line)
            completed[row["document_id"]] = row
    with checkpoint.open("a", encoding="utf-8") as stream:
        for index, record in enumerate(selected, 1):
            row = completed.get(record.document_id)
            if row is None:
                row = _standard_document(record, templates[record.expected_family], extractor,
                                         decisions, criticality, claims)
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                stream.flush()
            documents.append(row)
            if index % 10 == 0:
                print(json.dumps({"extraction_completed": index, "extraction_total": len(selected)}), flush=True)
    metrics = _aggregate(documents)
    end_to_end = _end_to_end(documents)
    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    (PHASE_ROOT / "extraction_metrics.json").write_text(json.dumps(metrics, indent=2), "utf-8")
    (PHASE_ROOT / "end_to_end_metrics.json").write_text(json.dumps(end_to_end, indent=2), "utf-8")
    return {"extraction": metrics, "end_to_end": end_to_end}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
