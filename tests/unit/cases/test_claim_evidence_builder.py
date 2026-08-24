from packages.claim_evidence import ClaimEvidenceBuilder


def _types(items):
    return {item.evidence_type for item in items}


def test_financial_and_date_relationships_create_e6_evidence():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={
            "total_charge": "30.00",
            "statement_period_from": "2026-01-01",
            "statement_period_to": "2026-01-31",
        },
        service_lines=[
            {"units": "2", "rate": "10", "charges": "20.00"},
            {"units": "1", "rate": "10", "charges": "10.00"},
        ],
    )
    assert {
        "CLAIM_TOTAL_CONFIRMED",
        "SERVICE_LINE_RECONCILED",
        "DATE_RELATIONSHIP_CONFIRMED",
    } <= _types(result.evidence_items)
    assert not result.contradictions


def test_financial_mismatch_is_an_explicit_claim_contradiction():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={"total_charge": "100.00"},
        service_lines=[{"charges": "90.00"}],
    )
    assert "CLAIM_TOTAL_CONTRADICTION" in _types(result.contradictions)


def test_member_and_provider_internal_consistency_are_e6_not_e5():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={
            "insured_id_number": ["ABC123", "ABC-123"],
            "provider_npi": ["1234567893", "1234567893"],
        },
    )
    assert {"MEMBER_IDENTITY_CONSISTENT", "PROVIDER_IDENTITY_CONSISTENT"} <= _types(
        result.evidence_items
    )
    assert {item.evidence_class.value for item in result.evidence_items} == {"E6"}
    assert all(not item.authoritative for item in result.evidence_items)


def test_ub04_service_line_coherence_and_failure_are_recorded():
    builder = ClaimEvidenceBuilder.load()
    coherent = builder.build(
        claim_id="claim-1",
        document_family="UB04",
        claim_values={},
        service_lines=[{
            "revenue_code": "0450", "hcpcs_code": "G0463",
            "units": "1", "charges": "25.00",
        }],
    )
    assert "UB04_SERVICE_LINE_COHERENT" in _types(coherent.evidence_items)
    invalid = builder.build(
        claim_id="claim-2",
        document_family="UB04",
        claim_values={},
        service_lines=[{"revenue_code": "45", "units": "0", "charges": "25.00"}],
    )
    assert "UB04_SERVICE_LINE_CONTRADICTION" in _types(invalid.contradictions)
