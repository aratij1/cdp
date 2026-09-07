"""Synthetic safety and coverage tests for label-local review-only candidates."""

import inspect
from dataclasses import asdict

import pytest

from evaluation.governed_30_candidate_coverage import ranks, unique_values
from workers.field_candidates.label_token_recovery import generate, labels
from workers.page_detection.text_extraction import TextLine


def token(text, x0, y0, x1, y1):
    return TextLine(text, x0, y0, x1, y1, 0.9)


def test_number_prefix_preserves_first_label_character():
    assert labels([token("8PATIENT NAME", 10, 10, 120, 25)]) == [(0, "patient_name")]
    assert labels([token("58 INSURED'S NAME", 10, 10, 150, 25)]) == [(0, "insured_name")]


def test_other_insured_does_not_become_primary_insured():
    assert not labels([token("9. OTHER INSURED'S NAME", 10, 10, 200, 25)])


def test_separate_columns_are_not_merged():
    tokens = [
        token("2. PATIENT'S NAME", 10, 10, 190, 25),
        token("4. INSURED'S NAME", 240, 10, 440, 25),
        token("ALPHA EXAMPLE", 10, 30, 160, 45),
        token("BETA SAMPLE", 240, 30, 390, 45),
    ]
    result = generate(tokens, width=500, height=500)
    assert any(c.field_name == "patient_name" and c.value == "ALPHA EXAMPLE" for c in result)
    assert all("BETA" not in c.value for c in result if c.field_name == "patient_name")
    assert all("ALPHA" not in c.value for c in result if c.field_name == "insured_name")


def test_label_proven_last_first_uses_existing_component_interpretation():
    result = generate(
        [
            token("PATIENT NAME Last Name First Name", 10, 10, 290, 25),
            token("EXAMPLE, ALPHA Q", 10, 30, 220, 45),
        ],
        width=700,
        height=500,
    )
    assert any(c.value == "ALPHA Q EXAMPLE" for c in result)
    assert all(c.review_only for c in result)


def test_name_without_convention_or_comma_is_not_reordered():
    result = generate(
        [token("PATIENT NAME", 10, 10, 180, 25), token("ALPHA EXAMPLE", 10, 30, 170, 45)],
        width=700,
        height=500,
    )
    assert all(c.value != "EXAMPLE ALPHA" for c in result)


def test_identifier_punctuation_and_leading_zeros_preserved():
    result = generate(
        [token("MEMBER NUMBER", 10, 10, 180, 25), token("000ABC-09", 10, 30, 150, 45)],
        width=700,
        height=500,
    )
    assert any(c.value == "000ABC-09" for c in result)
    assert all(c.value != "000ABC09" for c in result)


def test_far_away_value_is_not_a_candidate():
    assert not generate(
        [token("PATIENT NAME", 10, 10, 180, 25), token("ALPHA EXAMPLE", 10, 300, 170, 315)],
        width=700,
        height=500,
    )


def test_no_labels_no_candidates_or_canonical_fallback():
    tokens = [token("EXAMPLE PERSON", 10, 10, 180, 25)]
    assert generate(tokens, width=700, height=500) == []


def test_charge_column_does_not_emit_first_service_line_as_claim_total():
    tokens = [
        token("47 TOTAL CHARGES", 300, 10, 440, 25),
        token("48 NONCOVERE CHARGES", 470, 10, 690, 25),
        token("347.89", 330, 30, 410, 45),
    ]
    assert not generate(tokens, width=750, height=500)


def test_totals_row_intersects_charge_column_not_noncovered_column():
    tokens = [
        token("47 TOTAL CHARGES", 300, 10, 440, 25),
        token("48 NONCOVERE CHARGES", 470, 10, 690, 25),
        token("TOTALS", 180, 300, 290, 315),
        token("347.89", 330, 300, 410, 315),
        token("20.00", 500, 300, 580, 315),
    ]
    result = generate(tokens, width=750, height=500)
    assert [c.value for c in result] == ["347.89"]
    assert result[0].reason == "TOTALS_ROW_CHARGE_COLUMN_INTERSECTION"


def test_candidates_have_no_acceptance_or_form_authority():
    result = generate(
        [token("TOTAL CHARGE", 10, 10, 170, 25), token("347.89", 10, 30, 100, 45)],
        width=700,
        height=500,
    )
    assert result
    for candidate in result:
        data = asdict(candidate)
        assert data["review_only"] is True
        assert not {"accepted", "canonical_form", "stp_eligible"} & data.keys()


