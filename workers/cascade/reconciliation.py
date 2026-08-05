"""Deterministic candidate scoring and controlled field disposition."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from packages.domain.enums import FieldCriticality
from packages.ocr.contracts import OCRCandidate


class FieldDisposition(StrEnum):
    VALIDATED_AUTOMATICALLY = "VALIDATED_AUTOMATICALLY"
    VERIFIED_BY_HUMAN = "VERIFIED_BY_HUMAN"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


@dataclass(frozen=True)
class CalibrationParameters:
    slope: float = 1.0
    intercept: float = 0.0

    def calibrate(self, probability: float) -> float:
        p = min(max(probability, 1e-6), 1 - 1e-6)
        logit = math.log(p / (1 - p))
        return 1 / (1 + math.exp(-(self.slope * logit + self.intercept)))


@dataclass(frozen=True)
class ReconciliationResult:
    selected: OCRCandidate | None
    disposition: FieldDisposition
    reasons: tuple[str, ...]
    rejected: tuple[tuple[OCRCandidate, str], ...]


class CandidateReconciler:
    def __init__(
        self,
        validator: Callable[[str], bool],
        calibration: dict[tuple[str, str], CalibrationParameters] | None = None,
        minimum_score: float = 0.80,
    ) -> None:
        self._validator = validator
        self._calibration = calibration or {}
        self._minimum_score = minimum_score

    def reconcile(
        self,
        candidates: list[OCRCandidate],
        criticality: FieldCriticality,
        field_name: str = "*",
        authoritative_value: str | None = None,
        alignment_score: float = 1.0,
    ) -> ReconciliationResult:
        valid: list[tuple[OCRCandidate, float]] = []
        rejected: list[tuple[OCRCandidate, str]] = []
        for candidate in candidates:
            value = (candidate.value or "").strip()
            if not value:
                rejected.append((candidate, "empty_candidate"))
                continue
            if not self._validator(value):
                rejected.append((candidate, "hard_validation_failed"))
                continue
            calibration = self._calibration.get(
                (candidate.engine, field_name),
                CalibrationParameters(),
            )
            calibrated = (
                candidate.calibrated_confidence
                if candidate.calibrated_confidence is not None
                else calibration.calibrate(candidate.raw_confidence)
            )
            agreement = len(
                {item.engine for item in candidates if item.value == candidate.value}
            )
            reference_match = authoritative_value is not None and value == authoritative_value
            score = (
                0.55 * calibrated
                + 0.2 * min(agreement / 2, 1)
                + 0.15 * float(reference_match)
                + 0.1 * max(min(alignment_score, 1), 0)
            )
            valid.append((candidate, score))

        if not valid:
            return ReconciliationResult(
                None,
                FieldDisposition.HUMAN_REVIEW_REQUIRED,
                ("no_candidate_passed_hard_validation",),
                tuple(rejected),
            )
        selected, score = max(valid, key=lambda item: item[1])
        agreeing_engines = {
            item.engine for item, _ in valid if item.value == selected.value
        }
        reference_verified = (
            authoritative_value is not None and selected.value == authoritative_value
        )
        critical_evidence_ok = len(agreeing_engines) >= 2 or reference_verified
        if score < self._minimum_score:
            reason = f"candidate_score_below_threshold:{score:.3f}"
        elif criticality is FieldCriticality.CRITICAL and not critical_evidence_ok:
            reason = "critical_field_requires_two_engines_or_authoritative_reference"
        else:
            return ReconciliationResult(
                selected,
                FieldDisposition.VALIDATED_AUTOMATICALLY,
                (f"selected_score:{score:.3f}",),
                tuple(rejected),
            )
        return ReconciliationResult(
            selected,
            FieldDisposition.HUMAN_REVIEW_REQUIRED,
            (reason,),
            tuple(rejected),
        )


def claim_can_finalize(dispositions: dict[str, FieldDisposition], critical_fields: set[str]) -> bool:
    terminal = {
        FieldDisposition.VALIDATED_AUTOMATICALLY,
        FieldDisposition.VERIFIED_BY_HUMAN,
    }
    return all(dispositions.get(field) in terminal for field in critical_fields)
