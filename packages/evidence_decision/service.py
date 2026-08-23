from __future__ import annotations

from pathlib import Path

from packages.candidate_reconciliation.contracts import Decision
from packages.candidate_reconciliation.reconciler import EvidenceReconciler
from packages.evidence import EvidencePolicy, build_evidence_bundle
from packages.evidence.builder import candidate_identifier, engine_family
from packages.evidence_decision.contracts import (
    DecisionContext,
    FieldDecision,
    FieldDisposition,
    NextAction,
)
from packages.evidence_router import (
    EvidenceAcquisitionAction,
    EvidenceGapRouter,
    ReferenceSourceState,
)
from packages.field_policy import FieldPolicyRegistry
from packages.route_registry import RouteRegistry

DEFAULT_OCR_ROUTES_PATH = Path(__file__).resolve().parents[2] / "config" / "ocr_field_routes.yaml"

_NEXT_ACTIONS = {
    EvidenceAcquisitionAction.ACCEPT: NextAction.NONE,
    EvidenceAcquisitionAction.PROPAGATE_EXISTING_EVIDENCE: NextAction.PROPAGATE_EXISTING_EVIDENCE,
    EvidenceAcquisitionAction.CROP_RECOVERY: NextAction.CROP_RECOVERY,
    EvidenceAcquisitionAction.DETERMINISTIC_VALIDATION: NextAction.DETERMINISTIC_VALIDATION,
    EvidenceAcquisitionAction.CROSS_FIELD_RECONCILIATION: NextAction.CROSS_FIELD_RECONCILIATION,
    EvidenceAcquisitionAction.SECONDARY_OCR: NextAction.SECONDARY_OCR,
    EvidenceAcquisitionAction.REFERENCE_LOOKUP: NextAction.REFERENCE_LOOKUP,
    EvidenceAcquisitionAction.CLOUD_AI: NextAction.CLOUD_AI,
    EvidenceAcquisitionAction.HUMAN_REVIEW: NextAction.HUMAN_REVIEW,
}


