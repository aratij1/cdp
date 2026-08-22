"""Layered Bundle-D evaluation; never collapses routing/layout/decision metrics."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import Counter
from pathlib import Path

from PIL import Image

from evaluation.generate_bundle_d_dev_v1 import DEFAULT_OUTPUT, DEFAULT_UNTOUCHED, DEFAULT_UNTOUCHED_V2
from packages.criticality import CriticalityPolicy, DEFAULT_CRITICALITY_PATH
from packages.evidence_decision import DecisionContext, EvidenceDecisionService, FieldDisposition
from packages.layout_intelligence import BundleDLayoutEngine, GenericRoute
from packages.ocr.contracts import OCRCandidate
from workers.page_detection.text_extraction import PaddleOCRTextExtractor, RapidOCRFullPageTextExtractor


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def evaluate(dataset: Path, engine_name: str) -> dict:
    manifest = json.loads((dataset / "manifest.json").read_text("utf-8"))
    truth = [json.loads(line) for line in (dataset / "ground_truth.jsonl").read_text("utf-8").splitlines()]
    extractor = (PaddleOCRTextExtractor() if engine_name == "paddleocr"
                 else RapidOCRFullPageTextExtractor())
    layout = BundleDLayoutEngine()
    decisions = EvidenceDecisionService(route_mode="runtime")
    criticality = CriticalityPolicy.load(DEFAULT_CRITICALITY_PATH)
    counts = Counter(); latencies = []; errors = Counter()
    predictions = []
    for expected in truth:
        image = Image.open(dataset / expected["path"]).convert("RGB")
        started = time.perf_counter()
        ocr = extractor.extract(image)
        result = layout.extract(ocr, page_number=1, width=image.width, height=image.height,
                                engine=getattr(extractor, "engine_name", engine_name))
        latencies.append(time.perf_counter()-started)
        expected_nonclaim = expected["family"] == "NON_CLAIM"
        counts["documents"] += 1
        counts["unknown_route_correct"] += int(result.route is not GenericRoute.KNOWN_STANDARD)
        counts["nonclaim_total"] += int(expected_nonclaim)
        counts["nonclaim_correct"] += int(expected_nonclaim and result.route is GenericRoute.NON_CLAIM)
        counts["labels_total"] += len(expected["fields"])
        counts["labels_detected"] += len(set(expected["fields"]) & set(result.candidates))
        output_fields = {}
        for field_name, expected_value in expected["fields"].items():
            candidates = result.candidates.get(field_name, [])
            if not candidates:
                errors["LABEL_NOT_DETECTED_OR_VALUE_NOT_LINKED"] += 1
                counts["fields_total"] += 1
                counts["critical_total"] += int(criticality.for_field(field_name).value in {"C2", "C3"})
                continue
            best = candidates[0]
            correct = _norm(best.value) == _norm(expected_value)
            counts["links_total"] += 1; counts["links_correct"] += int(correct)
            counts["fields_total"] += 1; counts["fields_correct"] += int(correct)
            is_critical = criticality.for_field(field_name).value in {"C2", "C3"}
            counts["critical_total"] += int(is_critical); counts["critical_correct"] += int(is_critical and correct)
            ocr_candidates = [OCRCandidate(
                value=item.value, raw_value=item.value, engine=result.engine,
                model_name=getattr(extractor, "model_name", engine_name),
                model_version=getattr(extractor, "model_version", "unknown"),
                preprocessing_variant="prepared_full_page", raw_confidence=item.confidence,
                calibrated_confidence=None, bounding_box=item.bbox, latency_ms=0,
                validation_results=(("DATATYPE_VALID", item.relationship_evidence.relationship)
                                    if item.datatype_valid else (item.relationship_evidence.relationship,)),
                evidence_reference=f"layout:{item.relationship_evidence.relationship}",
            ) for item in candidates]
            decision = decisions.decide(DecisionContext(
                field_name=field_name, document_family=result.schema_evidence.schema_family,
                criticality=criticality.for_field(field_name), candidates=ocr_candidates,
                deterministic_evidence={"DATATYPE_VALID"} if best.datatype_valid else set(),
                hard_validation_passed=best.datatype_valid,
                structural_evidence_source=best.relationship_evidence.relationship,
            ))
            accepted = decision.disposition in {FieldDisposition.AUTO_ACCEPTED, FieldDisposition.REFERENCE_CONFIRMED}
            counts["accepted"] += int(accepted); counts["false_accepts"] += int(accepted and not correct)
            counts["review"] += int(not accepted)
            output_fields[field_name] = {"value": best.value, "correct": correct,
                                         "disposition": decision.disposition.value}
        predictions.append({"document_id": expected["document_id"], "route": result.route.value,
                            "schema": result.schema_evidence.schema_family, "fields": output_fields})
    ratio = lambda numerator, denominator: counts[numerator] / counts[denominator] if counts[denominator] else None
    report = {
        "qualification": {"dataset_id": manifest["dataset_id"],
                          "frozen_holdout": manifest["frozen_holdout"],
                          "tuning_prohibited": manifest["tuning_prohibited"]},
        "engine": engine_name,
        "routing": {"standard_form_precision": None, "standard_form_recall": None,
                    "unknown_layout_recall": ratio("unknown_route_correct", "documents"),
                    "non_claim_accuracy": ratio("nonclaim_correct", "nonclaim_total")},
        "layout": {"label_detection_recall": ratio("labels_detected", "labels_total"),
                   "label_value_association_accuracy": ratio("links_correct", "links_total"),
                   "table_detection_accuracy": None, "table_cell_accuracy": None},
        "extraction": {"field_exact_match": ratio("fields_correct", "fields_total"),
                       "critical_field_exact_match": ratio("critical_correct", "critical_total"),
                       "correct": counts["fields_correct"], "total": counts["fields_total"]},
        "decision": {"safe_coverage": ratio("accepted", "fields_total"),
                     "false_accepts": counts["false_accepts"],
                     "field_hitl": ratio("review", "fields_total")},
        "claim": {"claim_stp": None, "claim_hitl": None,
                  "note": "Development schema does not contain a complete governed claim policy."},
        "runtime": {"mean_seconds": statistics.fmean(latencies),
                    "p95_seconds": sorted(latencies)[max(0, __import__('math').ceil(.95*len(latencies))-1)]},
        "errors": dict(errors), "predictions": predictions,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=("development", "untouched", "untouched_v2"), default="development")
    parser.add_argument("--engine", choices=("rapidocr", "paddleocr"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    dataset = {"development": DEFAULT_OUTPUT, "untouched": DEFAULT_UNTOUCHED,
               "untouched_v2": DEFAULT_UNTOUCHED_V2}[args.dataset]
    report = evaluate(dataset, args.engine)
    output = args.output or Path("evaluation_results") / dataset.name / f"layout_{args.engine}.json"
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps({key: report[key] for key in ("qualification", "routing", "layout", "extraction", "decision", "runtime")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
