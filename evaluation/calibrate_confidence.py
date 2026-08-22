"""Train and evaluate confidence calibration without using holdout labels."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from evaluation.matcher import match_fields
from evaluation.normalizers import NormalizerRegistry
from evaluation.schemas import GroundTruthDataset, PredictionDataset
from packages.confidence import (
    CalibrationFeatureRecord,
    calibration_metrics,
    fit_isotonic,
    fit_platt,
)


def _family(field: str) -> str:
    if "name" in field or field.endswith(("_first", "_last")):
        return "name"
    if "addr" in field or field.endswith(("_city", "_state", "_zip")):
        return "address"
    if "date" in field or field.endswith("_dob"):
        return "date"
    if field in {"cpt_hcpcs", "principal_diagnosis", "diagnosis_code"}:
        return "clinical_code"
    if field in {"npi", "provider_npi", "member_id", "insured_id_number"}:
        return "identifier"
    if "charge" in field or "amount" in field or field == "units":
        return "financial"
    return "other"


def _feature_records(
    truth: GroundTruthDataset, predictions: PredictionDataset
) -> list[CalibrationFeatureRecord]:
    normalizers = NormalizerRegistry()
    records = []
    for pair in match_fields(truth, predictions):
        if pair.document.split not in {"calibration", "validation"} or pair.prediction is None:
            continue
        prediction = pair.prediction
        expected = pair.truth.expected_normalized
        if expected is None:
            expected = normalizers.normalize(pair.truth.field_name, pair.truth.expected_raw)
        actual = prediction.normalized_value
        if actual is None:
            actual = normalizers.normalize(pair.truth.field_name, prediction.raw_value)
        candidates = prediction.metadata.get("ocr_candidates", [])
        selected_value = str(prediction.raw_value or prediction.normalized_value or "").strip()
        supporting = {
            str(item.get("engine", ""))
            for item in candidates
            if str(item.get("value", "")).strip() == selected_value
        }
        confidences: dict[str, float] = {}
        for item in candidates:
            engine = str(item.get("engine", "")).lower()
            confidence = item.get("confidence")
            if isinstance(confidence, int | float):
                confidences[engine] = max(confidences.get(engine, 0.0), float(confidence))
        engine = prediction.extraction_method.split(":", 1)[0].lower()
        registration = prediction.metadata.get("registration_confidence")
        reference = prediction.metadata.get("reference_match_score")
        records.append(
            CalibrationFeatureRecord(
                document_id=pair.document.document_id,
                split=pair.document.split,
                document_type=pair.document.form_type,
                field_name=pair.truth.field_name,
                field_family=_family(pair.truth.field_name),
                criticality="CRITICAL" if pair.truth.critical else "NON_CRITICAL",
                selected_engine=engine,
                rapidocr_confidence=confidences.get("rapidocr"),
                paddle_confidence=confidences.get("paddleocr"),
                tesseract_confidence=max(
                    (score for name, score in confidences.items() if name.startswith("tesseract")),
                    default=None,
                ),
                selected_confidence=float(prediction.confidence or 0.0),
                engine_agreement_count=len(supporting),
                registration_confidence=float(registration)
                if isinstance(registration, int | float)
                else None,
                image_quality_score=None,
                format_valid=prediction.validation_result.startswith("VALID"),
                reference_match_score=float(reference)
                if isinstance(reference, int | float)
                else None,
                cross_field_consistency=prediction.metadata.get("cross_field_consistency"),
                preprocessing_profile=prediction.extraction_method.split(":", 1)[-1],
                label_contamination_detected=bool(
                    prediction.metadata.get("label_contamination_detected", False)
                ),
                correct=(expected or "") == (actual or ""),
            )
        )
    return records


def run(args: argparse.Namespace) -> dict:
    truth = GroundTruthDataset.model_validate_json(args.truth.read_text("utf-8"))
    predictions = PredictionDataset.model_validate_json(args.predictions.read_text("utf-8"))
    records = _feature_records(truth, predictions)
    by_family: dict[str, list[CalibrationFeatureRecord]] = defaultdict(list)
    for record in records:
        by_family[record.field_family].append(record)
    reports = {}
    registry_models = []
    for family, items in sorted(by_family.items()):
        training = [item for item in items if item.split == "calibration"]
        validation = [item for item in items if item.split == "validation"]
        if len(training) < 10 or len(validation) < 2:
            reports[family] = {"status": "INSUFFICIENT_DATA", "train": len(training), "validation": len(validation)}
            continue
        scores = [item.selected_confidence for item in training]
        labels = [item.correct for item in training]
        platt = fit_platt(scores, labels, f"{args.version}:{family}:platt")
        isotonic = fit_isotonic(scores, labels, f"{args.version}:{family}:isotonic")
        validation_scores = [item.selected_confidence for item in validation]
        validation_labels = [item.correct for item in validation]
        raw_metrics = calibration_metrics(validation_scores, validation_labels)
        candidates = {
            "platt": (platt, calibration_metrics([platt.predict(score) for score in validation_scores], validation_labels)),
            "isotonic": (isotonic, calibration_metrics([isotonic.predict(score) for score in validation_scores], validation_labels)),
        }
        selected_name, (selected, _selected_metrics) = min(
            candidates.items(),
            key=lambda item: (
                item[1][1].brier_score,
                item[1][1].expected_calibration_error,
                0 if item[0] == "platt" else 1,
            ),
        )
        reports[family] = {
            "status": "SELECTED",
            "train": len(training),
            "validation": len(validation),
            "selected": selected_name,
            "raw": asdict(raw_metrics),
            "models": {name: asdict(metrics) for name, (_, metrics) in candidates.items()},
        }
        for field in sorted({item.field_name for item in items}):
            payload = {"engine": "*", "field_name": field, "type": selected_name, "version": selected.version}
            if selected_name == "platt":
                payload.update(slope=selected.slope, intercept=selected.intercept)
            else:
                payload.update(thresholds=list(selected.thresholds), probabilities=list(selected.probabilities))
            registry_models.append(payload)

    output = {
        "schema_version": "1.0",
        "version": args.version,
        "status": "SHADOW_ONLY",
        "training_split": "calibration",
        "selection_split": "validation",
        "holdout_used": False,
        "holdout_documents_excluded": sum(document.split == "holdout" for document in truth.documents),
        "feature_records": len(records),
        "families": reports,
        "models": registry_models,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "features.jsonl").write_text(
        "".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8"
    )
    (args.output_dir / "calibration_report.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    args.registry.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "version": args.version,
                "status": "SHADOW_ONLY",
                "models": registry_models,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--truth", type=Path, default=Path("evaluation_data/ground_truth.json"))
    result.add_argument("--predictions", type=Path, default=Path("evaluation_results/vnext_accuracy_improvement/predictions_with_unstructured.json"))
    result.add_argument("--output-dir", type=Path, default=Path("evaluation_results/confidence_calibration"))
    result.add_argument("--registry", type=Path, default=Path("config/calibration/field_models_v1.json"))
    result.add_argument("--version", default="confidence-v1")
    return result


if __name__ == "__main__":
    print(json.dumps(run(parser().parse_args()), indent=2))
