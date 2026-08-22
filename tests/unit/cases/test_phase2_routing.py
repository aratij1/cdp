from packages.policy_engine.contracts import DecisionContext, PolicyAction
from packages.policy_engine.engine import AdaptivePolicyEngine


def context(field_name: str) -> DecisionContext:
    return DecisionContext(
        document_type="CMS1500", field_name=field_name, criticality="critical",
        previous_attempts={PolicyAction.RAPIDOCR}, remaining_budget=1, remaining_sla=10,
    )


def test_secondary_ocr_is_selected_by_field_family() -> None:
    policy = AdaptivePolicyEngine.load()
    assert policy.decide(context("patient_dob")).action is PolicyAction.TESSERACT
    assert policy.decide(context("service_charge")).action is PolicyAction.TESSERACT
    assert policy.decide(context("procedure_code")).action is PolicyAction.TESSERACT
    assert policy.decide(context("patient_name")).action is PolicyAction.PADDLEOCR
    assert policy.decide(context("patient_address")).action is PolicyAction.PADDLEOCR
