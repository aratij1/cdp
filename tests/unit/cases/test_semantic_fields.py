import pytest

from packages.semantic_fields import (
    SemanticFieldState,
    SemanticFieldValue,
    SentinelProjectionRule,
    SourceReference,
    infer_same_as_state,
    project_output_sentinel,
)


def test_unapproved_sentinel_rule_cannot_project_output():
    semantic = SemanticFieldValue(
        "insured_zip", SemanticFieldState.NOT_APPLICABLE, None, None,
        None, None, ("page:1",), True,
    )
    rule = SentinelProjectionRule(
        "CMS1500_INSURED_ZIP_NA", "1.0", "insured_zip",
        SemanticFieldState.NOT_APPLICABLE, "999999999", "pending",
    )
    with pytest.raises(ValueError, match="not an approved"):
        project_output_sentinel(semantic, rule)


def test_approved_rule_requires_validated_semantic_evidence():
    semantic = SemanticFieldValue(
        "insured_zip", SemanticFieldState.UNKNOWN, None, None,
        None, None, (), False,
    )
    rule = SentinelProjectionRule(
        "rule", "1", "insured_zip", SemanticFieldState.NOT_APPLICABLE,
        "999999999", "approved", "NSF record-field citation",
    )
    with pytest.raises(ValueError, match="has not satisfied"):
        project_output_sentinel(semantic, rule)


def test_same_as_requires_explicit_owner_bound_reference():
    result = infer_same_as_state(
        field_name="patient_addr1",
        source_value="SAME",
        claim_id="claim", same_owner_approved_claim=True,
        reference_fields={
            "patient_addr1": SourceReference("claim", "SAME", ("printed-same",), ("insured",)),
            "insured": SourceReference("claim", "14390 N 99TH ST", ("printed-address",)),
        },
        counterpart_value="14390 N 99TH ST",
        relationship_code="01",
        counterpart=SemanticFieldState.SAME_AS_INSURED,
        evidence_references=("rel_code:pixel", "insured_addr1:regional_ocr"),
    )
    assert result.validated
    assert result.semantic_state == SemanticFieldState.SAME_AS_INSURED
    assert result.output_value == "14390 N 99TH ST"


def test_same_as_does_not_overwrite_visible_source():
    result = infer_same_as_state(
        field_name="patient_addr1",
        source_value="different address",
        counterpart_value="14390 N 99TH ST",
        relationship_code="01",
        counterpart=SemanticFieldState.SAME_AS_INSURED,
        evidence_references=("rel_code:pixel",),
    )
    assert not result.validated
    assert result.semantic_state == SemanticFieldState.UNKNOWN
