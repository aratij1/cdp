"""Machine-readable and operator-friendly mismatch reports."""

from __future__ import annotations

import csv
import html
import json
from dataclasses import asdict
from pathlib import Path

from evaluation.metrics import EvaluationMetrics


def write_reports(metrics: EvaluationMetrics, output: str | Path) -> None:
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    payload = asdict(metrics)
    (target / "evaluation.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    rows = [asdict(row) for row in metrics.mismatches]
    columns = list(rows[0]) if rows else list(asdict(metrics.mismatches[0])) if metrics.mismatches else [
        "document_id", "form_type", "field_name", "expected_value", "extracted_value",
        "normalized_value", "ocr_confidence", "validation_result", "extraction_method",
        "bounding_box", "crop_reference", "failure_category",
    ]
    with (target / "mismatches.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    headers = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = "".join("<tr>" + "".join(
        f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in columns
    ) + "</tr>" for row in rows)
    stp = (
        f"{metrics.straight_through_processing_rate:.2%}"
        if metrics.straight_through_processing_rate is not None else "N/A (canonical claim decision unavailable)"
    )
    summary = (
        f"<p>Normalized accuracy: {metrics.normalized_field_accuracy:.2%}; "
        f"critical false-accept rate: {metrics.critical_false_accept_rate:.2%}; "
        f"perfect claims: {metrics.perfect_claim_rate:.2%}; STP: "
        f"{stp}</p>"
    )
    document = f"<!doctype html><meta charset='utf-8'><title>Evaluation</title>{summary}<table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table>"
    (target / "mismatches.html").write_text(document, encoding="utf-8")
