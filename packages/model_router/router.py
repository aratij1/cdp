"""The hybrid model router: a pure decision function (no model calls, no
I/O) that picks the next extraction stage for one field, following the
escalation order in docs/ARCHITECTURE.md §9:

    cache -> template rules -> OpenCV alignment -> regional PaddleOCR
    -> deterministic validation -> alternate preprocessing/OCR (failed
    fields only) -> LayoutLMv3 / Table Transformer / TrOCR -> compact VLM
    (failed crops only) -> human review

Steps 1-4 are assumed already attempted by the standard extraction path
before the router is ever called for a field (see `inputs.py`); `decide`
starts from "this field still isn't good enough" and either accepts it
(if it turns out to already meet the bar) or picks exactly one next step,
skipping anything already in `RouterInput.attempted_methods`. The VLM step
is only reachable after alternate-OCR (and, where applicable, LayoutLMv3/
Table Transformer) have already been tried and failed -- "do not invoke
the VLM for every claim" is structural here, not a comment.
"""

from __future__ import annotations

from packages.domain.enums import ExtractionMethod
from packages.domain.routing import ModelDecision
from packages.model_router.cost_table import DEFAULT_COST_TABLE, estimated_cost
from packages.model_router.inputs import RouterInput
from packages.validation_rules.thresholds import ThresholdRegistry


class ModelRouter:
    def __init__(
        self,
        threshold_registry: ThresholdRegistry | None = None,
        cost_table: dict[ExtractionMethod, float] | None = None,
        vlm_enabled: bool = False,
    ) -> None:
        self._thresholds = threshold_registry or ThresholdRegistry([])
        self._cost_table = cost_table or DEFAULT_COST_TABLE
        self._vlm_enabled = vlm_enabled

    def decide(self, router_input: RouterInput) -> ModelDecision:
        if router_input.cache_hit:
            return self._decision(router_input, ExtractionMethod.CACHE_HIT, ["cache_hit"])

        min_confidence = self._thresholds.min_confidence_for(
            router_input.field_name, router_input.field_criticality
        )
        already_passed = (
            router_input.evidence_policy_satisfied
            and not router_input.validation_failed
            and not router_input.ocr_disagreement
            and router_input.ocr_confidence >= min_confidence
        )
        if already_passed:
            return self._decision(
                router_input, ExtractionMethod.REGIONAL_PADDLEOCR, ["passed_initial_extraction"]
            )

        for method in self._escalation_order(router_input):
            if method in router_input.attempted_methods:
                continue
            if method is ExtractionMethod.VLM_FALLBACK and not (
                self._vlm_enabled and router_input.vlm_enabled
            ):
                continue  # VLM disabled by config -- skip straight past it
            return self._decision(router_input, method, self._reason_codes(router_input, method))

        return self._decision(
            router_input, ExtractionMethod.HUMAN_REVIEW, ["all_automated_stages_exhausted"]
        )

    def _escalation_order(self, router_input: RouterInput) -> list[ExtractionMethod]:
        order = [ExtractionMethod.ALTERNATE_PREPROCESS_OCR]
        if router_input.is_table_field:
            order.append(ExtractionMethod.TABLE_TRANSFORMER)
        if router_input.is_unstructured_document:
            order.append(ExtractionMethod.LAYOUTLMV3)
        order.append(ExtractionMethod.VLM_FALLBACK)
        order.append(ExtractionMethod.HUMAN_REVIEW)
        return order

    def _reason_codes(self, router_input: RouterInput, method: ExtractionMethod) -> list[str]:
        codes = []
        if router_input.validation_failed:
            codes.append("validation_failed")
        if router_input.ocr_disagreement:
            codes.append("ocr_disagreement")
        if not codes:
            codes.append("low_ocr_confidence")
        codes.append(f"escalate_to_{method.value.lower()}")
        return codes

    def _decision(
        self, router_input: RouterInput, method: ExtractionMethod, reason_codes: list[str]
    ) -> ModelDecision:
        return ModelDecision(
            field_name=router_input.field_name,
            selected_route=method,
            reason_codes=reason_codes,
            estimated_cost_usd=estimated_cost(method, self._cost_table),
            escalation_count=len(router_input.attempted_methods),
        )
