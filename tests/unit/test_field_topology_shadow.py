from dataclasses import replace

import pytest

from packages.claim_intelligence.field_topology import FormFieldTopology, generate
from workers.page_detection.text_extraction import TextLine

SHA = "a" * 64


def top(field="member_id", policy="IDENTIFIER_PRESENTATION_ALTERNATIVE"):
    return FormFieldTopology(
        "CMS1500",
        field,
        (0.1, 0.1, 0.6, 0.2),
        "OWN_LABELED_CELL",
        "SAME_ROW",
        policy,
        "PRESERVE_ALL_ALPHANUMERIC_COMPONENTS",
        "SOURCE_REVIEWED_ENGINEERING_ONLY",
        document_type="CMS1500",
        required_label_pattern="Member ID",
    )


def run(t, ts, **kwargs):
    args = {
        "topology": t,
        "form_type": t.form_type,
        "document_type": t.document_type,
        "source_sha256": SHA,
        "reviewed_source_sha256": SHA,
        "width": 1000,
        "height": 1000,
    }
    args.update(kwargs)
    return generate([TextLine("Member ID", 10, 10, 100, 30, 0.9)] + ts, **args)


def token(s, x=150, y=140):
    return TextLine(s, x, y, x + 100, y + 25, 0.95)


def test_identifier_presentation_preserves_literal_and_suffix():
    result = run(top(), [token("AB123-00")])
    assert [c["value"] for c in result] == ["AB123-00", "AB12300"]
    assert all(c["raw_tokens"][0]["text"] == "AB123-00" and c["review_only"] for c in result)


@pytest.mark.parametrize("form", ["UNKNOWN", "OTHER", "UB04", ""])
def test_identity_cannot_be_overridden(form):
    assert run(top(), [token("123")], form_type=form) == []


def test_source_review_and_label_must_match():
    assert run(top(), [token("123")], source_sha256="b" * 64) == []
    assert run(replace(top(), required_label_pattern="Missing Label"), [token("123")]) == []
    assert run(replace(top(), provenance="AUTO"), [token("123")]) == []


def test_name_components_keep_middle_initial_and_skip_addresses():
    t = replace(
        top("patient_name", "NAME_LAST_FIRST"), validation_policy="OBSERVED_NAME_COMPONENTS_ONLY"
    )
    result = run(t, [token("DOE,", 120), token("JANE,", 260), token("Q", 400)])
    assert result[0]["value"] == "JANE Q DOE"
    assert run(t, [token("DOE", 120), token("12 ROAD", 260)]) == []
    assert run(t, [token("SAME", 120)]) == []


def test_lab_summary_excludes_lines_paid_and_balance():
    t = replace(
        top("total_charge", "EXPLICIT_CLAIM_TOTAL"),
        form_type="OTHER",
        document_type="LABORATORY_BILL",
        label_relationship="LAB_SUMMARY_TAX_ID_ROW",
        validation_policy="CLAIM_TOTAL_ROLE_ONLY",
        normalized_region=(0.1, 0.1, 0.4, 0.8),
        required_label_pattern="Tax ID",
    )
    ts = [
        token("Tax ID: XX", 5, 600),
        token("10.00", 160, 200),
        token("20.00", 160, 300),
        token("30.00", 160, 600),
        token("0.00", 650, 600),
    ]
    assert [c["value"] for c in run(t, ts)] == ["30.00"]
    assert run(replace(t, label_relationship="OWN_LABELED_CELL"), ts) == []


def test_ungoverned_other_and_unknown_never_generate():
    t = replace(top(), form_type="OTHER", document_type="UNCLASSIFIED")
    assert run(t, [token("123")]) == []


def test_amount_requires_observed_decimal_not_invented_digits():
    t = replace(
        top("total_charge", "EXPLICIT_CLAIM_TOTAL"),
        form_type="OTHER",
        document_type="PSYCHOLOGY_RECEIPT",
        validation_policy="CLAIM_TOTAL_ROLE_ONLY",
    )
    assert run(t, [token("12O.00")]) == []
    assert run(t, [token("12000")]) == []


def test_no_reference_or_claim_identity_inputs():
    import inspect

    assert not {"expected", "reference", "claim_alias", "expected_length"} & set(
        inspect.signature(generate).parameters
    )


def test_date_does_not_concatenate_neighbor_label_or_invent_zero():
    from packages.claim_intelligence.field_topology import observed_date_values

    assert observed_date_values([token("10041971"), token("OCCURRENCE")]) == ["1971-10-04"]
    assert observed_date_values([token("1C041971")]) == []
    assert observed_date_values([token("13321971")]) == []


def test_single_line_punctuation_does_not_repair_letters():
    from packages.claim_intelligence.field_topology import source_line_values

    assert source_line_values("DOE, JANE, Q*", "insured_name") == ["JANE Q DOE"]
    assert source_line_values("E20.9", "principal_diagnosis") == ["E20.9"]
    assert source_line_values("'388", "principal_diagnosis") == []


def test_review_rank_preserves_coverage_and_requires_source_provenance():
    from packages.claim_intelligence.field_topology import rank_review_candidates

    values = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
    proof = {
        "value": "epsilon",
        "source_sha256": "a" * 64,
        "region_bbox": [1, 2, 3, 4],
        "review_only": True,
        "authority": "ENGINEERING_ONLY",
    }
    ranked = rank_review_candidates(values, [proof])
    assert ranked[0] == "epsilon"
    assert set(ranked[:5]) == set(values[:5])
    assert ranked[5:] == values[5:]
    assert rank_review_candidates(values, [{**proof, "source_sha256": ""}]) == values
