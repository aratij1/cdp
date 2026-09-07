"""Validate owner-authorized source occurrences separately from scoring eligibility."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml  # type: ignore[import-untyped]
from PIL import Image

from evaluation.claim_inventory import _publish

METHOD = "SOURCE_OWNER_CONFIRMED_SEQUENCE + GOVERNED_CONTROL_NUMBER"
RULE = "SOURCE_IMAGE_SEQUENCE_MATCHES_DATAMATICS_CLAIM_SEQUENCE"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(path: Path) -> list[dict]:
    """Read data tables only; spreadsheet prose never grants authority."""
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [
                "".join(node.itertext())
                for node in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", NS)
            ]
        tables = []
        for name in archive.namelist():
            if not re.fullmatch(r"xl/worksheets/sheet[0-9]+.xml", name):
                continue
            rows = []
            for row in ET.fromstring(archive.read(name)).findall(".//m:sheetData/m:row", NS):
                values = {}
                for cell in row:
                    column = re.sub(r"[0-9]", "", cell.attrib["r"])
                    value, inline = cell.find("m:v", NS), cell.find("m:is", NS)
                    text = (
                        value.text or ""
                        if value is not None
                        else ("".join(inline.itertext()) if inline is not None else "")
                    )
                    if cell.find("m:f", NS) is not None:
                        raise ValueError("FORMULA_IN_GOVERNED_WORKBOOK")
                    values[column] = strings[int(text)] if cell.get("t") == "s" else text
                rows.append(values)
            if rows and "group" in rows[0].values() and "source_sha256" in rows[0].values():
                tables.append(
                    [
                        {header: row.get(col, "") for col, header in rows[0].items()}
                        for row in rows[1:]
                        if row.get("A")
                    ]
                )
        if len(tables) != 1:
            raise ValueError("UNIQUE_GOVERNED_TABLE_REQUIRED")
        return tables[0]


def parse_claims(text: str, schemas: dict, form: str, optional_91: bool) -> list[dict]:
    """Use spec offsets and validate every claim record, retaining failed occurrences."""
    ub = form == "UB"
    start, end, width = ("20", "91", 2) if ub else ("CA0", "XA0", 3)
    envelopes = {"01", "10", "95", "99"} if ub else {"AA0", "BA0", "BA1", "YA0", "ZA0"}
    claims: list[dict] = []
    current: dict | None = None
    global_issues: set[str] = set()

    def close() -> None:
        nonlocal current
        if current is not None:
            valid_end = current["record_types"][-1] == end or (
                ub and optional_91 and current["record_types"][-1] == "90"
            )
            if not valid_end:
                current["issues"].add("CLAIM_TERMINATOR_MISSING")
            current["issues"] = sorted(current["issues"])
            claims.append(current)
            current = None

    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            global_issues.add("EMPTY_OUTPUT_RECORD")
            continue
        record = line[:width]
        schema = schemas.get(record)
        if schema is None or len(line) != schema.get("record_length"):
            global_issues.add("UNKNOWN_OR_INVALID_LENGTH_RECORD")
        if record == start:
            close()
            current = {
                "control": "",
                "record_types": [],
                "start_line": line_number,
                "end_line": line_number,
                "issues": set(),
            }
        elif record in envelopes:
            close()
            continue
        elif current is None:
            global_issues.add("ORPHAN_CLAIM_RECORD")
            continue
        if current is not None:
            current["record_types"].append(record)
            current["end_line"] = line_number
            controls = [
                field
                for field in (schema or {}).get("fields", [])
                if field.get("canonical_name") == "patient_control_number"
            ]
            if len(controls) != 1:
                current["issues"].add("CONTROL_SPEC_REQUIRED")
            else:
                field = controls[0]
                value = line[field["start_position"] - 1 : field["end_position"]].strip()
                if not value:
                    current["issues"].add("CONTROL_NUMBER_MISSING")
                if record == start:
                    current["control"] = value
                elif value != current["control"]:
                    current["issues"].add("CONTROL_NUMBER_INCONSISTENT")
            if (
                ub
                and record == "91"
                and (len(current["record_types"]) < 2 or current["record_types"][-2] != "90")
            ):
                current["issues"].add("UB_CLAIM_CONTROL_RECORD_MISSING")
            if record == end:
                close()
    close()
    for claim in claims:
        claim["issues"] = sorted(set(claim["issues"]) | global_issues)
    return claims


def validate_group(rows: list[dict], folder: Path, schemas: dict, optional_91: bool) -> dict:
    issues: set[str] = set()
    images: list[dict] = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() not in {".txt", ".json", ".csv"}:
            try:
                with Image.open(path) as source_image:
                    images.append(
                        {
                            "path": path,
                            "sha256": digest(path),
                            "frames": getattr(source_image, "n_frames", 1),
                        }
                    )
            except OSError:
                issues.add("UNREADABLE_SOURCE_IMAGE")
    hashes = Counter(image["sha256"] for image in images)
    if any(count != 1 for count in hashes.values()):
        issues.add("DUPLICATE_IMAGE_HASH")
    declared = Counter(row["source_sha256"] for row in rows)
    if declared != hashes:
        issues.add("SOURCE_HASH_SET_MISMATCH")
    if any(count != 1 for count in declared.values()):
        issues.add("DUPLICATE_MANIFEST_IMAGE")
    # Workbook sequence is table order across packages; source_page_number is package-local.
    positions = [(row["package_id"], int(row["source_page_number"])) for row in rows]
    if len(set(positions)) != len(positions):
        issues.add("DUPLICATE_SEQUENCE_POSITION")
    for package in {p for p, _ in positions}:
        seq = [i for p, i in positions if p == package]
        if seq != list(range(1, len(seq) + 1)):
            issues.add("MISSING_OR_REORDERED_SEQUENCE_POSITION")
    for key in ("claim_id", "document_id", "page_id"):
        if len({row[key] for row in rows}) != len(rows) or any(not row[key] for row in rows):
            issues.add("DUPLICATE_OR_MISSING_MANIFEST_ID")
    output_names = {row["output_text_file"] for row in rows}
    outputs = list(folder.glob("*.txt"))
    if len(output_names) != 1 or len(outputs) != 1 or outputs[0].name not in output_names:
        issues.add("UNIQUE_OUTPUT_FILE_REQUIRED")
        parsed = []
    else:
        parsed = parse_claims(
            outputs[0].read_text(encoding="utf-8-sig"),
            schemas,
            "UB" if rows[0]["group"] == "Group C" else "NSF",
            optional_91,
        )
    if len(images) != len(parsed) or len(rows) != len(parsed):
        issues.add("IMAGE_CLAIM_MANIFEST_COUNT_MISMATCH")
    byhash = {image["sha256"]: image for image in images}
    mappings = []
    for index, row in enumerate(rows):
        errors = set(issues)
        image = byhash.get(row["source_sha256"])
        claim = parsed[index] if index < len(parsed) else None
        if image is None:
            errors.add("SOURCE_IMAGE_MISSING_OR_CHANGED")
        else:
            # A .tif/.tiff presentation suffix may differ, only with identical sealed bytes.
            source_name = re.sub(r"\.tiff?$", "", row["source_file_name"], flags=re.IGNORECASE)
            if source_name != image["path"].name:
                errors.add("SOURCE_FILENAME_SEQUENCE_MISMATCH")
            suffix = image["path"].suffix[1:]
            if not suffix.isdigit() or int(suffix) != int(row["source_page_number"]):
                errors.add("SOURCE_SEQUENCE_MISMATCH")
            if image["path"].stem != row["package_id"]:
                errors.add("SOURCE_PACKAGE_MISMATCH")
        if claim is None:
            errors.add("OUTPUT_CLAIM_MISSING")
        else:
            errors.update(claim["issues"])
            if claim["control"] != row["source_record_id"].strip():
                errors.add("WORKBOOK_CONTROL_MISMATCH")
        mappings.append(
            {
                **row,
                "source_control_reference": claim["control"] if claim else None,
                "source_frame_count": image["frames"] if image else None,
                "actual_source_path": str(image["path"]) if image else None,
                "output_claim_sequence": index + 1,
                "output_record_start": claim["start_line"] if claim else None,
                "output_record_end": claim["end_line"] if claim else None,
                "membership_status": "EXACT"
                if not errors
                else ("UNBOUND" if image is None or claim is None else "AMBIGUOUS"),
                "validation_result": sorted(errors),
                "mapping_method": METHOD,
                "mapping_version": "owner-sequence-v1",
                "verified_by": "Ashish Singh",
                "verified_date": "2026-09-07",
            }
        )
    states = Counter(row["membership_status"] for row in mappings)
    return {
        "images": len(images),
        "output_claims": len(parsed),
        "source_frames": sum(image["frames"] for image in images),
        "packages": len({row["package_id"] for row in rows}),
        "claims_discovered": len(rows),
        "claims_exactly_bound": states["EXACT"],
        "claims_ambiguous": states["AMBIGUOUS"],
        "claims_unbound": states["UNBOUND"],
        "issues": dict(Counter(error for row in mappings for error in row["validation_result"])),
        "mappings": mappings,
    }


def refresh(root: Path, bindings: list[dict]) -> dict:
    private = root / "evaluation_results/qualification_closure"
    config_path = private / "owner_sequence_input.local.json"
    if not config_path.exists():
        return {}
    confirmation = {}
    try:
        config = json.loads(config_path.read_text())
        confirmation_path = root / "docs/qualification/source_owner_confirmation.json"
        confirmation = json.loads(confirmation_path.read_text())
        if (
            confirmation.get("status") != "OWNER_CONFIRMED"
            or confirmation.get("mapping_rule") != RULE
            or confirmation.get("owner_name") != "Ashish Singh"
        ):
            raise ValueError("OWNER_CONFIRMATION_INVALID")
        seals = config["sealed_inputs"]
        if str(confirmation_path) not in seals:
            raise ValueError("OWNER_CONFIRMATION_SEAL_REQUIRED")
        if any(
            not Path(path).is_file() or digest(Path(path)) != value for path, value in seals.items()
        ):
            raise ValueError("GOVERNED_INPUT_HASH_CHANGED")
        workbook = Path(config["workbook"])
        if str(workbook) not in seals:
            raise ValueError("WORKBOOK_SEAL_REQUIRED")
        rows = read_manifest(workbook)
        if {row["group"] for row in rows} != set(confirmation["dataset_scope"]):
            raise ValueError("OWNER_SCOPE_MISMATCH")
        if len({row["source_sha256"] for row in rows}) != len(rows):
            raise ValueError("DUPLICATE_SOURCE_HASH_ACROSS_GROUPS")
        if len({row["claim_id"] for row in rows}) != len(rows):
            raise ValueError("DUPLICATE_CLAIM_ID_ACROSS_GROUPS")
        groups, private_rows = {}, []
        for group in confirmation["dataset_scope"]:
            fmt = "ub92" if group == "Group C" else "nsf"
            paths = list((root / "config/output_specs" / fmt / "compiled").glob("*.yaml"))
            if not paths or any(str(path) not in seals for path in paths):
                raise ValueError("SPECIFICATION_SEAL_REQUIRED")
            schemas = {
                path.stem: yaml.safe_load(path.read_text(encoding="utf-8")) for path in paths
            }
            folder = Path(config["dataset_root"]) / group
            if any(str(path) not in seals for path in folder.glob("*.txt")):
                raise ValueError("OUTPUT_SEAL_REQUIRED")
            result = validate_group(
                [row for row in rows if row["group"] == group],
                folder,
                schemas,
                confirmation.get("ub_record_91_optional") is True,
            )
            private_rows.extend(result.pop("mappings"))
            groups[group] = result
        for row in private_rows:
            row["source_page_numbers"] = list(range(1, (row["source_frame_count"] or 0) + 1))
            row["cdp_page_bindings"] = [
                {
                    "source_page_id": b["source_page_id"],
                    "cdp_page_id": b.get("cdp_page_id"),
                    "source_page_index": b.get("source_page_index"),
                }
                for b in bindings
                if b.get("source_asset_sha256") == row["source_sha256"]
            ]
        exact_hashes = {
            row["source_sha256"] for row in private_rows if row["membership_status"] == "EXACT"
        }
        all_hashes = {row["source_sha256"] for row in private_rows}
        covered = [
            b
            for b in bindings
            if b.get("source_asset_sha256") in exact_hashes and b.get("state") == "EXACT"
        ]
        # File-level lineage does not certify frame roles or complete prediction/execution joins.
        total = {
            key: sum(group[key] for group in groups.values())
            for key in (
                "images",
                "output_claims",
                "source_frames",
                "packages",
                "claims_discovered",
                "claims_exactly_bound",
                "claims_ambiguous",
                "claims_unbound",
            )
        }
        total["binding_coverage"] = (
            total["claims_exactly_bound"] / total["claims_discovered"]
            if total["claims_discovered"]
            else None
        )
        report = {
            "status": "CLAIM_MEMBERSHIP_ESTABLISHED"
            if total["binding_coverage"] == 1
            else "PARTIAL_MEMBERSHIP",
            "scope": "OWNER_CONFIRMED_GROUPS_A_D_SOURCE_OCCURRENCES",
            "groups": groups,
            "total": total,
            "field_truth_created": False,
            "cohort": {
                "review_pages": len(bindings),
                "page_binding_exact": sum(b.get("state") == "EXACT" for b in bindings),
                "claim_membership_exact": len(covered),
                "claim_membership_ambiguous": sum(
                    b.get("source_asset_sha256") in all_hashes - exact_hashes for b in bindings
                ),
                "claim_membership_unavailable": len(bindings) - len(covered),
            },
            "claims": [
                {
                    "claim_id_sha256": hashlib.sha256(row["claim_id"].encode()).hexdigest(),
                    "group": row["group"],
                    "membership_status": row["membership_status"],
                    "source_frames": row["source_frame_count"],
                    "validation_result": row["validation_result"],
                    "mapping_method": METHOD,
                }
                for row in private_rows
            ],
        }
        _publish(
            private / "owner_sequence_membership.local.json",
            {
                "governed": True,
                "scope": confirmation["dataset_scope"],
                "mapping_method": METHOD,
                "mappings": private_rows,
            },
        )
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile) as exc:
        report = {
            "status": "PARTIAL_MEMBERSHIP",
            "validation_error": str(exc)
            if re.fullmatch(r"[A-Z_]+", str(exc))
            else "GOVERNED_INPUT_UNREADABLE",
            "membership_usable": False,
        }
        _publish(
            private / "owner_sequence_membership.local.json", {"governed": False, "mappings": []}
        )
    _publish(root / "evaluation_results/real_release/source_owner_confirmation.json", confirmation)
    _publish(root / "evaluation_results/real_release/source_claim_membership_report.json", report)
    return report
