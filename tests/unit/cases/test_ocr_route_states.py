from packages.evidence_decision import EvidenceDecisionService


def test_runtime_rejects_evaluation_only_routes():
    runtime = EvidenceDecisionService(route_mode="runtime")
    assert set(runtime.ocr_routes) == {"insured_id_number"}
    assert runtime.ocr_routes["insured_id_number"]["state"] == "PRODUCTION_APPROVED"


def test_evaluation_can_measure_nonproduction_routes():
    evaluation = EvidenceDecisionService(route_mode="evaluation")
    assert "patient_name" in evaluation.ocr_routes
    assert evaluation.ocr_routes["patient_name"]["state"] == "EVALUATION_ONLY"
