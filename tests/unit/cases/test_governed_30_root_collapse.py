"""Synthetic safety contracts for the root-cause collapse experiment."""

import hashlib
from dataclasses import asdict

import pytest
from PIL import Image

from evaluation.governed_30_root_collapse import CAUSES, classify, secondary_allowed
from evaluation.root_collapse_capture import capture_reviewed_rotation, validate_rotation_job
from packages.claim_intelligence.normalization import comparison_key
from workers.field_candidates.bounded_geometry_recovery import (
    generate_birthdate,
    generate_geometry,
    source_last_first_label,
)
from workers.page_detection.text_extraction import TextLine


def t(text, x0, y0, x1, y1):
    return TextLine(text, x0, y0, x1, y1, 0.9)


def test_compound_date_anchor_assembles_only_observed_digits():
    tokens = [
        t("10 BIRTHDATE", 10, 10, 100, 30),
        t("11 SEX", 160, 10, 200, 30),
        t("02292000", 15, 35, 145, 55),
    ]
    result = generate_birthdate(tokens, width=1000, height=1000)
    assert [c.value for c in result] == ["2000-02-29"]
    assert all(c.review_only for c in result)
    assert tokens[-1].text == "02292000"


@pytest.mark.parametrize("date_text", ["02292001", "02C92000", "022900", "02292000 EXTRA"])
def test_date_does_not_repair_characters_or_infer_century(date_text):
    tokens = [
        t("10 BIRTHDATE", 10, 10, 100, 30),
        t("11 SEX", 160, 10, 200, 30),
        t(date_text, 15, 35, 145, 55),
    ]
    assert not generate_birthdate(tokens, width=1000, height=1000)


def test_date_requires_independent_neighbor_and_correct_topology():
    date = t("01012000", 15, 35, 145, 55)
    assert not generate_birthdate(
        [t("10 BIRTHDATE", 10, 10, 100, 30), date], width=1000, height=1000
    )
    assert not generate_birthdate(
        [t("10 EMPLOYMENT", 10, 10, 120, 30), t("11 SEX", 160, 10, 200, 30), date],
        width=1000,
        height=1000,
    )


def test_receipt_total_same_row_has_bounded_distance():
    result = generate_geometry(
        [t("TOTAL", 10, 10, 90, 30), t("123.45", 110, 10, 200, 30), t("999.99", 700, 10, 790, 30)],
        width=1000,
        height=1000,
    )
    assert any(c.value == "123.45" for c in result)
    assert all(c.value != "999.99" for c in result)
    assert all("accepted" not in asdict(c) and c.review_only for c in result)


def test_charge_column_header_does_not_make_service_line_a_total():
    result = generate_geometry(
        [
            t("TOTAL CHARGES", 100, 10, 220, 30),
            t("HCPCS", 10, 10, 80, 30),
            t("123.45", 110, 40, 190, 60),
        ],
        width=1000,
        height=1000,
    )
    assert not any(c.field_name == "total_charge" for c in result)


def test_name_order_requires_two_explicit_ordered_source_instructions():
    assert source_last_first_label("PATIENT NAME Last Name First Name")
    assert not source_last_first_label("PATIENT NAME Las1 Name Firs1 Name")
    assert not source_last_first_label("PATIENT NAME")
    assert not source_last_first_label("First Name Last Name")


def test_reference_abbreviation_and_identifier_rules_stay_strict():
    assert comparison_key("patient_name", "JOHNATHAN SAMPLE") != comparison_key(
        "patient_name", "J SAMPLE"
    )
    assert comparison_key("member_id", "001-234") != comparison_key("member_id", "001234")
    assert comparison_key("patient_name", "Alpha Sample") == comparison_key(
        "patient_name", "ALPHA SAMPLE"
    )


@pytest.mark.parametrize("placeholder", ["SAME", "SAME AS ABOVE", "SELF"])
def test_placeholder_does_not_create_inherited_name(placeholder):
    result = generate_geometry(
        [
            t("INSURED NAME", 10, 10, 150, 30),
            t(placeholder, 10, 40, 150, 60),
            t("ALPHA SAMPLE", 600, 40, 750, 60),
        ],
        width=1000,
        height=1000,
    )
    assert not result


@pytest.mark.parametrize("cause", CAUSES)
def test_only_true_recognition_bucket_can_reach_secondary_ocr(cause):
    assert secondary_allowed(
        cause, region_proven=True, source_readable=True, token_value_present=False
    ) == (cause == "OCR_RECOGNITION_MISS")
    assert not secondary_allowed(
        cause, region_proven=False, source_readable=True, token_value_present=False
    )
    assert not secondary_allowed(
        cause, region_proven=True, source_readable=True, token_value_present=True
    )


