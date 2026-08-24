from evaluation.phase8_10b_parity import _context, _field_projection
from packages.claim_decision import ClaimDecisionContext
from packages.evidence_dependency import DependencyRelation, EvidenceDependencyService
from packages.ocr.provenance import EvidenceProvenance
from packages.runtime_profile import (
    HISTORICAL_PHASE8_10_PROFILE_PATH,
    DecisionServiceFactory,
)


def test_runtime_and_evaluation_load_identical_canonical_configuration():
    runtime = DecisionServiceFactory.from_profile()
    evaluation = DecisionServiceFactory.from_profile()
    assert evaluation.profile.matches_runtime(runtime.profile)
    assert runtime.profile.evidence_policy_sha256 == evaluation.profile.evidence_policy_sha256
    assert runtime.profile.route_registry_sha256 == evaluation.profile.route_registry_sha256
    assert runtime.profile.route_mode == evaluation.profile.route_mode == "runtime"


def test_same_context_produces_exact_required_field_decision_projection():
    runtime = DecisionServiceFactory.from_profile()
    evaluation = DecisionServiceFactory.from_profile()
    left = runtime.evidence_decision.decide(_context())
    right = evaluation.evidence_decision.decide(_context())
    assert _field_projection(left) == _field_projection(right)
    assert left.runtime_profile_id == "cdp-runtime-decision@phase8.10b-v1"


def test_same_field_decisions_produce_exact_claim_decision():
    runtime = DecisionServiceFactory.from_profile()
    evaluation = DecisionServiceFactory.from_profile()
    left_field = runtime.evidence_decision.decide(_context())
    right_field = evaluation.evidence_decision.decide(_context())
    left = runtime.claim_decision.decide(ClaimDecisionContext(
        claim_id="same", document_family="CMS1500", field_decisions=[left_field],
        policy_id=runtime.claim_decision.policy_id,
        policy_version=runtime.claim_decision.policy_version,
        enforce_configured_required_fields=False,
    ))
    right = evaluation.claim_decision.decide(ClaimDecisionContext(
        claim_id="same", document_family="CMS1500", field_decisions=[right_field],
        policy_id=evaluation.claim_decision.policy_id,
        policy_version=evaluation.claim_decision.policy_version,
        enforce_configured_required_fields=False,
    ))
    assert left.model_dump(mode="json") == right.model_dump(mode="json")
    assert left.runtime_profile_id == "cdp-runtime-decision@phase8.10b-v1"


def test_historical_profile_cannot_claim_runtime_parity():
    runtime = DecisionServiceFactory.from_profile()
    historical = DecisionServiceFactory.from_profile(HISTORICAL_PHASE8_10_PROFILE_PATH)
    assert not historical.profile.matches_runtime(runtime.profile)
    assert historical.profile.profile_status.value == "HISTORICAL_ONLY"
    assert historical.profile.route_mode == "evaluation"
    assert historical.profile.evidence_policy_sha256 != runtime.profile.evidence_policy_sha256


def test_engine_name_alone_never_makes_candidates_independent():
    common = {
        "page_sha256": "a" * 64,
        "source_representation_id": "same-page",
        "observation_id": "same-observation",
        "crop_sha256": "b" * 64,
        "localization_id": "same-localization",
        "preprocessing_profile": "same-preparation",
        "engine_family": "rapid-family",
    }
    left = EvidenceProvenance(**common, engine_name="rapidocr")
    right = EvidenceProvenance(**common, engine_name="paddleocr")
    result = EvidenceDependencyService().classify(left, right)
    assert result.relation is DependencyRelation.CORRELATED
