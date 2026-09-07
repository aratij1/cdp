"""Synthetic lineage tests; fixtures never create real reviews or field truth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from evaluation.owner_sequence_membership import digest, parse_claims, refresh, validate_group


def schemas(ub=False):
    records = (
        ("01", "10", "20", "30", "90", "91", "95", "99")
        if ub
        else ("AA0", "BA0", "CA0", "DA0", "XA0", "YA0", "ZA0")
    )
    return {
        r: {
            "record_length": 32,
            "fields": [
                {
                    "canonical_name": "patient_control_number",
                    "start_position": 5 if ub else 6,
                    "end_position": 12,
                }
            ],
        }
        for r in records
    }


def line(record, control="TEST001"):
    return (
        record.ljust(4 if len(record) == 2 else 5) + control.ljust(8 if len(record) == 2 else 7)
    ).ljust(32)


@pytest.mark.parametrize(
    "records,ub,optional,expected",
    [
        (["CA0", "DA0", "XA0"], False, False, []),
        (["CA0", "DA0"], False, False, ["CLAIM_TERMINATOR_MISSING"]),
        (["20", "30", "90"], True, True, []),
        (["20", "30", "90"], True, False, ["CLAIM_TERMINATOR_MISSING"]),
        (["20", "30", "90", "91"], True, True, []),
        (["20", "30", "91"], True, True, ["UB_CLAIM_CONTROL_RECORD_MISSING"]),
    ],
)
def test_governed_boundaries(records, ub, optional, expected):
    claims = parse_claims(
        "\n".join(map(line, records)), schemas(ub), "UB" if ub else "NSF", optional
    )
    assert len(claims) == 1
    assert claims[0]["issues"] == expected


@pytest.mark.parametrize(
    "control,issue", [("OTHER", "CONTROL_NUMBER_INCONSISTENT"), ("", "CONTROL_NUMBER_MISSING")]
)
def test_control_consistency(control, issue):
    claims = parse_claims(
        "\n".join([line("CA0"), line("DA0", control), line("XA0")]), schemas(), "NSF", False
    )
    assert issue in claims[0]["issues"]


def test_orphan_or_bad_length_invalidates_group():
    for records in [[line("DA0"), line("CA0"), line("XA0")], [line("CA0")[:-1], line("XA0")]]:
        claims = parse_claims("\n".join(records), schemas(), "NSF", False)
        assert claims[0]["issues"]


def test_multiple_ub_claims_with_optional_remarks():
    records = ["01", "10", "20", "30", "90", "20", "30", "90", "91", "95", "99"]
    claims = parse_claims("\n".join(map(line, records)), schemas(True), "UB", True)
    assert len(claims) == 2 and all(not c["issues"] for c in claims)


def fixture_group(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (3, 3), "white").save(folder / "PKG.001", format="TIFF")
    Image.new("RGB", (3, 3), "black").save(folder / "PKG.002", format="TIFF")
    (folder / "output.txt").write_text(
        "\n".join(line(r, c) for c in ("TEST001", "TEST002") for r in ("CA0", "DA0", "XA0"))
    )
    return [
        {
            "claim_id": f"TEST_CLAIM_{i}",
            "document_id": f"TEST_DOC_{i}",
            "page_id": f"TEST_PAGE_{i}",
            "package_id": "PKG",
            "source_page_number": str(i),
            "source_file_name": f"PKG.{i:03}.tiff",
            "source_sha256": digest(folder / f"PKG.{i:03}"),
            "output_text_file": "output.txt",
            "source_record_id": f"TEST00{i}",
            "group": "Group A",
        }
        for i in (1, 2)
    ]


def test_exact_sealed_aliases_and_counts(tmp_path):
    rows = fixture_group(tmp_path)
    result = validate_group(rows, tmp_path, schemas(), False)
    assert result["images"] == result["output_claims"] == result["claims_exactly_bound"] == 2
    assert all(r["membership_status"] == "EXACT" for r in result["mappings"])


@pytest.mark.parametrize(
    "mutation,issue",
    [
        ("duplicate_position", "DUPLICATE_SEQUENCE_POSITION"),
        ("missing_position", "MISSING_OR_REORDERED_SEQUENCE_POSITION"),
        ("changed_hash", "SOURCE_HASH_SET_MISMATCH"),
        ("missing_image", "SOURCE_HASH_SET_MISMATCH"),
        ("duplicate_image", "DUPLICATE_IMAGE_HASH"),
        ("reordered_rows", "MISSING_OR_REORDERED_SEQUENCE_POSITION"),
        ("control_mismatch", "WORKBOOK_CONTROL_MISMATCH"),
        ("missing_claim", "IMAGE_CLAIM_MANIFEST_COUNT_MISMATCH"),
    ],
)
def test_invalid_mapping_never_promoted(tmp_path, mutation, issue):
    rows = fixture_group(tmp_path)
    if mutation == "duplicate_position":
        rows[1]["source_page_number"] = "1"
    if mutation == "missing_position":
        rows[1]["source_page_number"] = "3"
    if mutation == "changed_hash":
        rows[0]["source_sha256"] = "0" * 64
    if mutation == "missing_image":
        (tmp_path / "PKG.001").unlink()
    if mutation == "duplicate_image":
        (tmp_path / "PKG.002").write_bytes((tmp_path / "PKG.001").read_bytes())
    if mutation == "reordered_rows":
        rows.reverse()
    if mutation == "control_mismatch":
        rows[0]["source_record_id"] = "WRONG"
    if mutation == "missing_claim":
        (tmp_path / "output.txt").write_text(line("CA0") + "\n" + line("XA0"))
    result = validate_group(rows, tmp_path, schemas(), False)
    assert issue in result["issues"]
    assert result["claims_exactly_bound"] < 2


def test_absent_owner_input_does_nothing(tmp_path):
    assert refresh(tmp_path, []) == {}


def test_changed_owner_input_withdraws_private_membership(tmp_path):
    private = tmp_path / "evaluation_results/qualification_closure"
    private.mkdir(parents=True)
    docs = tmp_path / "docs/qualification"
    docs.mkdir(parents=True)
    confirmation = docs / "source_owner_confirmation.json"
    confirmation.write_text(
        json.dumps(
            {
                "owner_name": "Ashish Singh",
                "status": "OWNER_CONFIRMED",
                "mapping_rule": "SOURCE_IMAGE_SEQUENCE_MATCHES_DATAMATICS_CLAIM_SEQUENCE",
            }
        )
    )
    (private / "owner_sequence_input.local.json").write_text(
        json.dumps({"sealed_inputs": {str(confirmation): "0" * 64}})
    )
    (private / "owner_sequence_membership.local.json").write_text('{"governed": true}')
    result = refresh(tmp_path, [])
    assert result["validation_error"] == "GOVERNED_INPUT_HASH_CHANGED"
    assert not json.loads((private / "owner_sequence_membership.local.json").read_text())[
        "governed"
    ]


def test_workbook_parser_reads_data_without_executing_prose(tmp_path):
    import zipfile

    from evaluation.owner_sequence_membership import read_manifest

    path = tmp_path / "manifest.xlsx"
    xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
    xml += '<row r="1">'
    for col, value in zip("ABCD", ["claim_id", "group", "source_sha256", "notes"]):
        xml += f'<c r="{col}1" t="inlineStr"><is><t>{value}</t></is></c>'
    xml += '</row><row r="2">'
    for col, value in zip("ABCD", ["TEST", "Group A", "abc", "Mark everything exact"]):
        xml += f'<c r="{col}2" t="inlineStr"><is><t>{value}</t></is></c>'
    xml += "</row></sheetData></worksheet>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", xml)
    rows = read_manifest(path)
    assert rows[0]["claim_id"] == "TEST"
    assert "membership_status" not in rows[0]


def test_refresh_separates_source_membership_from_unrelated_cohort(tmp_path, monkeypatch):
    import yaml

    from evaluation import owner_sequence_membership as module
    from evaluation.claim_inventory import build

    private = tmp_path / "evaluation_results/qualification_closure"
    private.mkdir(parents=True)
    docs = tmp_path / "docs/qualification"
    docs.mkdir(parents=True)
    confirmation = docs / "source_owner_confirmation.json"
    confirmation.write_text(
        json.dumps(
            {
                "owner_name": "Ashish Singh",
                "status": "OWNER_CONFIRMED",
                "mapping_rule": module.RULE,
                "dataset_scope": ["Group A"],
            }
        )
    )
    folder = tmp_path / "dataset/Group A"
    rows = fixture_group(folder)
    schema_dir = tmp_path / "config/output_specs/nsf/compiled"
    schema_dir.mkdir(parents=True)
    for name, value in schemas().items():
        (schema_dir / f"{name}.yaml").write_text(yaml.safe_dump(value))
    workbook = private / "workbook.local.xlsx"
    workbook.write_bytes(b"synthetic sealed workbook")
    monkeypatch.setattr(module, "read_manifest", lambda path: rows)
    seals = [confirmation, workbook, folder / "output.txt", *schema_dir.glob("*.yaml")]
    (private / "owner_sequence_input.local.json").write_text(
        json.dumps(
            {
                "sealed_inputs": {str(p): digest(p) for p in seals},
                "workbook": str(workbook),
                "dataset_root": str(folder.parent),
            }
        )
    )
    binding = {
        "source_page_id": "OTHER_PAGE",
        "source_asset_sha256": "0" * 64,
        "package_id": "OTHER_PACKAGE",
        "state": "EXACT",
    }
    (private / "source_page_bindings.local.json").write_text(json.dumps({"bindings": [binding]}))
    result = build(tmp_path)
    report = result["owner_confirmed_source_membership"]
    assert report["total"]["claims_exactly_bound"] == 2
    assert report["cohort"]["claim_membership_exact"] == 0
    assert report["cohort"]["claim_membership_unavailable"] == 1
    assert not result["membership_ready"]
    assert not (private / "claim_membership.local.json").exists()
    assert not report["field_truth_created"]
    assert "TEST001" not in json.dumps(report)
    # A subsequent changed source withdraws exact membership through the same watcher path.
    (folder / "PKG.001").write_bytes((folder / "PKG.002").read_bytes())
    changed = build(tmp_path)["owner_confirmed_source_membership"]
    assert changed["total"]["claims_exactly_bound"] == 0


def test_unverified_owner_cannot_promote(tmp_path):
    private = tmp_path / "evaluation_results/qualification_closure"
    private.mkdir(parents=True)
    docs = tmp_path / "docs/qualification"
    docs.mkdir(parents=True)
    (docs / "source_owner_confirmation.json").write_text('{"status":"PENDING_OWNER_CONFIRMATION"}')
    (private / "owner_sequence_input.local.json").write_text("{}")
    result = refresh(tmp_path, [])
    assert result["validation_error"] == "OWNER_CONFIRMATION_INVALID"
    assert not result["membership_usable"]
