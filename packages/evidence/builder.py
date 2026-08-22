from __future__ import annotations

from collections import defaultdict

from packages.evidence.models import EvidenceBundle, EvidenceClass, EvidenceItem
from packages.ocr.contracts import OCRCandidate


def engine_family(engine: str) -> str:
    value = engine.casefold()
    if "rapid" in value or "onnx" in value:
        return "RAPID_ONNX_FAMILY"
    if "paddle" in value or "ppocr" in value:
        return "PADDLE_FAMILY"
    if "tesseract" in value:
        return "TESSERACT_FAMILY"
    if any(item in value for item in ("gemini", "textract", "azure", "vlm", "cloud")):
        return "CLOUD_AI_FAMILY"
    return value.upper() or "UNKNOWN_ENGINE_FAMILY"


def build_evidence_bundle(*, field_name: str, candidates: list[OCRCandidate],
                          registration_confidence: float, wrong_crop_suspected: bool,
                          deterministic_evidence: set[str], hard_validation_passed: bool,
                          reference=None, cross_field_evidence: set[str] | None = None) -> EvidenceBundle:
    populated = [candidate for candidate in candidates if candidate.value]
    selected = max(populated, key=lambda item: item.raw_confidence, default=None)
    bundle = EvidenceBundle(field_name=field_name, candidate_value=selected.value if selected else None)
    if not populated:
        bundle.items.append(EvidenceItem(evidence_class=EvidenceClass.E0, evidence_type="NO_EXTRACTION_EVIDENCE",
                                         evidence_family="NO_EVIDENCE", source="pipeline"))
    by_value: dict[str, set[str]] = defaultdict(set)
    for candidate in populated:
        family = engine_family(candidate.engine)
        candidate_id = candidate.evidence_reference
        bundle.items.append(EvidenceItem(
            evidence_class=EvidenceClass.E7 if family == "CLOUD_AI_FAMILY" else EvidenceClass.E1,
            evidence_type="AI_EXTRACTION" if family == "CLOUD_AI_FAMILY" else "OCR_EXTRACTION",
            evidence_family=family, source=candidate.engine, value=candidate.value,
            supports_candidate_id=candidate_id, confidence=candidate.raw_confidence,
            independent=True, metadata={"preprocessing_variant": candidate.preprocessing_variant},
        ))
        by_value[candidate.value.strip().casefold()].add(family)
    for value, families in by_value.items():
        local = families - {"CLOUD_AI_FAMILY"}
        if len(local) >= 2:
            bundle.items.append(EvidenceItem(
                evidence_class=EvidenceClass.E2, evidence_type="MULTI_ENGINE_AGREEMENT",
                evidence_family="INDEPENDENT_OCR_AGREEMENT", source="evidence_builder",
                value=value, independent=True, metadata={"engines": sorted(local), "agreement_type": "NORMALIZED_EXACT"},
            ))
    if registration_confidence >= .80 and not wrong_crop_suspected:
        bundle.items.append(EvidenceItem(
            evidence_class=EvidenceClass.E3, evidence_type="REGISTRATION_CONFIRMED",
            evidence_family="PAGE_GEOMETRY", source="registration",
            confidence=registration_confidence, deterministic=True,
        ))
    facts = set(deterministic_evidence)
    if hard_validation_passed:
        facts.add("HARD_VALIDATION_PASSED")
    for fact in sorted(facts):
        bundle.items.append(EvidenceItem(
            evidence_class=EvidenceClass.E4, evidence_type=fact,
            evidence_family=f"DETERMINISTIC:{fact}", source="validation", deterministic=True,
        ))
    if reference and reference.verified and not reference.contradiction:
        bundle.items.append(EvidenceItem(
            evidence_class=EvidenceClass.E5, evidence_type="REFERENCE_CONFIRMED",
            evidence_family=f"REFERENCE:{reference.source or 'unknown'}", source=reference.source or "reference",
            value=reference.value, authoritative=True, version=reference.version,
            metadata={"matching_attributes": reference.matched_attributes, "conflicts": reference.conflicts},
        ))
    for fact in sorted(cross_field_evidence or set()):
        bundle.items.append(EvidenceItem(
            evidence_class=EvidenceClass.E6, evidence_type=fact,
            evidence_family=f"CROSS_FIELD:{fact}", source="claim_reconciliation", deterministic=True,
        ))
    return bundle
