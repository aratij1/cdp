from packages.deterministic_evidence import DeterministicEvidenceService


def test_runtime_and_evaluation_contexts_produce_identical_deterministic_evidence():
    runtime = DeterministicEvidenceService().evaluate(
        "total_charge", "150.00", claim_values={"service_line_charges": "100.00,50.00"}
    )
    evaluation = DeterministicEvidenceService().evaluate(
        "total_charge", "150.00", claim_values={"service_line_charges": "100.00,50.00"}
    )
    assert runtime == evaluation
