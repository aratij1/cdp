from packages.criticality import CriticalityLevel
from packages.stp_policy import ClaimSTPContext, FieldSTPEvidence, SafeSTPPolicy, STPLevel


def _field(name="member_id", level=CriticalityLevel.C3, **changes):
    values = dict(
        field_name=name, criticality=level, required=True, resolved=True, confidence=.99,
        evidence_policy_satisfied=True, independently_verified=True,
        validation_passed=True, reference_verified=True,
    )
    values.update(changes)
    return FieldSTPEvidence(**values)


def _context(**changes):
    values = dict(
        document_id="d1", form_type="CMS1500", fields=[_field()],
        registration_confidence=.96, page_classification_confidence=.98,
        wrong_page_check_passed=True, wrong_crop_check_passed=True,
        mandatory_validation_results={"claim_total": True},
    )
    values.update(changes)
    return ClaimSTPContext(**values)


def test_all_c3_independently_verified_is_stp_safe():
    decision = SafeSTPPolicy.load().evaluate(_context())
    assert decision.level is STPLevel.STP_SAFE
    assert decision.claim_quality == .96


def test_standard_passes_all_gates_without_c3_requirement():
    decision = SafeSTPPolicy.load().evaluate(
        _context(fields=[_field(level=CriticalityLevel.C2, independently_verified=False)])
    )
    assert decision.level is STPLevel.STP_STANDARD


def test_confidence_never_overrides_failed_evidence_policy():
    decision = SafeSTPPolicy.load().evaluate(
        _context(fields=[_field(confidence=1, evidence_policy_satisfied=False)])
    )
    assert decision.level is STPLevel.REVIEW_REQUIRED
    assert "CRITICAL_EVIDENCE_POLICY_FAILED:member_id" in decision.reason_codes


def test_claim_quality_is_weakest_gate_not_average():
    decision = SafeSTPPolicy.load().evaluate(_context(registration_confidence=.91))
    assert decision.claim_quality == .91


def test_unresolved_required_field_and_contradiction_require_review():
    fields = [_field(), _field("payer_name", CriticalityLevel.C1, resolved=False)]
    decision = SafeSTPPolicy.load().evaluate(
        _context(fields=fields, unresolved_contradiction=True)
    )
    assert decision.level is STPLevel.REVIEW_REQUIRED
    assert decision.required_field_completeness == .5
    assert "REQUIRED_FIELDS_UNRESOLVED" in decision.reason_codes
    assert "UNRESOLVED_CONTRADICTION" in decision.reason_codes


def test_wrong_page_or_crop_is_rejected_not_stp():
    page = SafeSTPPolicy.load().evaluate(_context(wrong_page_check_passed=False))
    crop = SafeSTPPolicy.load().evaluate(_context(wrong_crop_check_passed=False))
    assert page.level is STPLevel.REJECTED
    assert crop.level is STPLevel.REJECTED


def test_empty_policy_and_missing_validation_fail_closed():
    decision = SafeSTPPolicy.load().evaluate(
        _context(fields=[], mandatory_validation_results={})
    )
    assert decision.level is STPLevel.REVIEW_REQUIRED
    assert "REQUIRED_FIELD_POLICY_EMPTY" in decision.reason_codes
    assert "CRITICAL_FIELD_POLICY_EMPTY" in decision.reason_codes
    assert decision.claim_quality == 0


def test_review_task_count_is_not_used_as_a_proxy_for_policy_gates():
    passing = SafeSTPPolicy.load().evaluate(_context(open_review_tasks=2))
    failing = SafeSTPPolicy.load().evaluate(
        _context(open_review_tasks=0, service_lines_valid=False)
    )
    assert passing.level is STPLevel.STP_SAFE
    assert failing.level is STPLevel.REVIEW_REQUIRED
