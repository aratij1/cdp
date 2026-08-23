from packages.evidence_decision import EvidenceDecisionService


def test_runtime_rejects_evaluation_only_routes():
    runtime = EvidenceDecisionService(route_mode="runtime")
    assert set(runtime.ocr_routes) == {
        "federal_tax_no",
        "insured_id_number",
        "provider_npi",
        "total_charge",
    }
    assert runtime.ocr_routes["insured_id_number"]["state"] == "PRODUCTION_APPROVED"


def test_evaluation_can_measure_nonproduction_routes():
    evaluation = EvidenceDecisionService(route_mode="evaluation")
    assert "patient_name" in evaluation.ocr_routes
    assert evaluation.ocr_routes["patient_name"]["state"] == "EVALUATION_ONLY"


def test_member_alias_resolves_to_approved_insured_id_route():
    runtime = EvidenceDecisionService(route_mode="runtime")
    route = runtime.production_route_for("CMS1500", "member_id")

    assert route is not None
    assert route.field == "insured_id_number"
    assert route.primary_engine == "paddleocr"
    assert route.confirmation_engine == "rapidocr"
