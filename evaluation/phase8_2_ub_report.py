"""Build detailed UB service-line metrics from a golden evaluation run."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from packages.forms.ub04 import UB04StructuralMapDetector
from packages.page_observation import PageObservation
from workers.table_extraction.observation_service_lines import UB04ObservationServiceLineExtractor

ROOT = Path(__file__).resolve().parents[1]


def run(input_run: Path, observation_cache: Path, output: Path) -> dict:
    rows = [json.loads(line) for line in (input_run / "service_line_records.jsonl").read_text("utf-8").splitlines()]
    fields = [json.loads(line) for line in (input_run / "field_records.jsonl").read_text("utf-8").splitlines()]
    truth_documents = sorted({row["document_id"] for row in rows})
    predicted_rows = 0
    for document_id in truth_documents:
        observation = PageObservation.model_validate_json(
            (observation_cache / f"{document_id}.json").read_text("utf-8")
        )
        structure = UB04StructuralMapDetector().detect(observation)
        predicted_rows += len(UB04ObservationServiceLineExtractor().extract(
            observation, structure
        ).lines)
    true_positive_rows = sum(row["row_detected"] for row in rows)
    columns = list(rows[0]["cells"])
    column_accuracy = {
        name: sum(row["cells"][name] for row in rows) / len(rows) for name in columns
    }
    by_doc = defaultdict(list)
    for row in rows:
        by_doc[row["document_id"]].append(row)
    totals = {
        row["document_id"]: Decimal(str(row["expected"]))
        for row in fields if row["family"] == "UB04" and row["field_name"] == "total_charge"
    }
    reconciliation = {}
    for document_id, values in by_doc.items():
        charges = [
            Decimal(row["predicted_values"]["charge"])
            for row in values if row["predicted_values"]["charge"] is not None
        ]
        observed = sum(charges, Decimal("0"))
        expected = totals.get(document_id)
        reconciliation[document_id] = {
            "sum_line_charges": str(observed), "claim_total": str(expected),
            "reconciled": expected is not None and abs(observed - expected) <= Decimal("0.01"),
        }
    result = {
        "truth_rows": len(rows), "predicted_rows": predicted_rows,
        "true_positive_rows": true_positive_rows,
        "row_recall": true_positive_rows / len(rows),
        "row_precision": true_positive_rows / max(1, predicted_rows),
        "column_cell_accuracy": sum(
            value for row in rows for value in row["cells"].values()
        ) / (len(rows) * len(columns)),
        "column_accuracy": column_accuracy,
        "exact_row_accuracy": sum(row["exact_row"] for row in rows) / len(rows),
        "failure_layers": dict(Counter(row["failure_layer"] for row in rows)),
        "charge_reconciliation_rate": sum(
            item["reconciled"] for item in reconciliation.values()
        ) / len(reconciliation),
        "charge_reconciliation": reconciliation,
    }
    output.write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-run", type=Path, required=True)
    parser.add_argument("--observation-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.input_run, args.observation_cache, args.output), indent=2))
