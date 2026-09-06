"""Synthetic safety checks for bounded date alternatives and closure accounting."""

from dataclasses import replace

import pytest

from packages.claim_intelligence.discovery import NoncanonicalDiscovery, select_recovery
from packages.claim_intelligence.document import DocumentPage, Token


def page_with_dates(*values):
    def token(text, box):
        return Token(
            text, text, box, 0.99, "synthetic", "page", str(box), "invocation", "source", "crop"
        )

    return DocumentPage(
        "page",
        "package",
        "OTHER_CLAIM_FORM",
        "NOT_VERIFIED",
        1000,
        1000,
        "SYNTHETIC",
        (
            token("DOB", (100, 100, 220, 120)),
            *(
                token(value, (100 + i * 100, 130, 190 + i * 100, 150))
                for i, value in enumerate(values)
            ),
        ),
    )


def test_complete_date_retains_its_own_provenance_beside_numeric_flag():
    page = page_with_dates("01/02/2000", "8")
    result = NoncanonicalDiscovery().extract(page)
    candidates = result.candidates["patient_dob"]
    assert [c.normalized_value for c in candidates] == ["2000-01-02"]
    assert len(candidates[0].evidence) == 1
    assert candidates[0].evidence[0].bbox == page.tokens[1].bbox
    assert page.tokens[2].text == "8"
    assert not result.production_authority and not result.canonical_localization
    for family in ("UNKNOWN", "CMS1500", "UB04"):
        assert not NoncanonicalDiscovery().extract(replace(page, form_type=family)).candidates


@pytest.mark.parametrize("value", ["001/02/2000", "02/30/2000", "O1/02/2000", "01/02/00"])
def test_no_substring_date_repair(value):
    assert not NoncanonicalDiscovery().extract(page_with_dates(value, "8")).candidates


def test_two_complete_dates_remain_ambiguous():
    result = NoncanonicalDiscovery().extract(page_with_dates("01/02/2000", "02/03/2001"))
    assert len(result.candidates["patient_dob"]) == 2
    chosen, _ = select_recovery(
        "patient_dob", result.candidates["patient_dob"], existing_value=None
    )
    assert chosen is None


@pytest.mark.parametrize(
    "label,field,value",
    [
        ("RELATIONSHIP", "relationship", "SELF"),
        ("TYPE OF BILL", "type_of_bill", "123"),
    ],
)
def test_atomic_registry_fields_preserve_complete_tokens(label, field, value):
    page = page_with_dates(value, "8")
    page = replace(
        page, tokens=(replace(page.tokens[0], text=label, normalized_text=label), *page.tokens[1:])
    )
    result = NoncanonicalDiscovery().extract(page)
    assert [c.value for c in result.candidates[field]] == [value]
    assert not result.production_authority
    invalid = "X" + value
    page = replace(
        page,
        tokens=(
            page.tokens[0],
            replace(page.tokens[1], text=invalid, normalized_text=invalid),
            page.tokens[2],
        ),
    )
    assert field not in NoncanonicalDiscovery().extract(page).candidates


def test_hitl_union_does_not_double_count_overlapping_review():
    from evaluation.closure_iteration3 import hitl_summary

    rows = [
        {
            "claim_id": "synthetic",
            "field": "a",
            "technical": ["WRONG_CROP"],
            "external": ["SOURCE_EVIDENCE_REQUIRED"],
        },
        {
            "claim_id": "synthetic",
            "field": "b",
            "technical": [],
            "external": ["MEMBER_AUTHORITY_REQUIRED"],
        },
        {"claim_id": "synthetic", "field": "c", "technical": [], "external": []},
    ]
    result = hitl_summary(rows)
    assert result["technical_hitl_rate"] == 1 / 3
    assert result["external_hitl_rate"] == result["total_observed_hitl_rate"] == 2 / 3
    assert not result["production_measured"]
    with pytest.raises(ValueError):
        hitl_summary(rows + rows[:1])


def test_unknown_external_reason_fails_closed():
    from evaluation.closure_iteration3 import external_categories

    assert external_categories("member_id", ["AUTHORITATIVE_DATA_REQUIRED"]) == [
        "MEMBER_AUTHORITY_REQUIRED"
    ]
    assert external_categories("provider_name", ["AUTHORITATIVE_DATA_REQUIRED"]) == [
        "PROVIDER_AUTHORITY_REQUIRED"
    ]
    assert external_categories("patient_name", ["AUTHORITATIVE_DATA_REQUIRED"]) == [
        "PATIENT_IDENTITY_AUTHORITY_REQUIRED"
    ]
    assert external_categories("unknown", ["NEW_REASON"]) == ["OTHER_EXTERNAL"]


def test_visibility_is_source_bound_and_never_proves_ceiling_by_itself():
    from evaluation.closure_iteration3 import audited_visibility, ceiling_status

    row = {"field_name": "patient_dob", "truth": "2000-01-02"}
    observation = {"page_sha256": "synthetic-source", "ocr_tokens": []}
    assert audited_visibility(row, observation, None) == "UNKNOWN"
    with pytest.raises(ValueError, match="BINDING"):
        audited_visibility(row, observation, {"page_sha256": "other", "visibility": "NOT_VISIBLE"})
    assert (
        ceiling_status([{"governed_recovered_after": False, "visibility": "NOT_VISIBLE"}])
        == "NOT_PROVEN"
    )
    observation["ocr_tokens"] = [{"text": "01/02/2000"}]
    assert audited_visibility(row, observation, None) == "VISIBLE_IN_EXISTING_TOKENS"


def test_dashboard_preserves_current_aggregate_checkpoint(tmp_path, monkeypatch):
    import json

    from evaluation import closure_dashboard

    monkeypatch.setattr(closure_dashboard, "ROOT", tmp_path)
    target = tmp_path / "docs/closure/iteration3_summary.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"status": "CONTINUE", "production_authority": False}))
    assert closure_dashboard.run() == {"status": "CONTINUE", "production_authority": False}
    assert not (tmp_path / "docs/closure/iteration2_diagnostics.json").exists()