def test_reviewed_orientation_is_source_hash_bound_and_not_reference_driven(tmp_path):
    path = tmp_path / "source.png"
    Image.new("RGB", (20, 30), "white").save(path)
    job = {
        "claim_alias": "SYNTHETIC",
        "page_number": 1,
        "image_path": str(path),
        "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rotation": 180,
        "visual_evidence": "SOURCE HEADER INVERTED",
        "authority": "MANUALLY_VERIFIED_DIAGNOSTIC_ONLY",
        "osd_agrees": True,
    }
    validate_rotation_job(job)
    with pytest.raises(ValueError, match="SOURCE_ONLY_ORIENTATION_SCHEMA_REQUIRED"):
        capture_reviewed_rotation({**job, "reference_value": "DO NOT INFER"}, object())
    with pytest.raises(ValueError, match="INDEPENDENT_VISUAL_ORIENTATION_EVIDENCE_REQUIRED"):
        validate_rotation_job({**job, "osd_agrees": False})
    with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
        validate_rotation_job({**job, "image_sha256": "different"})


def test_matching_admitting_code_cannot_rescue_wrong_principal_region():
    row = {
        "field": "principal_diagnosis",
        "source_visibility": {
            "visibility": "VISIBLE_CLEAR",
            "notes": [],
            "representation_difference": False,
            "orientation_180_observed": False,
        },
    }
    cause, reason, extractable = classify(
        row, {"principal_region_observed": True, "principal_region_match": False}
    )
    assert cause == "OCR_RECOGNITION_MISS" and extractable
    assert "not interchangeable" in reason


def test_compound_birthdate_replaces_generic_gender_and_row_proposals():
    from workers.field_candidates.bounded_geometry_recovery import generate_structural

    tokens = [
        t("10 BIRTHDATE", 10, 10, 100, 30),
        t("11 SEX", 160, 10, 200, 30),
        t("02292000", 15, 35, 145, 55),
        t("M", 175, 35, 185, 55),
    ]
    dates = [
        c.value
        for c in generate_structural(tokens, width=1000, height=1000)
        if c.field_name == "patient_dob"
    ]
    assert dates == ["2000-02-29"]
    assert tokens[-1].text == "M"


@pytest.mark.parametrize(
    "observed,assembled", [("123 45", "123.45"), ("123:45", "123.45"), ("123.45 s", "123.45")]
)
def test_total_assembly_uses_observed_amount_components(observed, assembled):
    from workers.field_candidates.bounded_geometry_recovery import source_amount_components

    assert source_amount_components(observed) == assembled
    tokens = [t("TOTAL CHARGE", 10, 10, 180, 30), t(observed, 10, 40, 170, 60)]
    result = generate_geometry(tokens, width=1000, height=1000)
    assert any(c.value == assembled for c in result)
    assert tokens[-1].text == observed


def test_amount_assembly_never_repairs_digits_or_guesses_fraction():
    from workers.field_candidates.bounded_geometry_recovery import source_amount_components

    assert source_amount_components("123 4") is None
    assert source_amount_components("12O:45") is None
    assert source_amount_components("123.45 OTHER") is None


def _visible_row(field):
    return {
        "field": field,
        "claim_alias": "SYNTHETIC",
        "source_visibility": {
            "visibility": "VISIBLE_CLEAR",
            "notes": [],
            "representation_difference": False,
            "orientation_180_observed": False,
        },
    }


def test_charge_header_without_total_region_is_topology_not_recognition():
    cause, _, _ = classify(_visible_row("total_charge"), {"charge_column_header_only": True})
    assert cause == "WRONG_FORM_OR_FIELD_TOPOLOGY"


def test_merged_amount_token_is_assembly_not_recognition():
    cause, _, _ = classify(_visible_row("total_charge"), {"merged_amount_match": True})
    assert cause == "TOKEN_ASSEMBLY"


def test_matching_name_in_other_column_is_not_local_assembly_proof():
    cause, _, _ = classify(
        _visible_row("patient_name"),
        {
            "token_matches": [{}],
            "label_matches": [{}],
            "local_value_match": False,
            "exact_order_token_match": False,
        },
    )
    assert cause == "LABEL_TO_VALUE_ASSOCIATION"
