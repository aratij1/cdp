"""Sealed fixed-width engineering references; never blind human truth."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from PIL import Image

from packages.real_data_evaluation.blind_workflow import FIELDS

PARSER_VERSION = "governed-reference-v1"
AUTHORITY = "ENGINEERING_REFERENCE_ONLY"
ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


# Explicit semantic choices. Format omissions remain non-comparable.
MAPPINGS = {
    "CMS1500": {
        "member_id": ("DA0", ["insured_identification_number"], "text"),
        "patient_name": (
            "CA0",
            ["patient_first_name", "patient_middle_initial", "patient_last_name"],
            "name",
        ),
        "insured_name": (
            "DA0",
            ["insured_first_name", "insured_middle_initial", "insured_last_name"],
            "name",
        ),
        "patient_dob": ("CA0", ["patient_date_of_birth"], "date_format_missing"),
        "service_date": ("FA0", ["service_from_date"], "date_format_missing"),
        "total_charge": ("XA0", ["total_claim_charges"], "implied_cents"),
        "provider_name": ("BA0", ["provider_organization_name"], "provider_role_ambiguous"),
        "principal_diagnosis": ("EA0", ["diagnosis_code_1"], "principal_semantics_unestablished"),
    },
    "UB": {
        "member_id": ("30", ["certificate_ssn_health_insurance"], "text"),
        "patient_name": (
            "20",
            ["patient_first_name", "patient_middle_initial", "patient_last_name"],
            "name",
        ),
        "insured_name": (
            "30",
            ["insured_s_first_name", "insured_s_middle_initial", "insured_s_last_name"],
            "name",
        ),
        "patient_dob": ("20", ["patient_birthdate"], "MMDDCCYY"),
        "service_date": ("20", ["statement_covers_period_from_date"], "CCYYMMDD"),
        "total_charge": (
            "90",
            ["total_accommodation_charges_revenue", "total_ancillary_charges_revenue_centers"],
            "sum_implied_cents",
        ),
        "provider_name": ("10", ["provider_name"], "provider_role_ambiguous"),
        "principal_diagnosis": ("70", ["principal_diagnosis_code"], "diagnosis"),
    },
}
NON_COMPARABLE = {
    "date_format_missing",
    "provider_role_ambiguous",
    "principal_semantics_unestablished",
}


def load_schemas(root: Path, form: str) -> dict:
    folder = root / "config/output_specs" / ("ub92" if form == "UB" else "nsf") / "compiled"
    return {
        p.stem: yaml.safe_load(p.read_text(encoding="utf8")) for p in sorted(folder.glob("*.yaml"))
    }


def catalog(schemas: dict, form: str) -> list[dict]:
    result = []
    for field in FIELDS:
        record, names, normalization = MAPPINGS[form][field]
        positions = []
        for name in names:
            matches = [
                f
                for f in schemas.get(record, {}).get("fields", [])
                if f.get("canonical_name") == name
            ]
            if len(matches) != 1:
                raise ValueError("UNIQUE_SPEC_FIELD_REQUIRED")
            f = matches[0]
            positions.append(
                {
                    "canonical_name": name,
                    "start": f["start_position"],
                    "end": f["end_position"],
                    "picture": f["cobol_picture"],
                }
            )
        result.append(
            {
                "cdp_field": field,
                "source_record": record,
                "positions": positions,
                "normalization": normalization,
                "authority": AUTHORITY,
                "status": "NOT_COMPARABLE"
                if normalization in NON_COMPARABLE
                else "REFERENCE_AVAILABLE",
            }
        )
    return result


def normalize(parts: list[str], method: str) -> str:
    if method in {"text", "name"}:
        return " ".join(" ".join(p.split()) for p in parts if p.strip()).upper()
    if method == "diagnosis":
        return parts[0].strip().replace(".", "").upper()
    if method in {"CCYYMMDD", "MMDDCCYY"}:
        return (
            datetime.strptime(parts[0].strip(), "%Y%m%d" if method == "CCYYMMDD" else "%m%d%Y")
            .replace(tzinfo=UTC)
            .strftime("%Y-%m-%d")
        )
    if method in {"implied_cents", "sum_implied_cents"}:
        # Unsupported overpunch is rejected rather than guessing sign encoding.
        if not all(re.fullmatch(r"[+-]?[0-9]+", p.strip()) for p in parts):
            raise ValueError("UNSUPPORTED_MONETARY_ENCODING")
        return str(
            sum((Decimal(p.strip()) / 100 for p in parts), Decimal(0)).quantize(Decimal("0.01"))
        )
    raise ValueError("NORMALIZATION_NOT_ESTABLISHED")


def parse_reference(
    lines: list[str],
    mapping: list[dict],
    schemas: dict,
    *,
    source_hash: str,
    claim_alias: str,
    start_line: int = 1,
) -> dict:
    """Return private values, preserving conflicting record occurrences as ambiguity."""
    fields = {}
    for rule in mapping:
        record = rule["source_record"]
        occurrences = [
            (start_line + i, line) for i, line in enumerate(lines) if line.startswith(record)
        ]
        provenance = [
            {
                "source_file_hash": source_hash,
                "claim_control_alias": claim_alias,
                "record_type": record,
                "line_number": number,
                "positions": rule["positions"],
                "parser_version": PARSER_VERSION,
            }
            for number, _ in occurrences
        ]
        entry = {
            "status": rule["status"],
            "authority": AUTHORITY,
            "provenance": provenance,
            "normalization": rule["normalization"],
        }
        if not occurrences:
            entry["status"] = "REFERENCE_NOT_AVAILABLE"
        elif rule["status"] != "NOT_COMPARABLE":
            values: list[str | None] = []
            malformed = False
            for _, line in occurrences:
                parts = [line[p["start"] - 1 : p["end"]] for p in rule["positions"]]
                if len(line) != schemas[record]["record_length"]:
                    malformed = True
                    continue
                if not any(p.strip() for p in parts):
                    values.append(None)
                    continue
                try:
                    values.append(normalize(parts, rule["normalization"]))
                except ValueError:
                    malformed = True
            if malformed:
                entry["status"] = "NOT_COMPARABLE"
                entry["reason"] = "INVALID_REFERENCE_ENCODING"
            elif len(set(values)) > 1:
                entry["status"] = "REFERENCE_AMBIGUOUS"
            elif not values or values[0] is None:
                entry["status"] = "REFERENCE_NOT_AVAILABLE"
                entry["reason"] = "BLANK_OUTPUT_DOES_NOT_PROVE_SOURCE_BLANK"
            else:
                entry["value"] = values[0]
        fields[rule["cdp_field"]] = entry
    return fields


def freeze(path: Path, payload: dict) -> None:
    """Create once, accept identical replays, reject drift."""
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf8") as stream:
            stream.write(data)
    except FileExistsError:
        if json.loads(path.read_text(encoding="utf8")) != payload:
            raise ValueError("IMMUTABLE_GOVERNED_COHORT_DRIFT")


def build(root: Path = ROOT) -> dict:
    private = root / "evaluation_results/qualification_closure"
    inputs = json.loads((private / "owner_sequence_input.local.json").read_text(encoding="utf8"))
    membership_path = private / "owner_sequence_membership.local.json"
    membership = json.loads(membership_path.read_text(encoding="utf8"))
    rows = membership.get("mappings", [])
    if (
        membership.get("governed") is not True
        or len(rows) != 30
        or any(r.get("membership_status") != "EXACT" for r in rows)
    ):
        raise ValueError("THIRTY_GOVERNED_EXACT_CLAIMS_REQUIRED")
    for name, expected in inputs["sealed_inputs"].items():
        if digest(Path(name)) != expected:
            raise ValueError("GOVERNED_INPUT_SEAL_MISMATCH")
    owner_path = root / "docs/qualification/source_owner_confirmation.json"
    owner = json.loads(owner_path.read_text(encoding="utf8"))
    if owner.get("status") != "OWNER_CONFIRMED":
        raise ValueError("OWNER_CONFIRMATION_REQUIRED")
    schemas = {form: load_schemas(root, form) for form in MAPPINGS}
    catalogs = {form: catalog(schemas[form], form) for form in MAPPINGS}
    manifest_claims, references = [], []
    aliases = set()
    for row in rows:
        alias = row["claim_id"]
        if alias in aliases or not alias.startswith("CLM_"):
            raise ValueError("UNIQUE_CLAIM_ALIAS_REQUIRED")
        aliases.add(alias)
        source = Path(row["actual_source_path"])
        if digest(source) != row["source_sha256"]:
            raise ValueError("SOURCE_SEAL_MISMATCH")
        with Image.open(source) as image:
            frames = getattr(image, "n_frames", 1)
        if frames != row["source_frame_count"] or row["source_page_numbers"] != list(
            range(1, frames + 1)
        ):
            raise ValueError("COMPLETE_FRAME_MEMBERSHIP_REQUIRED")
        form = "UB" if row["claim_form_type"] in {"UB", "UB04"} else "CMS1500"
        output = source.parent / row["output_text_file"]
        output_hash = digest(output)
        if inputs["sealed_inputs"].get(str(output)) != output_hash:
            raise ValueError("SEALED_OUTPUT_REQUIRED")
        start, end = row["output_record_start"], row["output_record_end"]
        lines = output.read_text(encoding="utf-8-sig").splitlines()[start - 1 : end]
        valid_end = bool(lines) and (
            lines[-1].startswith(row["claim_record_end"])
            or (
                form == "UB"
                and owner.get("ub_record_91_optional") is True
                and lines[-1].startswith("90")
            )
        )
        if not lines or not lines[0].startswith(row["claim_record_start"]) or not valid_end:
            raise ValueError("GOVERNED_RECORD_BOUNDARY_MISMATCH")
        control_spec = next(
            f
            for f in schemas[form][row["claim_record_start"]]["fields"]
            if f["canonical_name"] == "patient_control_number"
        )
        if (
            lines[0][control_spec["start_position"] - 1 : control_spec["end_position"]].strip()
            != row["source_control_reference"]
        ):
            raise ValueError("CONTROL_REFERENCE_MISMATCH")
        manifest_claims.append(
            {
                "claim_alias": alias,
                "package_hash": seal(row["package_id"]),
                "source_hash": row["source_sha256"],
                "source_file_alias": "source_" + row["source_sha256"][:16],
                "form_type": form,
                "pages": [
                    {"page_alias": f"{alias}_FRAME_{frame:03d}", "frame_index": frame - 1}
                    for frame in range(1, frames + 1)
                ],
                "membership_status": "EXACT",
                "membership_provenance": seal(
                    {"method": membership["mapping_method"], "version": row["mapping_version"]}
                ),
                "owner_confirmation_provenance": digest(owner_path),
                "output_provenance": {
                    "source_file_hash": output_hash,
                    "start_line": start,
                    "end_line": end,
                },
            }
        )
        references.append(
            {
                "claim_alias": alias,
                "form_type": form,
                "fields": parse_reference(
                    lines,
                    catalogs[form],
                    schemas[form],
                    source_hash=output_hash,
                    claim_alias=alias,
                    start_line=start,
                ),
            }
        )
    payload = {
        "schema_version": 1,
        "cohort": "governed_30",
        "authority": AUTHORITY,
        "claims": manifest_claims,
        "membership_input_sha256": digest(membership_path),
        "input_provenance_seals": sorted(inputs["sealed_inputs"].values()),
    }
    payload["cohort_hash"] = seal(payload)
    out = root / "evaluation_results/real_release"
    freeze(out / "governed_30_manifest.json", payload)
    private_result = {
        "cohort_hash": payload["cohort_hash"],
        "parser_version": PARSER_VERSION,
        "authority": AUTHORITY,
        "claims": references,
    }
    freeze(private / "governed_30_reference.local.json", private_result)
    summary = {
        "cohort_hash": payload["cohort_hash"],
        "claims": len(rows),
        "frames": sum(len(c["pages"]) for c in manifest_claims),
        "authority": AUTHORITY,
        "mapping_catalog": catalogs,
        "reference_status_counts": dict(
            Counter(f["status"] for c in references for f in c["fields"].values())
        ),
    }
    freeze(out / "governed_30_reference_catalog.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
