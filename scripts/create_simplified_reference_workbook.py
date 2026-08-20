"""Create a reviewer-friendly reference workbook without changing the governed source."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from evaluation.import_governed_reference_xlsx import read_sheet
from evaluation.reference_enrichment_workbook import _sheet

SOURCE = Path("evaluation_results/reference_enrichment/reference_decisions_governed_v4_enriched.xlsx")
OUTPUT = Path("evaluation_results/reference_enrichment/reference_decisions_SIMPLE_FILL.xlsx")
HEADERS = [
    "identity_key", "document_id", "field_name", "criticality", "current_candidate",
    "reference_value", "decision", "authorized_source_system", "source_dataset_version",
    "source_record_id", "matching_attributes", "contradictions", "primary_reviewer",
    "primary_approved_at", "second_reviewer", "second_approved_at", "claim_revalidated",
    "comment",
]


def main() -> None:
    source_rows = [row for row in read_sheet(SOURCE, "Reference Decisions") if row.get("identity_key")]
    rows = [{
        "identity_key": row.get("identity_key", ""),
        "document_id": row.get("document_id", ""),
        "field_name": row.get("field_name", ""),
        "criticality": row.get("criticality", ""),
        "current_candidate": row.get("current_candidate", ""),
        "reference_value": "", "decision": "PENDING", "authorized_source_system": "",
        "source_dataset_version": "", "source_record_id": "", "matching_attributes": "",
        "contradictions": "[]", "primary_reviewer": "", "primary_approved_at": "",
        "second_reviewer": "", "second_approved_at": "", "claim_revalidated": "FALSE",
        "comment": "",
    } for row in source_rows]
    example = [{
        "identity_key": "EXAMPLE|1|CMS1500||patient_last",
        "document_id": "EXAMPLE", "field_name": "patient_last", "criticality": "CRITICAL",
        "current_candidate": "KARNO", "reference_value": "KARNO",
        "decision": "REFERENCE_VERIFIED", "authorized_source_system": "ELIGIBILITY_MEMBER_MASTER",
        "source_dataset_version": "2026-08-01", "source_record_id": "MEMBER-847291",
        "matching_attributes": '["member_id","dob","name"]', "contradictions": "[]",
        "primary_reviewer": "reviewer1@company.com",
        "primary_approved_at": "2026-08-02T09:09:00Z",
        "second_reviewer": "reviewer2@company.com",
        "second_approved_at": "2026-08-02T09:30:00Z", "claim_revalidated": "TRUE",
        "comment": "Exact member ID and DOB; normalized name matched.",
    }]
    instructions = [
        {"Field": "decision", "What to enter": "REFERENCE_VERIFIED, REFERENCE_CONTRADICTION, or PENDING"},
        {"Field": "matching_attributes", "What to enter": '["member_id","dob","name"] — use real independent matches'},
        {"Field": "authorized_source_system", "What to enter": "Actual eligibility/provider/downstream system name"},
        {"Field": "source_record_id", "What to enter": "Real record identifier from that system"},
        {"Field": "approval timestamps", "What to enter": "ISO 8601, e.g. 2026-08-02T09:09:00Z"},
        {"Field": "critical rows", "What to enter": "Two different reviewers are required"},
        {"Field": "no independent evidence", "What to enter": "Keep decision=PENDING and claim_revalidated=FALSE"},
    ]
    sheets = [
        ("FILL THESE ROWS", HEADERS, rows, "decision"),
        ("EXAMPLE ONLY", HEADERS, example, "decision"),
        ("INSTRUCTIONS", ["Field", "What to enter"], instructions, None),
    ]
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, 4)
    )
    workbook_sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, (name, *_rest) in enumerate(sheets, 1)
    )
    relationships = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, 4)
    )
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", f'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{overrides}</Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{workbook_sheets}</sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        archive.writestr("xl/styles.xml", '<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="6"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF4CC"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="D9EAD3"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="F4CCCC"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FCE5CD"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="5"><xf/><xf fillId="2" applyFill="1"/><xf fillId="3" applyFill="1"/><xf fillId="4" applyFill="1"/><xf fillId="5" applyFill="1"/></cellXfs></styleSheet>')
        for index, (_name, headers, data, style_key) in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet(headers, data, style_key))
    print(OUTPUT)


if __name__ == "__main__":
    main()
