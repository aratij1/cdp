"""Localization-only Phase 8.10 benchmark; no crop OCR or truth in runtime logic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.phase8_8_generalization import SOURCE_IDS
from evaluation.phase8_9_localization_provenance import _metric_records, _rows, _write, _write_rows
from packages.field_localization import (
    FieldDefinitionRegistry,
    FieldLocator,
    aggregate_localization,
    classify_region,
    production_usable,
)
from packages.page_observation import PageObservation

ROOT = Path(__file__).resolve().parents[1]
OBSERVATIONS = ROOT / "evaluation_results/phase8_8c"
TRUTH_RECORDS = ROOT / "evaluation_results/phase8_10"
OUTPUT = ROOT / "evaluation_results/phase8_10/localization_only"


def run(output: Path = OUTPUT) -> dict:
    registries = {
        "CMS1500": FieldDefinitionRegistry.load(
            ROOT / "config/field_definitions/cms1500_v1.yaml"
        ),
        "UB04": FieldDefinitionRegistry.load(
            ROOT / "config/field_definitions/ub04_v1.yaml"
        ),
    }
    locator = FieldLocator()
    metric_records = []
    audit_rows = []
    for source in SOURCE_IDS:
        rows = [
            row for row in _rows(
                TRUTH_RECORDS / source.lower() / "v3_extraction/field_records.jsonl"
            ) if row.get("dataset_role") == "VALIDATION"
        ]
        observations = {}
        for row in rows:
            document_id = row["document_id"]
            if document_id not in observations:
                observations[document_id] = PageObservation.model_validate_json(
                    (OBSERVATIONS / source.lower() / "observations" / f"{document_id}.json")
                    .read_text("utf-8")
                )
            definition = registries[row["family"]].get(
                row["family"], row["field_name"]
            )
            evidence = locator.locate(observations[document_id], definition)
            benchmark_row = {
                **row,
                "source": source,
                "localization_evidence": evidence.model_dump(mode="json"),
                "raw_ocr": None,
                "final": None,
                "candidate_trace": {},
            }
            record = _metric_records([benchmark_row], source)[0]
            metric_records.append(record)
            audit_rows.append({
                **record.model_dump(mode="json"),
                "outcome": classify_region(record).value,
                "production_usable": production_usable(record),
                "relationship_id": evidence.relationship_id,
                "relationship_type": evidence.relationship_type,
                "relationship_score": evidence.relationship_score,
                "relationship_geometry": evidence.relationship_geometry,
                "ownership_confidence": evidence.ownership_confidence,
                "ownership_reason_codes": evidence.ownership_reason_codes,
                "selected_candidate_id": evidence.selected_candidate_id,
                "candidates": [item.model_dump(mode="json") for item in evidence.candidates],
            })
    critical = [record for record in metric_records if record.critical]
    report = {
        "phase": "8.10",
        "benchmark": "LOCALIZATION_ONLY_BEFORE_OCR",
        "truth_available_to_runtime_locator": False,
        "samples": len(metric_records),
        "localization": aggregate_localization(metric_records),
        "critical_localization": aggregate_localization(critical),
    }
    _write(output / "summary.json", report)
    _write_rows(output / "localization_records.jsonl", audit_rows)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
