from __future__ import annotations

from packages.candidate_reconciliation.contracts import Decision
from packages.candidate_reconciliation.reconciler import EvidenceReconciler
from packages.evidence_decision.contracts import (
    DecisionContext, FieldDecision, FieldDisposition, NextAction,
)


class EvidenceDecisionService:
    """Sole authority for machine field disposition."""

    def __init__(self, reconciler: EvidenceReconciler | None = None) -> None:
        self.reconciler = reconciler or EvidenceReconciler()
        self.policy_version = self.reconciler.evidence_policies.version

    def decide(self, context: DecisionContext) -> FieldDecision:
        if context.wrong_crop_suspected or context.registration_confidence < 0.60:
            return self._terminal(
                context, FieldDisposition.ESCALATE, NextAction.CROP_RECOVERY,
                ["WRONG_CROP_SUSPECTED" if context.wrong_crop_suspected else "LOW_REGISTRATION"],
            )
        reference = context.reference
        if reference and (reference.contradiction or reference.conflicts):
            return self._terminal(
                context, FieldDisposition.HUMAN_REVIEW_REQUIRED, NextAction.HUMAN_REVIEW,
                ["REFERENCE_CONTRADICTION"],
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
            disposition, action = FieldDisposition.ESCALATE, NextAction.SECONDARY_OCR
            reasons = [*result.rationale_codes, "HARD_VALIDATION_FAILED"]
        elif result.decision is Decision.ACCEPT:
            disposition, action, reasons = FieldDisposition.AUTO_ACCEPTED, NextAction.NONE, result.rationale_codes
        elif result.decision is Decision.REFERENCE_CONFIRMED:
            disposition, action, reasons = FieldDisposition.REFERENCE_CONFIRMED, NextAction.NONE, result.rationale_codes
        elif not context.blocks_stp and context.criticality.value in {"C0", "C1"}:
            disposition, action = FieldDisposition.UNRESOLVED_NON_BLOCKING, NextAction.NONE
            reasons = [*result.rationale_codes, "NON_BLOCKING_FIELD"]
        elif result.decision is Decision.ESCALATE:
            disposition, action, reasons = FieldDisposition.ESCALATE, NextAction.SECONDARY_OCR, result.rationale_codes
        elif result.decision is Decision.ABSTAIN:
            disposition, action, reasons = FieldDisposition.INSUFFICIENT_EVIDENCE, NextAction.HUMAN_REVIEW, result.rationale_codes
        else:
            disposition, action, reasons = FieldDisposition.HUMAN_REVIEW_REQUIRED, NextAction.HUMAN_REVIEW, result.rationale_codes
        return FieldDecision(
            field_name=context.field_name, selected_value=result.selected_value,
            disposition=disposition, calibrated_probability=result.confidence,
            candidate_ids=result.candidate_ids, supporting_evidence=result.supporting_evidence,
            conflicting_evidence=result.conflicting_evidence,
            reason_codes=list(dict.fromkeys(reasons)), next_action=action,
            policy_version=self.policy_version,
        )

    def _terminal(
        self, context: DecisionContext, disposition: FieldDisposition,
        action: NextAction, reasons: list[str],
    ) -> FieldDecision:
        return FieldDecision(
            field_name=context.field_name, disposition=disposition,
            calibrated_probability=0, reason_codes=reasons, next_action=action,
            policy_version=self.policy_version,
        )
