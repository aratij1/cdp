from __future__ import annotations

from packages.field_localization.contracts import FieldLocationEvidence, LocalizationStage
from packages.local_evidence_cascade import decide_local_candidate

from .contracts import WrongCropAssessment


class WrongCropDetector:
    """Calibrated, interpretable crop-risk combination.

    A detection is a review/blocking signal, never evidence that a competing
    candidate is correct.
    """

    version = "wrong-crop-detector-v1"
    threshold = .60

    def assess(self, location: FieldLocationEvidence, observed_text: str,
               datatype: str) -> WrongCropAssessment:
        signals: dict[str, float] = {
            "upstream": 1.0 if location.wrong_crop_suspected else 0.0,
            "unresolved": 1.0 if location.stage == LocalizationStage.UNRESOLVED else 0.0,
            "contract_unvalidated": .62 if (
                location.region_source == "ANCHOR_RELATIVE_CONTRACT"
            ) else 0.0,
            "empty": 1.0 if not (observed_text or "").strip() else 0.0,
            "semantic": 0.0,
            "label": 0.0,
            "geometry": max(0.0, .60 - float(location.geometry_confidence or 0)) / .60,
        }
        decision = decide_local_candidate(observed_text or "", datatype)
        # OCR invalidity alone is an extraction signal, not crop evidence.
        # It contributes only when the locator independently scored the
        # selected value span as semantically incompatible.
        if (observed_text and not decision.accepted
                and location.semantic_confidence is not None
                and location.semantic_confidence < .20
                and location.region_source != "ANCHOR_RELATIVE_CONTRACT"):
            signals["semantic"] = .82
        compact = "".join(character for character in (observed_text or "").upper()
                          if character.isalnum())
        labels = {
            "PATIENTNAME", "PROVIDERNAME", "MEMBERID", "TYPEOFBILL",
            "PRINCIPALDIAGNOSIS", "TOTALCHARGE", "NPI", "REV",
        }
        if compact in labels:
            signals["label"] = 1.0
        elif any(compact.startswith(label) for label in labels if len(compact) > len(label)):
            signals["label"] = .45
        risk = max(signals.values())
        reasons = tuple(
            f"WRONG_CROP_SIGNAL_{name.upper()}" for name, value in signals.items()
            if value >= self.threshold
        )
        return WrongCropAssessment(
            risk=risk, detected=risk >= self.threshold, threshold=self.threshold,
            signal_scores=signals, reason_codes=reasons, detector_version=self.version,
        )
