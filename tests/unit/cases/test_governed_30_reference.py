"""Synthetic-only regression checks for governed engineering references."""

from pathlib import Path

import pytest

from evaluation.governed_30_reference import (
    AUTHORITY,
    ROOT,
    catalog,
    freeze,
    load_schemas,
    normalize,
    parse_reference,
)


def record(form, record_type, values):
    schema = load_schemas(ROOT, form)[record_type]
    chars = list(" " * schema["record_length"])
    chars[: len(record_type)] = record_type
    for name, value in values.items():
        spec = next(f for f in schema["fields"] if f["canonical_name"] == name)
        width = spec["end_position"] - spec["start_position"] + 1
        chars[spec["start_position"] - 1 : spec["end_position"]] = value.ljust(width)
    return "".join(chars)


def parse(form, lines):
    schemas = load_schemas(ROOT, form)
    return parse_reference(
        lines,
        catalog(schemas, form),
        schemas,
        source_hash="a" * 64,
        claim_alias="synthetic_claim",
        start_line=10,
    )


def test_name_composite_and_provenance_do_not_use_patient_control():
    result = parse(
        "CMS1500",
        [
            record(
                "CMS1500",
                "CA0",
                {
                    "patient_first_name": "JANE",
                    "patient_middle_initial": "Q",
                    "patient_last_name": "EXAMPLE",
                    "patient_control_number": "PRIVATE_CONTROL",
                },
            )
        ],
    )["patient_name"]
    assert result["value"] == "JANE Q EXAMPLE"
    assert result["authority"] == AUTHORITY
    assert result["provenance"][0]["line_number"] == 10
    assert "PRIVATE_CONTROL" not in str(result)


def test_conflicting_insured_occurrences_remain_ambiguous():
    lines = [
        record("CMS1500", "DA0", {"insured_identification_number": value})
        for value in ("SYNTH_A", "SYNTH_B")
    ]
    result = parse("CMS1500", lines)["member_id"]
    assert result["status"] == "REFERENCE_AMBIGUOUS"
    assert "value" not in result
    assert len(result["provenance"]) == 2


def test_blank_and_missing_are_not_source_blank_truth():
    fields = parse("CMS1500", [record("CMS1500", "CA0", {})])
    assert fields["patient_name"]["status"] == "REFERENCE_NOT_AVAILABLE"
    assert fields["member_id"]["status"] == "REFERENCE_NOT_AVAILABLE"
    assert all("value" not in f for f in fields.values())


def test_truncated_record_never_produces_reference():
    fields = parse("CMS1500", ["CA0   BROKEN"])
    assert fields["patient_name"]["status"] == "NOT_COMPARABLE"
    assert "value" not in fields["patient_name"]


def test_date_spec_formats_are_distinct_and_strict():
    assert normalize(["02292024"], "MMDDCCYY") == "2024-02-29"
    assert normalize(["20240229"], "CCYYMMDD") == "2024-02-29"
    with pytest.raises(ValueError):
        normalize(["02292023"], "MMDDCCYY")
    fields = parse("CMS1500", [record("CMS1500", "CA0", {"patient_date_of_birth": "20240101"})])
    assert fields["patient_dob"]["status"] == "NOT_COMPARABLE"


def test_money_implied_cents_summed_only_from_explicit_totals():
    assert normalize(["0001234"], "implied_cents") == "12.34"
    assert normalize(["0000012345", "0000000067"], "sum_implied_cents") == "124.12"
    with pytest.raises(ValueError):
        normalize(["00000123J"], "implied_cents")
    fields = parse(
        "UB",
        [
            record(
                "UB",
                "90",
                {
                    "total_accommodation_charges_revenue": "0000012345",
                    "total_ancillary_charges_revenue_centers": "0000000067",
                },
            )
        ],
    )
    assert fields["total_charge"]["value"] == "124.12"


def test_ub_principal_diagnosis_is_explicit_nsf_first_diagnosis_is_not():
    ub = parse("UB", [record("UB", "70", {"principal_diagnosis_code": "Z00.00"})])
    assert ub["principal_diagnosis"]["value"] == "Z0000"
    nsf = parse("CMS1500", [record("CMS1500", "EA0", {"diagnosis_code_1": "Z0000"})])
    assert nsf["principal_diagnosis"]["status"] == "NOT_COMPARABLE"


def test_immutable_freeze_accepts_same_content_and_rejects_drift(tmp_path: Path):
    path = tmp_path / "manifest.json"
    freeze(path, {"cohort": "synthetic"})
    original = path.read_bytes()
    freeze(path, {"cohort": "synthetic"})
    with pytest.raises(ValueError, match="IMMUTABLE_GOVERNED_COHORT_DRIFT"):
        freeze(path, {"cohort": "different"})
    assert path.read_bytes() == original
