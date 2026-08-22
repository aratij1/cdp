from packages.policy_engine import AdaptivePolicyEngine, DecisionContext, PolicyAction


def _context(**changes):
    values = dict(document_type="CMS1500", field_name="member_id", criticality="critical")
    values.update(changes)
    return DecisionContext(**values)


def test_accept_requires_policy_evidence_and_no_contradiction():
    engine = AdaptivePolicyEngine.load()
    assert engine.decide(_context(current_confidence=.99)).action is PolicyAction.RAPIDOCR
    accepted = engine.decide(_context(current_confidence=.99, evidence_policy_satisfied=True))
    assert accepted.action is PolicyAction.ACCEPT
    contradicted = engine.decide(_context(current_confidence=.99, evidence_policy_satisfied=True,
                                           unresolved_contradiction=True))
    assert contradicted.action is PolicyAction.RAPIDOCR


def test_member_id_advances_through_field_specific_route():
    engine = AdaptivePolicyEngine.load()
    attempts = {PolicyAction.RAPIDOCR, PolicyAction.TESSERACT}
    decision = engine.decide(_context(previous_attempts=attempts, reference_available=True))
    assert decision.action is PolicyAction.REFERENCE_LOOKUP
    decision = engine.decide(_context(previous_attempts=attempts | {PolicyAction.REFERENCE_LOOKUP},
                                      cloud_processing_allowed=True))
    assert decision.action is PolicyAction.GEMINI_CHEAP


def test_npi_never_routes_to_gemini():
    engine = AdaptivePolicyEngine.load()
    decision = engine.decide(_context(field_name="provider_npi", previous_attempts={
        PolicyAction.RAPIDOCR, PolicyAction.TESSERACT, PolicyAction.REFERENCE_LOOKUP},
        reference_available=True, cloud_processing_allowed=True))
    assert decision.action is PolicyAction.HITL


def test_uncertain_registration_gets_one_bounded_crop_expansion():
    engine = AdaptivePolicyEngine.load()
    first = engine.decide(_context(registration_confidence=.7))
    assert first.action is PolicyAction.EXPAND_CROP
    second = engine.decide(_context(registration_confidence=.7,
                                    previous_attempts={PolicyAction.EXPAND_CROP}))
    assert second.action is PolicyAction.RAPIDOCR


def test_table_uses_docling_before_cloud_fallback():
    engine = AdaptivePolicyEngine.load()
    decision = engine.decide(_context(field_name="service_lines", is_table_field=True,
                                     previous_attempts={PolicyAction.RAPIDOCR}))
    assert decision.action is PolicyAction.DOCLING


def test_budget_and_cloud_policy_skip_ineligible_actions():
    engine = AdaptivePolicyEngine.load()
    decision = engine.decide(_context(previous_attempts={PolicyAction.RAPIDOCR, PolicyAction.TESSERACT},
                                     reference_available=False, cloud_processing_allowed=False,
                                     remaining_budget=0))
    assert decision.action is PolicyAction.HITL
    assert "cloud_processing_disallowed" in decision.reason_codes
