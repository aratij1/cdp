from packages.claim_intelligence import (
    AuthorityState,
    Candidate,
    CandidateEvidence,
    CDP2ShadowEngine,
    ClaimConsistencyEngine,
    ClaimGraph,
    ExtractionState,
    FieldNode,
    ServiceLine,
)


def _candidate(candidate_id: str, value: str, confidence: float = 0.9) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        value=value,
        evidence=(
            CandidateEvidence(
                source="rapidocr",
                confidence=confidence,
                page_id="p1",
                crop_hash=f"crop-{candidate_id}",
                independent_group=f"g-{candidate_id}",
                source_id="source",
                provenance_id=f"inv-{candidate_id}",
                localization_region=f"region-{candidate_id}",
            ),
        ),
    )


def test_total_charge_exact_decimal_proof() -> None:
    claim = ClaimGraph(
        claim_id="c1",
        service_lines_complete=True,
        form_type="UB04",
        fields={
            "total_charge": FieldNode(
                name="total_charge",
                candidates=[_candidate("c-total", "1527.00")],
                extraction_state=ExtractionState.EXTRACTED_AMBIGUOUS,
                authority_state=AuthorityState.AUTHORITATIVE_NOT_REQUIRED,
            )
        },
        service_lines=[
            ServiceLine("1", charge="425.00", evidence=_candidate("line1", "425.00").evidence),
            ServiceLine("2", charge="350.00", evidence=_candidate("line2", "350.00").evidence),
            ServiceLine("3", charge="252.00", evidence=_candidate("line3", "252.00").evidence),
            ServiceLine("4", charge="500.00", evidence=_candidate("line4", "500.00").evidence),
        ],
    )
    results = ClaimConsistencyEngine().total_charge(claim)
    assert len(results) == 1
    assert results[0].verdict == "PROOF"


def test_total_charge_missing_line_fails_closed() -> None:
    claim = ClaimGraph(
        claim_id="c2",
        form_type="UB04",
        fields={
            "total_charge": FieldNode(
                name="total_charge",
                candidates=[_candidate("c-total", "100.00")],
            )
        },
        service_lines=[ServiceLine("1", charge=None)],
    )
    assert ClaimConsistencyEngine().total_charge(claim) == []


def test_service_date_outside_statement_period_conflicts() -> None:
    claim = ClaimGraph(
        claim_id="c3",
        form_type="UB04",
        statement_start="2026-01-01",
        statement_end="2026-01-31",
        service_lines=[ServiceLine("1", service_date="2026-02-01")],
    )
    results = ClaimConsistencyEngine().service_dates(claim)
    assert results[0].verdict == "CONFLICT"


def test_shadow_engine_never_grants_production_authority() -> None:
    claim = ClaimGraph(
        claim_id="c4",
        form_type="CMS1500",
        fields={
            "member_id": FieldNode(
                name="member_id",
                candidates=[_candidate("m1", "ABC123", 0.99)],
                extraction_state=ExtractionState.EXTRACTED_CONFIDENT,
                authority_state=AuthorityState.AUTHORITATIVE_NOT_AVAILABLE,
            )
        },
    )
    result = CDP2ShadowEngine().evaluate(claim)
    assert result.production_authority is False
    assert all(field.production_authority is False for field in result.fields)
    assert result.fields[0].authority_state.endswith("AUTHORITATIVE_NOT_AVAILABLE")


def test_deterministic_conflict_forces_shadow_review() -> None:
    claim = ClaimGraph(
        claim_id="c5",
        form_type="CMS1500",
        fields={
            "patient_dob": FieldNode(
                name="patient_dob",
                candidates=[_candidate("dob1", "2027-01-01", 0.99)],
                extraction_state=ExtractionState.EXTRACTED_CONFIDENT,
                authority_state=AuthorityState.AUTHORITATIVE_NOT_REQUIRED,
            )
        },
        service_lines=[ServiceLine("1", service_date="2026-01-01")],
    )
    result = CDP2ShadowEngine().evaluate(claim)
    assert result.fields[0].decision.action == "REVIEW_SHADOW"
    assert "DETERMINISTIC_CONFLICT" in result.fields[0].decision.reasons
