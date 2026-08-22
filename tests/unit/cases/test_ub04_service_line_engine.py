from decimal import Decimal

from workers.table_extraction import UB04ServiceLineEngine, UB04Token


def _token(text, x, y=580, confidence=.96):
    return UB04Token(text=text, bbox=(x, y, x + 30, y + 12), confidence=confidence)


def _valid_tokens():
    return [
        _token("0450", 40),
        _token("EMERGENCY", 150),
        _token("99281", 650),
        _token("010224", 930),
        _token("1", 1080),
        _token("125.50", 1240),
    ]


def test_reconstructs_associated_valid_row_and_reconciles_total():
    result = UB04ServiceLineEngine(hcpcs_reference={"99281"}).reconstruct(
        _valid_tokens(), registration_confidence=.95, claim_total=Decimal("125.50")
    )
    assert result.geometry_valid is True
    assert result.totals_reconciled is True
    assert len(result.lines) == 1
    line = result.lines[0]
    assert line.revenue_code == "0450"
    assert line.hcpcs == "99281"
    assert line.service_date.isoformat() == "2024-01-02"
    assert line.units == Decimal("1")
    assert line.charge == Decimal("125.50")
    assert line.automatically_eligible is True


def test_values_on_second_geometry_row_stay_associated():
    tokens = _valid_tokens() + [_token("0300", 40, y=615), _token("50.00", 1240, y=615)]
    result = UB04ServiceLineEngine(hcpcs_reference={"99281"}).reconstruct(
        tokens, registration_confidence=.95, claim_total=Decimal("175.50")
    )
    assert [line.line_number for line in result.lines] == [1, 2]
    assert result.lines[1].revenue_code == "0300"
    assert result.lines[1].charge == Decimal("50.00")


def test_low_registration_routes_whole_table_to_docling():
    result = UB04ServiceLineEngine().reconstruct(_valid_tokens(), registration_confidence=.7)
    assert result.geometry_valid is False
    assert result.escalation == "DOCLING"
    assert result.lines == []


def test_unreliable_geometry_fails_closed_instead_of_mixing_rows():
    tokens = _valid_tokens() + [_token("noise", 1650, y=200), _token("noise", 1650, y=300),
                               _token("noise", 1650, y=400)]
    result = UB04ServiceLineEngine().reconstruct(tokens, registration_confidence=.95)
    assert result.geometry_valid is False
    assert result.escalation == "DOCLING"
    assert "TABLE_GEOMETRY_UNRELIABLE" in result.reason_codes


def test_invalid_hcpcs_and_total_mismatch_require_review():
    tokens = _valid_tokens()
    tokens[2] = _token("BAD", 650)
    result = UB04ServiceLineEngine(hcpcs_reference={"99281"}).reconstruct(
        tokens, registration_confidence=.95, claim_total=Decimal("999")
    )
    assert result.escalation == "HITL"
    assert "TOTAL_CHARGES_MISMATCH" in result.reason_codes
    assert "INVALID_HCPCS_FORMAT" in result.lines[0].validation_errors
    assert result.lines[0].automatically_eligible is False


def test_hcpcs_cannot_be_auto_eligible_without_reference_data():
    result = UB04ServiceLineEngine().reconstruct(_valid_tokens(), registration_confidence=.95)
    assert "HCPCS_REFERENCE_UNAVAILABLE" in result.lines[0].validation_errors
    assert result.lines[0].automatically_eligible is False


def test_missing_claim_total_prevents_automatic_row_eligibility():
    result = UB04ServiceLineEngine(hcpcs_reference={"99281"}).reconstruct(
        _valid_tokens(), registration_confidence=.95
    )
    assert "TOTAL_RECONCILIATION_UNAVAILABLE" in result.reason_codes
    assert result.escalation == "HITL"
    assert result.lines[0].automatically_eligible is False


def test_empty_regional_result_fails_closed_to_docling():
    result = UB04ServiceLineEngine().reconstruct([], registration_confidence=.95)
    assert result.geometry_valid is False
    assert result.escalation == "DOCLING"
    assert result.reason_codes == ["TABLE_EMPTY"]
    assert result.policy_version == "ub04-service-lines-v2"


def test_numeric_and_future_date_validation_prevent_automatic_eligibility():
    tokens = _valid_tokens()
    tokens[3] = _token("010299", 930)
    tokens[4] = _token("0", 1080)
    tokens[5] = _token("-125.50", 1240)
    result = UB04ServiceLineEngine(hcpcs_reference={"99281"}).reconstruct(
        tokens, registration_confidence=.95, claim_total=Decimal("-125.50")
    )
    errors = result.lines[0].validation_errors
    assert "FUTURE_SERVICE_DATE" in errors
    assert "INVALID_UNITS" in errors
    assert "INVALID_CHARGE" in errors
    assert result.lines[0].automatically_eligible is False


def test_reference_and_policy_versions_are_preserved():
    result = UB04ServiceLineEngine(
        {"99281"}, hcpcs_reference_version="hcpcs-2026-q3"
    ).reconstruct(_valid_tokens(), registration_confidence=.95, claim_total=Decimal("125.50"))
    assert result.hcpcs_reference_version == "hcpcs-2026-q3"
    assert result.policy_version == "ub04-service-lines-v2"
