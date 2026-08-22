from __future__ import annotations

from packages.candidate_reconciliation.contracts import Decision
from packages.candidate_reconciliation.reconciler import EvidenceReconciler
from packages.evidence_decision.contracts import (
    DecisionContext, FieldDecision, FieldDisposition, NextAction,
)
from packages.evidence import EvidenceGapRouter, EvidencePolicy, build_evidence_bundle


class EvidenceDecisionService:
    """Sole authority for machine field disposition."""

    def __init__(self, reconciler: EvidenceReconciler | None = None,
                 evidence_policy: EvidencePolicy | None = None) -> None:
        self.reconciler = reconciler or EvidenceReconciler()
        self.evidence_policy = evidence_policy or EvidencePolicy.load()
        self.gap_router = EvidenceGapRouter()
        self.policy_version = self.reconciler.evidence_policies.version

    def decide(self, context: DecisionContext) -> FieldDecision:
        bundle = build_evidence_bundle(
            field_name=context.field_name, candidates=context.candidates,
            registration_confidence=context.registration_confidence,
            wrong_crop_suspected=context.wrong_crop_suspected,
            deterministic_evidence=set(context.deterministic_evidence),
            hard_validation_passed=context.hard_validation_passed,
            reference=context.reference, cross_field_evidence=set(context.cross_field_evidence),
        )
        policy_satisfied, available, missing, gap_reasons = self.evidence_policy.evaluate(
            context.field_name, context.criticality, bundle
        )
        if context.wrong_crop_suspected or context.registration_confidence < 0.60:
            return self._terminal(
                context, FieldDisposition.ESCALATE, NextAction.CROP_RECOVERY,
                ["WRONG_CROP_SUSPECTED" if context.wrong_crop_suspected else "LOW_REGISTRATION_CONFIDENCE"],
                bundle=bundle, available=available, missing=missing,
            )
        reference = context.reference
        if reference and (reference.contradiction or reference.conflicts):
            return self._terminal(
                context, FieldDisposition.HUMAN_REVIEW_REQUIRED, NextAction.HUMAN_REVIEW,
                ["REFERENCE_CONTRADICTION"],
                bundle=bundle, available=available, missing=missing,
            )
        deterministic = set(context.deterministic_evidence) | set(context.cross_field_evidence)
        if context.hard_validation_passed:
            deterministic.add("HARD_VALIDATION_PASSED")
        result = self.reconciler.reconcile(
            context.field_name, context.candidates, context.criticality,
            deterministic_evidence=deterministic,
            authoritative_value=reference.value if reference else None,
            authoritative_reference_verified=bool(reference and reference.verified),
            authoritative_source=reference.source if reference else None,
            authoritative_version=reference.version if reference else None,
            document_family=context.document_family,
        )
        if not context.hard_validation_passed:
            if not context.candidates or not any(candidate.value for candidate in context.candidates):
                action = NextAction.CROP_RECOVERY
                reasons = [*result.rationale_codes, "EMPTY_CROP", *gap_reasons]
            else:
                opportunity = self.gap_router.route(missing)
                action = NextAction(opportunity.action)
                reasons = [*result.rationale_codes, "INVALID_FORMAT", *gap_reasons]
            disposition = FieldDisposition.ESCALATE
        elif result.decision is Decision.ACCEPT and policy_satisfied:
            disposition, action, reasons = FieldDisposition.AUTO_ACCEPTED, NextAction.NONE, result.rationale_codes
        elif result.decision is Decision.REFERENCE_CONFIRMED and policy_satisfied:
            disposition, action, reasons = FieldDisposition.REFERENCE_CONFIRMED, NextAction.NONE, result.rationale_codes
        elif result.decision in {Decision.ACCEPT, Decision.REFERENCE_CONFIRMED}:
            opportunity = self.gap_router.route(missing)
            action = NextAction(opportunity.action)
            disposition = FieldDisposition.ESCALATE if action is not NextAction.HUMAN_REVIEW else FieldDisposition.HUMAN_REVIEW_REQUIRED
            reasons = [*result.rationale_codes, *gap_reasons]
        elif not context.blocks_stp and context.criticality.value in {"C0", "C1"}:
            disposition, action = FieldDisposition.UNRESOLVED_NON_BLOCKING, NextAction.NONE
            reasons = [*result.rationale_codes, "NON_BLOCKING_FIELD"]
        elif result.decision is Decision.ESCALATE:
            opportunity = self.gap_router.route(missing)
            disposition, action = FieldDisposition.ESCALATE, NextAction(opportunity.action)
            reasons = [*result.rationale_codes, *gap_reasons]
        elif result.decision is Decision.ABSTAIN:
            disposition, action = FieldDisposition.INSUFFICIENT_EVIDENCE, NextAction.HUMAN_REVIEW
            reasons = [*result.rationale_codes, *gap_reasons]
        else:
            disposition, action = FieldDisposition.HUMAN_REVIEW_REQUIRED, NextAction.HUMAN_REVIEW
            reasons = [*result.rationale_codes, *gap_reasons]
        return FieldDecision(
            field_name=context.field_name, selected_value=result.selected_value,
            disposition=disposition, calibrated_probability=result.confidence,
            candidate_ids=result.candidate_ids, supporting_evidence=result.supporting_evidence,
            conflicting_evidence=result.conflicting_evidence,
            reason_codes=list(dict.fromkeys(reasons)), next_action=action,
            policy_version=self.policy_version, evidence_bundle=bundle,
            available_evidence=list(available), missing_evidence=list(missing),
        )

    def _terminal(
        self, context: DecisionContext, disposition: FieldDisposition,
        action: NextAction, reasons: list[str],
        *, bundle=None, available=(), missing=(),
    ) -> FieldDecision:
        return FieldDecision(
            field_name=context.field_name, disposition=disposition,
            calibrated_probability=0, reason_codes=reasons, next_action=action,
            policy_version=self.policy_version, evidence_bundle=bundle,
            available_evidence=list(available), missing_evidence=list(missing),
        )
