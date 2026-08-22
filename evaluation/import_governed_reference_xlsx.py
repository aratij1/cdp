"""Validate governed reference decisions from an XLSX workbook.

The reader intentionally uses the Python standard library, keeping the runtime
free from an Excel dependency. Only fully governed, independently sourced
decisions are emitted for inference optimization.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": MAIN, "r": REL, "pr": PACKAGE_REL}
TRUE_VALUES = {"1", "true", "yes", "y"}
ACCEPTED_STRENGTHS = {"TIER_A_REFERENCE", "TIER_A_APPROVED_CORRECTION", "TIER_B_DOWNSTREAM"}


def _column(cell_reference: str) -> int:
    letters = "".join(char for char in cell_reference if char.isalpha())
    value = 0
    for char in letters:
        value = value * 26 + ord(char.upper()) - 64
    return value - 1


def read_sheet(path: Path, sheet_name: str) -> list[dict[str, str]]:
    with ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.iter(f"{{{MAIN}}}t"))
                      for item in root.findall("m:si", NS)]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        target = None
        for sheet in workbook.findall(".//m:sheets/m:sheet", NS):
            if sheet.attrib["name"] == sheet_name:
                target = targets[sheet.attrib[f"{{{REL}}}id"]].lstrip("/")
                break
        if target is None:
            raise ValueError(f"Workbook does not contain sheet {sheet_name!r}")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        xml = ET.fromstring(archive.read(target))
        matrix: list[list[str]] = []
        for row in xml.findall(".//m:sheetData/m:row", NS):
            values: dict[int, str] = {}
            for cell in row.findall("m:c", NS):
                kind = cell.attrib.get("t")
                raw = cell.find("m:v", NS)
                inline = cell.find("m:is", NS)
                value = "".join(node.text or "" for node in inline.iter(f"{{{MAIN}}}t")) \
                    if inline is not None else (raw.text if raw is not None else "")
                if kind == "s" and value:
                    value = shared[int(value)]
                values[_column(cell.attrib["r"])] = str(value or "").strip()
            width = max(values, default=-1) + 1
            matrix.append([values.get(index, "") for index in range(width)])
    if not matrix:
        return []
    headers = matrix[0]
    return [{header: row[index] if index < len(row) else "" for index, header in enumerate(headers)}
            for row in matrix[1:] if any(row)]


def validate(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    accepted: list[dict[str, str]] = []
    audit: list[dict[str, object]] = []
    for row in rows:
        decision = row.get("decision", "").upper()
        canonical_key = "|".join((
            row.get("document_id", ""), row.get("page_number", ""),
            row.get("document_family", ""), row.get("service_line_number", ""),
            row.get("field_name", ""),
        ))
        reasons: list[str] = []
        if decision == "PENDING":
            reasons.append("PENDING_DECISION")
        elif decision not in {"REFERENCE_VERIFIED", "REFERENCE_CONTRADICTION"}:
            reasons.append("INVALID_DECISION")
        if decision == "REFERENCE_VERIFIED":
            required = ["reference_value", "reference_provider", "reference_dataset_version",
                        "source_record_id", "source_lineage", "matching_attributes", "approved_by",
                        "approved_at"]
            reasons.extend(f"MISSING_{name.upper()}" for name in required if not row.get(name))
            if row.get("label_strength") not in ACCEPTED_STRENGTHS:
                reasons.append("UNACCEPTED_LABEL_STRENGTH")
            if row.get("independent_truth", "").lower() not in TRUE_VALUES:
                reasons.append("INDEPENDENT_TRUTH_NOT_CONFIRMED")
            if row.get("criticality") == "CRITICAL" and not (
                row.get("second_approved_by") and row.get("second_approved_at")
            ):
                reasons.append("SECOND_APPROVAL_REQUIRED")
            if row.get("contradictions"):
                reasons.append("CONTRADICTION_PRESENT")
        status = "ACCEPTED" if not reasons else "NOT_APPLIED"
        audit.append({"source_identity_key": row.get("identity_key"),
                      "canonical_identity_key": canonical_key, "decision": decision,
                      "status": status, "reasons": reasons})
        if status == "ACCEPTED":
            accepted.append({
                "identity_key": canonical_key,
                "decision": decision,
                "reference_value": row.get("reference_value", ""),
                "reference_provider": row.get("reference_provider", ""),
                "reference_dataset_version": row.get("reference_dataset_version", ""),
                "source_record_id": row.get("source_record_id", ""),
            })
    return accepted, audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = read_sheet(args.workbook, "Reference Decisions")
    accepted, audit = validate(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "reference_decisions.json").write_text(json.dumps(accepted, indent=2), encoding="utf-8")
    (args.output / "import_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    summary = {
        "workbook_rows": len(rows),
        "accepted_decisions": len(accepted),
        "pending_or_rejected": len(rows) - len(accepted),
        "reference_verified": sum(row["decision"] == "REFERENCE_VERIFIED" for row in accepted),
        "contradictions": sum(row["decision"] == "REFERENCE_CONTRADICTION" for row in accepted),
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
