"""Independent literal-offset goldens transcribed from governed NSF/UB specifications."""

import pytest

from evaluation.governed_30_reference import ROOT, catalog, load_schemas, parse_reference


def parse(form, record, slots):
    schemas = load_schemas(ROOT, form)
    chars = list(" " * schemas[record]["record_length"])
    chars[: len(record)] = record
    for start, end, value in slots:
        assert len(value) <= end - start + 1
        chars[start - 1 : end] = value.ljust(end - start + 1)
    return parse_reference(
        ["".join(chars)],
        catalog(schemas, form),
        schemas,
        source_hash="f" * 64,
        claim_alias="SYNTHETIC",
        start_line=101,
    )


@pytest.mark.parametrize(
    "form,record,field,slots,expected",
    [
        ("CMS1500", "DA0", "member_id", [(157, 181, "000SYNTHETIC99")], "000SYNTHETIC99"),
        (
            "CMS1500",
            "CA0",
            "patient_name",
            [(23, 42, "EXAMPLE"), (43, 54, "ALPHA"), (55, 55, "Q")],
            "ALPHA Q EXAMPLE",
        ),
        (
            "CMS1500",
            "DA0",
            "insured_name",
            [(182, 201, "SAMPLE"), (202, 213, "BETA"), (214, 214, "R")],
            "BETA R SAMPLE",
        ),
        ("CMS1500", "XA0", "total_charge", [(78, 84, "0034789")], "347.89"),
        ("UB", "30", "member_id", [(35, 53, "000SYNTHETIC88")], "000SYNTHETIC88"),
        (
            "UB",
            "20",
            "patient_name",
            [(25, 44, "EXAMPLE"), (45, 53, "ALPHA"), (54, 54, "Q")],
            "ALPHA Q EXAMPLE",
        ),
        (
            "UB",
            "30",
            "insured_name",
            [(111, 130, "SAMPLE"), (131, 139, "BETA"), (140, 140, "R")],
            "BETA R SAMPLE",
        ),
        ("UB", "20", "patient_dob", [(56, 63, "02292024")], "2024-02-29"),
        ("UB", "20", "service_date", [(133, 140, "20240229")], "2024-02-29"),
        ("UB", "70", "principal_diagnosis", [(25, 31, "Z00.00")], "Z0000"),
        (
            "UB",
            "90",
            "total_charge",
            [(43, 52, "0000034789"), (53, 62, "9999999999"), (63, 72, "0000000075")],
            "348.64",
        ),
    ],
)
def test_literal_spec_positions(form, record, field, slots, expected):
    result = parse(form, record, slots)[field]
    assert result["status"] == "REFERENCE_AVAILABLE"
    assert result["value"] == expected
    assert result["provenance"][0]["line_number"] == 101


def test_patient_and_insured_names_remain_distinct():
    result = parse(
        "CMS1500",
        "DA0",
        [
            (6, 22, "SYNTH_CONTROL"),
            (157, 181, "SYNTH_MEMBER"),
            (182, 201, "INSURED"),
            (202, 213, "EXAMPLE"),
        ],
    )
    assert result["insured_name"]["value"] == "EXAMPLE INSURED"
    assert result["member_id"]["value"] == "SYNTH_MEMBER"
    assert result["patient_name"]["status"] == "REFERENCE_NOT_AVAILABLE"


@pytest.mark.parametrize("value", ["000000123J", "0000012.34", "          "])
def test_ub_unestablished_sign_decimal_or_partial_blank_rejected(value):
    result = parse("UB", "90", [(43, 52, value), (63, 72, "0000000075")])["total_charge"]
    assert result["status"] == "NOT_COMPARABLE"
    assert "value" not in result


def test_zero_currency_is_numeric_but_blank_does_not_prove_source_blank():
    assert parse("CMS1500", "XA0", [(78, 84, "0000000")])["total_charge"]["value"] == "0.00"
    result = parse("CMS1500", "XA0", [])["total_charge"]
    assert result["status"] == "REFERENCE_NOT_AVAILABLE"
    assert "value" not in result


def test_date_zero_fill_is_invalid_not_source_blank():
    result = parse("UB", "20", [(56, 63, "00000000")])["patient_dob"]
    assert result["status"] == "NOT_COMPARABLE"
    assert "value" not in result


def test_continuation_record_does_not_replace_insurance_header():
    schemas = load_schemas(ROOT, "UB")
    fields = parse_reference(
        ["31" + " " * (schemas["31"]["record_length"] - 2)],
        catalog(schemas, "UB"),
        schemas,
        source_hash="f" * 64,
        claim_alias="SYNTHETIC",
    )
    assert fields["insured_name"]["status"] == "REFERENCE_NOT_AVAILABLE"
