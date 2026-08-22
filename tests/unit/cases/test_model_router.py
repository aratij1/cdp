"""Hybrid model router: escalation-order decision logic, cost/reason
codes, and VLM-disabled-by-default behavior."""

from packages.domain.enums import ExtractionMethod, FieldCriticality
from packages.model_router import ModelRouter, RouterInput
from packages.validation_rules.thresholds import FieldThreshold, ThresholdRegistry


def _registry() -> ThresholdRegistry:
    return ThresholdRegistry(
        [
            FieldThreshold(
                field_name="provider_npi", criticality=FieldCriticality.CRITICAL, min_confidence=0.9
            )
        ]
    )


def test_cache_hit_short_circuits_everything():
    router = ModelRouter(_registry())
    decision = router.decide(
        RouterInput(
            field_name="provider_npi",
            field_criticality=FieldCriticality.CRITICAL,
            ocr_confidence=0.0,
            cache_hit=True,
        )
    )
    assert decision.selected_route == ExtractionMethod.CACHE_HIT
    assert decision.estimated_cost_usd == 0.0
    assert decision.escalation_count == 0


def test_field_meeting_threshold_is_accepted_without_escalation():
    router = ModelRouter(_registry())
    decision = router.decide(
        RouterInput(
            field_name="provider_npi",
            field_criticality=FieldCriticality.CRITICAL,
            ocr_confidence=0.95,
            evidence_policy_satisfied=True,
        )
    )
    assert decision.selected_route == ExtractionMethod.REGIONAL_PADDLEOCR
    assert decision.escalation_count == 0


def test_low_confidence_critical_field_escalates_to_alternate_ocr_first():
    router = ModelRouter(_registry())
    decision = router.decide(
        RouterInput(
            field_name="provider_npi",
            field_criticality=FieldCriticality.CRITICAL,
            ocr_confidence=0.4,
        )
    )
    assert decision.selected_route == ExtractionMethod.ALTERNATE_PREPROCESS_OCR
    assert "low_ocr_confidence" in decision.reason_codes


def test_full_escalation_ladder_advances_one_step_at_a_time():
    router = ModelRouter(_registry(), vlm_enabled=True)
    attempted: set[ExtractionMethod] = set()
    base_input = {
        "field_name": "provider_npi", "field_criticality": FieldCriticality.CRITICAL, "ocr_confidence": 0.1
    }

    decision = router.decide(RouterInput(attempted_methods=frozenset(attempted), **base_input))
    assert decision.selected_route == ExtractionMethod.ALTERNATE_PREPROCESS_OCR
    attempted.add(decision.selected_route)

    decision = router.decide(RouterInput(attempted_methods=frozenset(attempted), **base_input))
    assert decision.selected_route == ExtractionMethod.VLM_FALLBACK
    attempted.add(decision.selected_route)

    decision = router.decide(RouterInput(attempted_methods=frozenset(attempted), **base_input))
    assert decision.selected_route == ExtractionMethod.HUMAN_REVIEW


def test_vlm_disabled_by_default_skips_straight_to_human_review():
    router = ModelRouter(_registry(), vlm_enabled=False)
    decision = router.decide(
        RouterInput(
            field_name="provider_npi",
            field_criticality=FieldCriticality.CRITICAL,
            ocr_confidence=0.1,
            attempted_methods=frozenset({ExtractionMethod.ALTERNATE_PREPROCESS_OCR}),
        )
    )
    assert decision.selected_route == ExtractionMethod.HUMAN_REVIEW


def test_vlm_enabled_but_field_opts_out_still_skips_to_human_review():
    router = ModelRouter(_registry(), vlm_enabled=True)
    decision = router.decide(
        RouterInput(
            field_name="provider_npi",
            field_criticality=FieldCriticality.CRITICAL,
            ocr_confidence=0.1,
            vlm_enabled=False,
            attempted_methods=frozenset({ExtractionMethod.ALTERNATE_PREPROCESS_OCR}),
        )
    )
    assert decision.selected_route == ExtractionMethod.HUMAN_REVIEW