class EvidenceDecisionService:
    """Sole authority for machine field disposition."""

    def __init__(
        self,
        reconciler: EvidenceReconciler | None = None,
        evidence_policy: EvidencePolicy | None = None,
        field_policy: FieldPolicyRegistry | None = None,
        ocr_routes_path: str | Path = DEFAULT_OCR_ROUTES_PATH,
        route_mode: str = "runtime",
        route_registry: RouteRegistry | None = None,
    ) -> None:
        self.reconciler = reconciler or EvidenceReconciler()
        self.evidence_policy = evidence_policy or EvidencePolicy.load()
        self.field_policy = field_policy or FieldPolicyRegistry.load()
        self.gap_router = EvidenceGapRouter()
        self.policy_version = self.evidence_policy.version
        self.route_mode = route_mode
        self.route_registry = route_registry or RouteRegistry.load(ocr_routes_path)
        self.ocr_routes = {
            route.field: route.compatibility_spec()
            for route in self.route_registry.routes_for_mode(route_mode)
        }

    def decide(self, context: DecisionContext) -> FieldDecision:
        field_policy = self.field_policy.for_field(
            context.document_family,
            context.field_name,
        )
        route = self.route_registry.find_any(context.field_name, context.document_family)
        if route is None and field_policy.canonical_field_name != context.field_name:
            route = self.route_registry.find_any(
                field_policy.canonical_field_name,
                context.document_family,
            )
        candidates = list(context.candidates)
        rejected_route_ids: list[str] = []
        route_reasons: list[str] = []
        if route is not None and route not in self.route_registry.routes_for_mode(self.route_mode):
            eligible = [
                candidate
                for candidate in candidates
                if engine_family(candidate.engine) != engine_family(route.confirmation_engine)
            ]
            if len(eligible) != len(candidates):
                candidates = eligible
                rejected_route_ids.append(route.route_id)
                route_reasons.append(f"ROUTE_STATUS_REJECTED:{route.route_id}:{route.status.value}")
        bundle = build_evidence_bundle(
            field_name=context.field_name,
            candidates=candidates,
            registration_confidence=context.registration_confidence,
            wrong_crop_suspected=context.wrong_crop_suspected,
            deterministic_evidence=set(context.deterministic_evidence),
            deterministic_evidence_version=context.deterministic_evidence_version,
            hard_validation_passed=context.hard_validation_passed,
            reference=context.reference,
            cross_field_evidence=set(context.cross_field_evidence),
            structural_evidence_source=context.structural_evidence_source,
            structural_localization=context.structural_localization,
            reference_source_state=context.reference_source_state.value,
            route_id=(
                route.route_id
                if route
                else f"{context.document_family}.{context.field_name}.no-route"
            ),
            route_status=route.status.value if route else "DISABLED",
            route_mode=self.route_mode,
            rejected_route_ids=rejected_route_ids,
        )
        blocks_stp = field_policy.blocks_stp if context.blocks_stp is None else context.blocks_stp
        if context.requires_review_when_unresolved is None:
            review_unresolved = (
                False
                if context.blocks_stp is False
                else field_policy.requires_review_when_unresolved
            )
        else:
            review_unresolved = context.requires_review_when_unresolved
        policy_field_name = field_policy.canonical_field_name
        policy_satisfied, available, missing, gap_reasons = self.evidence_policy.evaluate(
            policy_field_name,
            context.criticality,
            bundle,
            context.document_family,
            reference_authorized=(
                context.reference_source_state is ReferenceSourceState.AUTHORIZED
            ),
        )
        policy_id, _ = self.evidence_policy.field_spec(
            context.document_family,
            policy_field_name,
            context.criticality,
        )
        bundle.policy_id = policy_id
        bundle.policy_version = self.evidence_policy.version
        bundle.missing_evidence_classes = set(missing)
        if not field_policy.configured:
            return self._terminal(
                context,
                FieldDisposition.HUMAN_REVIEW_REQUIRED,
                NextAction.HUMAN_REVIEW,
                ["FIELD_POLICY_NOT_CONFIGURED"],
                bundle=bundle,
                available=available,
                missing=missing,
            )
        if (
            context.wrong_crop_suspected
            or context.registration_confidence is not None
            and context.registration_confidence < 0.60
        ):
            return self._terminal(
                context,
                FieldDisposition.ESCALATE,
                NextAction.CROP_RECOVERY,
                [
                    "WRONG_CROP_SUSPECTED"
                    if context.wrong_crop_suspected
                    else "LOW_REGISTRATION_CONFIDENCE"
                ],
                bundle=bundle,
                available=available,
                missing=missing,
            )
        reference = context.reference
        if reference and (reference.contradiction or reference.conflicts):
            return self._terminal(
                context,
                FieldDisposition.HUMAN_REVIEW_REQUIRED,
                NextAction.HUMAN_REVIEW,
                ["REFERENCE_CONTRADICTION"],
                bundle=bundle,
                available=available,
                missing=missing,
            )
        deterministic = set(context.deterministic_evidence) | set(context.cross_field_evidence)
        if context.hard_validation_passed:
            deterministic.add("HARD_VALIDATION_PASSED")
        result = self.reconciler.reconcile(
            context.field_name,
            candidates,
            context.criticality,
            deterministic_evidence=deterministic,
            authoritative_value=reference.value if reference else None,
            authoritative_reference_verified=bool(reference and reference.verified),
            authoritative_source=reference.source if reference else None,
            authoritative_version=reference.version if reference else None,
            document_family=context.document_family,
            enforce_legacy_evidence_policy=False,
        )
        selected_candidates = [
            candidate
            for candidate in candidates
            if (candidate.value or "").strip().casefold()
            == (result.selected_value or "").strip().casefold()
        ]
        if selected_candidates:
            selected = max(selected_candidates, key=lambda item: item.raw_confidence)
            bundle.selected_candidate_id = candidate_identifier(selected)
            bundle.candidate_value = selected.value
        if not context.hard_validation_passed:
            if not candidates or not any(candidate.value for candidate in candidates):
                action = NextAction.CROP_RECOVERY
                reasons = [*result.rationale_codes, "EMPTY_CROP", *gap_reasons, *route_reasons]
            else:
                action, next_reasons = self._next_action(context, available, missing)
                reasons = [
                    *result.rationale_codes,
                    "INVALID_FORMAT",
                    *gap_reasons,
                    *route_reasons,
                    *next_reasons,
                ]
            if not blocks_stp and not review_unresolved:
                disposition, action = FieldDisposition.UNRESOLVED_NON_BLOCKING, NextAction.NONE
                reasons = [*reasons, "NON_BLOCKING_FIELD"]
            else:
                disposition = FieldDisposition.ESCALATE
        elif result.decision is Decision.ACCEPT and policy_satisfied:
            disposition, action, reasons = (
                FieldDisposition.AUTO_ACCEPTED,
                NextAction.NONE,
                [*result.rationale_codes, *route_reasons],
            )
        elif result.decision is Decision.REFERENCE_CONFIRMED and policy_satisfied:
            disposition, action, reasons = (
                FieldDisposition.REFERENCE_CONFIRMED,
                NextAction.NONE,
                [*result.rationale_codes, *route_reasons],
            )
        elif result.decision in {Decision.ACCEPT, Decision.REFERENCE_CONFIRMED}:
            action, next_reasons = self._next_action(context, available, missing)
            disposition = (
                FieldDisposition.ESCALATE
                if action is not NextAction.HUMAN_REVIEW
                else FieldDisposition.HUMAN_REVIEW_REQUIRED
            )
            reasons = [*result.rationale_codes, *gap_reasons, *route_reasons, *next_reasons]
        elif not blocks_stp and not review_unresolved:
            disposition, action = FieldDisposition.UNRESOLVED_NON_BLOCKING, NextAction.NONE
            reasons = [*result.rationale_codes, "NON_BLOCKING_FIELD", *route_reasons]
        elif result.decision is Decision.ESCALATE and policy_satisfied:
            disposition, action = FieldDisposition.HUMAN_REVIEW_REQUIRED, NextAction.HUMAN_REVIEW
            reasons = [
                *result.rationale_codes,
                "CALIBRATION_OR_AMBIGUITY_REQUIRES_REVIEW",
                *route_reasons,
            ]
        elif result.decision is Decision.ESCALATE:
            action, next_reasons = self._next_action(context, available, missing)
            disposition = (
                FieldDisposition.ESCALATE
                if action is not NextAction.HUMAN_REVIEW
                else FieldDisposition.HUMAN_REVIEW_REQUIRED
            )
            reasons = [*result.rationale_codes, *gap_reasons, *route_reasons, *next_reasons]
        elif result.decision is Decision.ABSTAIN:
            disposition, action = FieldDisposition.INSUFFICIENT_EVIDENCE, NextAction.HUMAN_REVIEW
            reasons = [*result.rationale_codes, *gap_reasons, *route_reasons]
        else:
            disposition, action = FieldDisposition.HUMAN_REVIEW_REQUIRED, NextAction.HUMAN_REVIEW
            reasons = [*result.rationale_codes, *gap_reasons, *route_reasons]
        return FieldDecision(
            field_id=context.field_id,
            field_name=context.field_name,
            selected_value=result.selected_value,
            disposition=disposition,
            calibrated_probability=result.confidence,
            candidate_ids=result.candidate_ids,
            supporting_evidence=result.supporting_evidence,
            conflicting_evidence=result.conflicting_evidence,
            reason_codes=list(dict.fromkeys(reasons)),
            next_action=action,
            policy_version=self.policy_version,
            evidence_bundle=bundle,
            available_evidence=list(available),
            missing_evidence=list(missing),
            criticality=field_policy.criticality,
            required=field_policy.required,
            blocks_stp=blocks_stp,
            requires_review_when_unresolved=review_unresolved,
        )

    def _next_action(
        self, context: DecisionContext, available, missing
    ) -> tuple[NextAction, list[str]]:
        requirements = tuple(
            frozenset(item.value for item in option)
            for option in self.evidence_policy.requirements(
                self.field_policy.canonical_name(
                    context.document_family,
                    context.field_name,
                ),
                context.criticality,
                context.document_family,
            )
        )
        route = self.ocr_routes.get(context.field_name, {})
        if route and route.get("document_family", "*").upper() not in {
            "*",
            context.document_family.upper(),
        }:
            route = {}
        decision = self.gap_router.route(
            available=set(available),
            requirements=requirements,
            propagatable=set(context.propagatable_evidence),
            reference_state=context.reference_source_state,
            confirmation_engine=route.get("confirmation"),
        )
        return _NEXT_ACTIONS[decision.action], decision.reason_codes

    def _terminal(
        self,
        context: DecisionContext,
        disposition: FieldDisposition,
        action: NextAction,
        reasons: list[str],
        *,
        bundle=None,
        available=(),
        missing=(),
    ) -> FieldDecision:
        field_policy = self.field_policy.for_field(
            context.document_family,
            context.field_name,
        )
        return FieldDecision(
            field_id=context.field_id,
            field_name=context.field_name,
            disposition=disposition,
            calibrated_probability=0,
            reason_codes=reasons,
            next_action=action,
            policy_version=self.policy_version,
            evidence_bundle=bundle,
            available_evidence=list(available),
            missing_evidence=list(missing),
            criticality=field_policy.criticality,
            required=field_policy.required if context.required is None else context.required,
            blocks_stp=field_policy.blocks_stp
            if context.blocks_stp is None
            else context.blocks_stp,
            requires_review_when_unresolved=(
                field_policy.requires_review_when_unresolved
                if context.requires_review_when_unresolved is None
                else context.requires_review_when_unresolved
            ),
        )