def test_reference_and_form_override_are_not_runtime_inputs():
    assert set(inspect.signature(generate).parameters) == {"tokens", "width", "height"}
    with pytest.raises(TypeError):
        generate([], width=100, height=100, reference="SYNTHETIC")
    with pytest.raises(TypeError):
        generate([], width=100, height=100, form_type="UB04")


def test_candidate_recall_never_changes_raw_accuracy_or_chooses_truth():
    values = unique_values("member_id", ["OTHER", "MATCH", "MATCH", "LATER"])
    assert values == ["OTHER", "MATCH", "LATER"]
    assert ranks("member_id", "MATCH", values) == {"1": False, "3": True, "5": True}


def test_recall_does_not_ignore_id_case_or_leading_zeros():
    assert ranks("member_id", "000ABC", ["ABC", "000abc"]) == {"1": False, "3": False, "5": False}


def test_invalid_image_dimensions_rejected():
    with pytest.raises(ValueError, match="POSITIVE_IMAGE_DIMENSIONS_REQUIRED"):
        generate([], width=0, height=100)


def test_secondary_gate_rejects_existing_candidate_tokens_and_invalid_region():
    from evaluation.governed_30_candidate_coverage import secondary_gate

    vis = {"visibility": "VISIBLE_CLEAR", "representation_difference": False}
    trial = {"mode": "rapid", "page_number": 1, "image_sha256": "sealed", "bbox": [1, 2, 3, 4]}
    args = {
        "before": [],
        "token_present": False,
        "visibility": vis,
        "trial": trial,
        "candidates": [{"page_number": 1, "bbox": (1, 2, 3, 4)}],
        "captures": [{"page_number": 1, "image_sha256": "sealed"}],
    }
    assert secondary_gate(**args) is None
    assert (
        secondary_gate(**{**args, "token_candidate_match": True})
        == "REFERENCE_ALREADY_RECOVERED_FROM_PRIMARY_TOKENS"
    )
    assert secondary_gate(**{**args, "before": ["SOURCE"]}) == "PRIMARY_CANDIDATE_ALREADY_PRESENT"
    assert (
        secondary_gate(**{**args, "token_present": True})
        == "REFERENCE_ALREADY_IN_PRIMARY_TOKEN_LINE"
    )
    assert secondary_gate(**{**args, "candidates": []}) == "NO_VALID_LABEL_GROUNDED_REGION"
    assert secondary_gate(**{**args, "captures": []}) == "SOURCE_HASH_MISMATCH"
    assert (
        secondary_gate(**{**args, "visibility": {"visibility": "NOT_PRESENT"}})
        == "SOURCE_VALUE_NOT_FULLY_VISIBLE"
    )
    assert (
        secondary_gate(**{**args, "trial": {**trial, "mode": "trocr"}})
        == "HANDWRITING_NOT_CONFIRMED"
    )


def test_capture_rejects_reference_seed_before_image_or_engine_access():
    from evaluation.governed_30_token_capture import capture_primary, capture_region

    job = {
        "claim_alias": "SYNTHETIC",
        "page_number": 1,
        "image_path": "unused",
        "image_sha256": "unused",
        "reference_value": "DO NOT INFER",
    }
    with pytest.raises(ValueError, match="SOURCE_ONLY_INPUT_SCHEMA_REQUIRED"):
        capture_primary(job, object())
    with pytest.raises(ValueError, match="SOURCE_ONLY_INPUT_SCHEMA_REQUIRED"):
        capture_region(job, object(), mode="rapid")


def test_secondary_candidate_beyond_five_is_not_recall_at_five():
    assert not ranks("member_id", "EXACT", ["1", "2", "3", "4", "5", "EXACT"])["5"]


def test_source_absence_is_not_classified_as_ocr_failure():
    from evaluation.governed_30_candidate_coverage import inferred_stage

    assert (
        inferred_stage(
            missing=True,
            localized=True,
            present=False,
            visibility={"visibility": "NOT_PRESENT"},
            tokens=[],
            recovered=False,
        )
        == "REFERENCE_NOT_VISIBLE_ON_SOURCE"
    )