def test_pipeline_runs_end_to_end_with_vlm_disabled():
    """The full ladder from first failure to human review, with the VLM
    globally disabled -- proves the pipeline never gets stuck waiting on
    a VLM call it isn't allowed to make."""
    router = ModelRouter(_registry(), vlm_enabled=False)
    attempted: set[ExtractionMethod] = set()
    base_input = {
        "field_name": "provider_npi", "field_criticality": FieldCriticality.CRITICAL, "ocr_confidence": 0.1
    }
    routes = []
    for _ in range(5):
        decision = router.decide(RouterInput(attempted_methods=frozenset(attempted), **base_input))
        routes.append(decision.selected_route)
        if decision.selected_route == ExtractionMethod.HUMAN_REVIEW:
            break
        attempted.add(decision.selected_route)

    assert ExtractionMethod.VLM_FALLBACK not in routes
    assert routes[-1] == ExtractionMethod.HUMAN_REVIEW


def test_table_field_routes_through_table_transformer_before_vlm():
    router = ModelRouter(ThresholdRegistry([]), vlm_enabled=True)
    decision = router.decide(
        RouterInput(
            field_name="revenue_code",
            field_criticality=FieldCriticality.CRITICAL,
            ocr_confidence=0.1,
            is_table_field=True,
            attempted_methods=frozenset({ExtractionMethod.ALTERNATE_PREPROCESS_OCR}),
        )
    )
    assert decision.selected_route == ExtractionMethod.TABLE_TRANSFORMER


def test_unstructured_document_routes_through_layoutlmv3_before_vlm():
    router = ModelRouter(ThresholdRegistry([]), vlm_enabled=True)
    decision = router.decide(
        RouterInput(
            field_name="some_field",
            field_criticality=FieldCriticality.NON_CRITICAL,
            ocr_confidence=0.1,
            is_unstructured_document=True,
            attempted_methods=frozenset({ExtractionMethod.ALTERNATE_PREPROCESS_OCR}),
        )
    )
    assert decision.selected_route == ExtractionMethod.LAYOUTLMV3


def test_validation_failure_is_reflected_in_reason_codes():
    router = ModelRouter(_registry())
    decision = router.decide(
        RouterInput(
            field_name="provider_npi",
            field_criticality=FieldCriticality.CRITICAL,
            ocr_confidence=0.95,  # high confidence, but failed a deterministic check
            validation_failed=True,
        )
    )
    assert decision.selected_route == ExtractionMethod.ALTERNATE_PREPROCESS_OCR
    assert "validation_failed" in decision.reason_codes


def test_non_critical_field_has_a_lower_bar_than_critical():
    router = ModelRouter(ThresholdRegistry([]))  # falls back to criticality defaults
    critical_decision = router.decide(
        RouterInput(
            field_name="x", field_criticality=FieldCriticality.CRITICAL, ocr_confidence=0.8
        )
    )
    non_critical_decision = router.decide(
        RouterInput(
            field_name="x", field_criticality=FieldCriticality.NON_CRITICAL, ocr_confidence=0.8,
            evidence_policy_satisfied=True,
        )
    )
    assert critical_decision.selected_route == ExtractionMethod.ALTERNATE_PREPROCESS_OCR
    assert non_critical_decision.selected_route == ExtractionMethod.REGIONAL_PADDLEOCR


def test_estimated_cost_increases_with_escalation():
    router = ModelRouter(_registry(), vlm_enabled=True)
    alt_ocr = router.decide(
        RouterInput(field_name="provider_npi", field_criticality=FieldCriticality.CRITICAL, ocr_confidence=0.1)
    )
    vlm = router.decide(
        RouterInput(
            field_name="provider_npi",
            field_criticality=FieldCriticality.CRITICAL,
            ocr_confidence=0.1,
            attempted_methods=frozenset({ExtractionMethod.ALTERNATE_PREPROCESS_OCR}),
        )
    )
    assert vlm.estimated_cost_usd > alt_ocr.estimated_cost_usd
