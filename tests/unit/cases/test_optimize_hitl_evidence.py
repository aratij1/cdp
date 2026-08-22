from evaluation.optimize_hitl_evidence import evidence_decision, optimize_dataset
from packages.evidence_router import ReferenceSourceState


def _field(name="patient_first", candidates=()):
    return {
        "field_name": name, "raw_value": None, "normalized_value": None,
        "confidence": 0.5, "accepted": False, "reviewed": True,
        "metadata": {"ocr_candidates": list(candidates)},
    }


def _candidate(engine, value, confidence=.95):
    return {"engine": engine, "value": value, "confidence": confidence}


def test_critical_name_requires_rapid_paddle_and_structural_evidence():
    field = _field(candidates=[
        _candidate("rapidocr", "JANE"), _candidate("tesseract_psm_7", "JANE")
    ])
    assert evidence_decision(field) is None
    field["metadata"]["ocr_candidates"].append(_candidate("paddleocr", "Jane"))
    assert evidence_decision(field) is None
    no_reference = evidence_decision(
        field,
        registration_confidence=.95,
        structural_evidence_source="TEST_FIXTURE_CANONICAL",
    )
    assert no_reference["final_disposition"] == "AUTO_ACCEPTED"
    reference = {"decision": "REFERENCE_VERIFIED", "reference_value": "JANE"}
    decision = evidence_decision(
        field, reference,
        registration_confidence=.95,
        structural_evidence_source="TEST_FIXTURE_CANONICAL",
        reference_source_state=ReferenceSourceState.AUTHORIZED,
    )
    assert decision["canonical"] == "JANE"
    assert decision["final_disposition"] == "REFERENCE_CONFIRMED"
    assert decision["policy_version"] == "evidence-policy-v2-candidate"


def test_form_label_and_invalid_state_fail_closed():
    labels = [_candidate("rapidocr", "PATIENT NAME"), _candidate("paddleocr", "PATIENT NAME")]
    assert evidence_decision(_field(candidates=labels)) is None
    states = [_candidate("rapidocr", "JA"), _candidate("paddleocr", "JA")]
    assert evidence_decision(_field("patient_state", states)) is None


def test_tesseract_variants_count_as_one_independent_family():
    candidates = [
        _candidate("tesseract_psm_7", "90210"),
        _candidate("tesseract_psm_11", "90210"),
    ]
    assert evidence_decision(_field("patient_zip", candidates)) is None


def test_unpromoted_field_route_remains_review_only_even_with_consensus():
    candidates = [_candidate("rapidocr", "90210"), _candidate("paddleocr", "90210")]
    assert evidence_decision(_field("patient_zip", candidates)) is None


def test_optimizer_records_truth_blind_provenance():
    field = _field(candidates=[_candidate("rapidocr", "JANE"), _candidate("paddleocr", "JANE")])
    field["metadata"].update({
        "registration_confidence": .95,
        "structural_evidence_source": "TEST_FIXTURE_CANONICAL",
        "reference_source_state": "AUTHORIZED",
    })
    payload = {"schema_version": "1.0", "documents": [{"document_id": "D1", "fields": [field]}]}
    refs = [{"identity_key": "D1|1|CMS1500||patient_first", "decision": "REFERENCE_VERIFIED",
             "reference_value": "JANE"}]
    output, metrics = optimize_dataset(payload, refs)
    result = output["documents"][0]["fields"][0]
    assert result["accepted"] is True
    assert result["metadata"]["hitl_optimization"]["ground_truth_loaded"] is False
    assert metrics["promoted_fields"] == 1


def test_authorized_reference_cannot_promote_without_ocr_evidence():
    field = _field(candidates=[])
    field["raw_value"] = "JANE"
    payload = {"schema_version": "1.0", "documents": [{"document_id": "D1", "fields": [field]}]}
    refs = [{"identity_key": "D1|1|CMS1500||patient_first", "decision": "REFERENCE_VERIFIED",
             "reference_value": "JANE", "reference_provider": "eligibility"}]
    output, metrics = optimize_dataset(payload, refs)
    result = output["documents"][0]["fields"][0]
    assert result["accepted"] is False
    assert metrics["promoted_fields"] == 0


def test_reference_contradiction_and_empty_candidate_fail_closed():
    field = _field(candidates=[])
    payload = {"schema_version": "1.0", "documents": [{"document_id": "D1", "fields": [field]}]}
    refs = [{"identity_key": "D1|1|CMS1500||patient_first", "decision": "REFERENCE_VERIFIED"}]
    output, _ = optimize_dataset(payload, refs)
    assert output["documents"][0]["fields"][0]["accepted"] is False
