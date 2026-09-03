"""Evidence-driven reconciliation with fail-closed C3 acceptance."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256

from packages.candidate_reconciliation.contracts import (
    Decision,
    EvidenceReference,
    ReconciliationResult,
)
from packages.confidence import CalibrationRegistry
from packages.criticality import CriticalityLevel
from packages.evidence.normalization import normalize_agreement_value
from packages.evidence_policy import EvidencePolicyRegistry
from packages.observability.metrics import field_reconciliation_total
from packages.ocr.contracts import OCRCandidate
from packages.ocr.independence import independence_group


class EvidenceReconciler:
    def __init__(
        self,
        calibration: CalibrationRegistry | None = None,
        accept_thresholds: dict[CriticalityLevel, float] | None = None,
        evidence_policies: EvidencePolicyRegistry | None = None,
        allow_authoritative_financial_e6: bool = False,
    ) -> None:
        self.calibration = calibration or CalibrationRegistry()
        self.thresholds = accept_thresholds or {
            CriticalityLevel.C0: 0.70,
            CriticalityLevel.C1: 0.80,
            CriticalityLevel.C2: 0.92,
            CriticalityLevel.C3: 0.98,
        }
        self.evidence_policies = evidence_policies or EvidencePolicyRegistry.load()
        self.allow_authoritative_financial_e6 = allow_authoritative_financial_e6

    @staticmethod
    def _candidate_id(candidate: OCRCandidate) -> str:
        if candidate.evidence_reference:
            return candidate.evidence_reference
        payload = (
            f"{candidate.engine}|{candidate.model_version}|{candidate.raw_value}|"
            f"{candidate.preprocessing_variant}"
        )
        return sha256(payload.encode()).hexdigest()[:24]

    def reconcile(
        self,
        field_name: str,
        candidates: list[OCRCandidate],
        criticality: CriticalityLevel,
        *,
        deterministic_evidence: set[str] | None = None,
        authoritative_value: str | None = None,
        authoritative_reference_verified: bool = False,
        authoritative_source: str | None = None,
        authoritative_version: str | None = None,
        document_family: str = "*",
        enforce_legacy_evidence_policy: bool = True,
        independent_agreement_values: set[str] | None = None,
    ) -> ReconciliationResult:
        deterministic = deterministic_evidence or set()
        groups: dict[str, list[tuple[OCRCandidate, float, str]]] = defaultdict(list)
        conflicts: list[EvidenceReference] = []
        for candidate in candidates:
            display_value = (candidate.value or "").strip()
            if not display_value:
                continue
            calibrated, version = self.calibration.calibrate(
                candidate.engine, field_name, candidate.raw_confidence
            )
            normalized = normalize_agreement_value(field_name, display_value)
            if normalized:
                groups[normalized].append((candidate, calibrated, version))
        ids = [self._candidate_id(candidate) for candidate in candidates]
        if not groups:
            return ReconciliationResult(
                field_name=field_name,
                selected_value=None,
                candidate_ids=ids,
                decision=Decision.ABSTAIN,
                confidence=0,
                rationale_codes=["NO_NONEMPTY_CANDIDATE"],
                calibration_model_version="none",
            )

        qualified_independent_values = (
            {
                normalize_agreement_value(field_name, item)
                for item in independent_agreement_values
            }
            if independent_agreement_values is not None
            else None
        )

        def independent_agreement(normalized_value, items) -> bool:
            if qualified_independent_values is not None:
                return normalized_value in qualified_independent_values
            return len({independence_group(c.engine) for c, _, _ in items}) >= 2

        ranked = sorted(
            groups.items(),
            key=lambda item: (
                independent_agreement(item[0], item[1]),
                max(score for _, score, _ in item[1]),
            ),
            reverse=True,
        )
        _normalized_value, supporting = ranked[0]
        value = max(supporting, key=lambda item: item[1])[0].value
        has_independent_agreement = independent_agreement(_normalized_value, supporting)
        calibrated = max(score for _, score, _ in supporting)
        agreement_bonus = 0.04 if has_independent_agreement else 0.0
        reference_match = (
            authoritative_reference_verified
            and authoritative_value is not None
            and (value or "").strip().casefold() == authoritative_value.strip().casefold()
        )
        reference_contradiction = (
            authoritative_reference_verified
            and authoritative_value is not None
            and (value or "").strip().casefold() != authoritative_value.strip().casefold()
        )
        deterministic_ok = (
            bool(
                deterministic
                & {
                    "CHECKSUM_VALID",
                    "REFERENCE_MATCH",
                    "CROSS_FIELD_CONSISTENT",
                    "CROSS_DOCUMENT_AGREEMENT",
                    "FINANCIAL_RECONCILIATION_VALID",
                    "CLAIM_TOTAL_CONFIRMED",
                    "DATE_RELATIONSHIP_CONFIRMED",
                }
            )
            or reference_match
        )
        financial_authority = bool(
            self.allow_authoritative_financial_e6
            and field_name in {"total_charge", "total_charges"}
            and deterministic
            & {
                "CLAIM_TOTAL_CONFIRMED",
                "FINANCIAL_RECONCILIATION_VALID",
                "LINE_TOTALS_RECONCILED",
            }
        )
        # A verified reference is an independent E5 authority, not an OCR
        # calibration shortcut. Exact candidate/reference agreement may use
        # the reference decision's governed confidence and provenance.
        confidence = 1.0 if reference_match or financial_authority else min(
            1.0, calibrated + agreement_bonus
        )
        evidence = [
            EvidenceReference(
                evidence_type="OCR_CANDIDATE",
                reference=self._candidate_id(candidate),
                source=candidate.engine,
                reason_code="ENGINE_SUPPORT",
            )
            for candidate, _, _ in supporting
        ]
        evidence.extend(
            EvidenceReference(
                evidence_type="DETERMINISTIC", reference=code, source="validation", reason_code=code
            )
            for code in sorted(deterministic)
        )
        if reference_match:
            evidence.append(
                EvidenceReference(
                    evidence_type="AUTHORITATIVE_REFERENCE",
                    reference=authoritative_version or "version-not-provided",
                    source=authoritative_source or "authorized-reference",
                    reason_code="REFERENCE_MATCH",
                )
            )
        elif reference_contradiction:
            conflicts.append(
                EvidenceReference(
                    evidence_type="AUTHORITATIVE_REFERENCE",
                    reference=authoritative_version or "version-not-provided",
                    source=authoritative_source or "authorized-reference",
                    reason_code="REFERENCE_CONTRADICTION",
                )
            )
        for other_value, items in ranked[1:]:
            conflicts.extend(
                EvidenceReference(
                    evidence_type="OCR_CANDIDATE",
                    reference=self._candidate_id(candidate),
                    source=candidate.engine,
                    reason_code=f"CONFLICTING_VALUE:{other_value}",
                )
                for candidate, _, _ in items
            )
        reasons = ["HARD_VALIDATION_PASSED"] if "HARD_VALIDATION_PASSED" in deterministic else []
        if has_independent_agreement:
            reasons.append("MULTI_ENGINE_AGREEMENT")
        if reference_match:
            reasons.append("REFERENCE_MATCH")
        reasons.extend(sorted(deterministic))
        signals = set(deterministic)
        if has_independent_agreement:
            signals.add("OCR_MULTI_ENGINE")
        if reference_match:
            signals.add("REFERENCE_MATCH")
        rule = self.evidence_policies.rule_for(document_family, field_name, criticality)
        policy_ok, missing_alternatives = rule.evaluate(signals)
        threshold = rule.threshold if rule.threshold is not None else self.thresholds[criticality]
        threshold_ok = confidence >= threshold
        # C3 always needs deterministic/authoritative evidence or two truly
        # independent engine families. Confidence is never sufficient alone.
        independent_evidence_ok = has_independent_agreement or deterministic_ok
        if reference_contradiction:
            decision = Decision.REVIEW
            reasons.append("REFERENCE_CONTRADICTION")
        elif not threshold_ok:
            decision = Decision.ESCALATE
            reasons.append("CALIBRATED_CONFIDENCE_BELOW_THRESHOLD")
        elif enforce_legacy_evidence_policy and not policy_ok:
            decision = Decision.REVIEW
            reasons.append("FIELD_EVIDENCE_POLICY_NOT_SATISFIED")
            reasons.extend(f"MISSING_ALTERNATIVE:{item}" for item in missing_alternatives)
        elif criticality is CriticalityLevel.C3 and not independent_evidence_ok:
            decision = Decision.REVIEW
            reasons.append("C3_INDEPENDENT_EVIDENCE_REQUIRED")
        elif len(ranked) > 1 and confidence - max(s for _, s, _ in ranked[1][1]) < 0.05:
            decision = Decision.REVIEW
            reasons.append("CONFLICT_MARGIN_TOO_SMALL")
        else:
            decision = (
                Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
            )
        versions = (
            [f"authoritative-reference:{authoritative_version or 'version-not-provided'}"]
            if reference_match
            else ["deterministic-financial-e6-v1"]
            if financial_authority
            else sorted({version for _, _, version in supporting})
        )
        result = ReconciliationResult(
            field_name=field_name,
            selected_value=value,
            candidate_ids=ids,
            decision=decision,
            confidence=confidence,
            supporting_evidence=evidence,
            conflicting_evidence=conflicts,
            rationale_codes=list(dict.fromkeys(reasons)),
            calibration_model_version=",".join(versions),
        )
        field_reconciliation_total.labels(
            field_name=field_name,
            criticality=criticality.value,
            decision=decision.value,
        ).inc()
        return result
