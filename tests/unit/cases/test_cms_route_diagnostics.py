from evaluation.cms_route_diagnostics import diagnose


def test_fallback_reports_first_identity_failure_and_no_source_values():
    data = {"candidate_commit_sha": "candidate", "claims": [{"pages": [{"page_number": 1}],
        "fields": [], "events": [{"topic": "extraction.unstructured.requested", "envelope": {
            "payload": {"page_numbers": [1], "reason_codes": ["STANDARD_EVIDENCE_INSUFFICIENT"],
                        "private_text": "do not emit"}}}]}]}
    result = diagnose(data)
    assert result["routing"]["fallback_requested"] == 1
    assert result["first_failing_stage_counts"] == {"FORM_IDENTITY": 1}
    assert result["pages"][0]["fallback_runtime_unavailable"]
    assert "do not emit" not in str(result)
