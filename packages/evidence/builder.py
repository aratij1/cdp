from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from packages.evidence.models import (
    EvidenceClass,
    EvidenceItem,
    FieldEvidenceBundle,
    StructuralLocalizationEvidence,
)
from packages.evidence.normalization import normalize_agreement_value
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


def candidate_identifier(candidate: OCRCandidate) -> str:
    if candidate.evidence_reference:
        return candidate.evidence_reference
    payload = (
        f"{candidate.engine}|{candidate.model_version}|{candidate.raw_value}|"
        f"{candidate.preprocessing_variant}"
    )
    return sha256(payload.encode()).hexdigest()[:24]


def build_evidence_bundle(
    *,
    field_name: str,
    candidates: list[OCRCandidate],
    registration_confidence: float | None,
    wrong_crop_suspected: bool,
    deterministic_evidence: set[str],
    hard_validation_passed: bool,
    deterministic_evidence_version: str | None = None,
    reference=None,
    cross_field_evidence: set[str] | None = None,
    structural_evidence_source: str | None = None,
    structural_localization: StructuralLocalizationEvidence | None = None,
    reference_source_state: str = "DISABLED",
    route_id: str | None = None,
    route_status: str | None = None,
    route_mode: str | None = None,
    rejected_route_ids: list[str] | None = None,
) -> FieldEvidenceBundle:
    populated = [candidate for candidate in candidates if candidate.value]
    selected = max(populated, key=lambda item: item.raw_confidence, default=None)
    candidate_ids = [candidate_identifier(candidate) for candidate in candidates]
    bundle = FieldEvidenceBundle(
        field_name=field_name,
        route_id=route_id,
        route_status=route_status,
        route_mode=route_mode,
        rejected_route_ids=rejected_route_ids or [],
        candidate_value=selected.value if selected else None,
        selected_candidate_id=candidate_identifier(selected) if selected else None,
        candidate_ids=candidate_ids,
    )
    if not populated:
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E0,
                evidence_type="NO_EXTRACTION_EVIDENCE",
                evidence_family="NO_EVIDENCE",
                source="pipeline",
            )
        )
    by_value: dict[str, set[str]] = defaultdict(set)
    for candidate in populated:
        family = engine_family(candidate.engine)
        candidate_id = candidate_identifier(candidate)
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E7
                if family == "CLOUD_AI_FAMILY"
                else EvidenceClass.E1,
                evidence_type="AI_EXTRACTION" if family == "CLOUD_AI_FAMILY" else "OCR_EXTRACTION",
                evidence_family=family,
                source=candidate.engine,
                value=candidate.value,
                supports_candidate_id=candidate_id,
                confidence=candidate.raw_confidence,
                independent=True,
                metadata={"preprocessing_variant": candidate.preprocessing_variant},
            )
        )
        normalized = normalize_agreement_value(field_name, candidate.value)
        if normalized:
            by_value[normalized].add(family)
    for value, families in by_value.items():
        local = families - {"CLOUD_AI_FAMILY"}
        if len(local) >= 2:
            bundle.items.append(
                EvidenceItem(
                    evidence_class=EvidenceClass.E2,
                    evidence_type="MULTI_ENGINE_AGREEMENT",
                    evidence_family="INDEPENDENT_OCR_AGREEMENT",
                    source="evidence_builder",
                    value=value,
                    independent=True,
                    metadata={
                        "engines": sorted(local),
                        "agreement_type": "FIELD_AWARE_NORMALIZED_EXACT",
                    },
                )
            )
    if structural_localization is not None:
        if structural_localization.confirmed and not wrong_crop_suspected:
            bundle.items.append(
                EvidenceItem(
                    evidence_class=EvidenceClass.E3,
                    evidence_type=structural_localization.evidence_type.value,
                    evidence_family="STRUCTURAL_LOCALIZATION",
                    source=structural_localization.source,
                    confidence=structural_localization.confidence,
                    deterministic=True,
                    version=structural_localization.version,
                    metadata={"reason_codes": list(structural_localization.reason_codes)},
                )
            )
    elif (
        registration_confidence is not None
        and registration_confidence >= 0.80
        and not wrong_crop_suspected
    ):
        # Compatibility behavior for persisted pre-Phase-8.4 contexts. New
        # runtime/replay contexts must pass qualified structural evidence.
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E3,
                evidence_type="REGISTRATION_CONFIRMED",
                evidence_family="PAGE_GEOMETRY",
                source=structural_evidence_source or "registration",
                confidence=registration_confidence,
                deterministic=True,
                metadata={
                    "structural_source": structural_evidence_source or "MEASURED_REGISTRATION"
                },
            )
        )
    facts = set(deterministic_evidence)
    if hard_validation_passed:
        facts.add("HARD_VALIDATION_PASSED")
    for fact in sorted(facts):
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E4,
                evidence_type=fact,
                evidence_family=f"DETERMINISTIC:{fact}",
                source="validation",
                deterministic=True,
                version=deterministic_evidence_version,
                metadata={"validation_result": "PASS"},
            )
        )
    if (
        reference
        and reference.verified
        and not reference.contradiction
        and reference_source_state == "AUTHORIZED"
    ):
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E5,
                evidence_type="REFERENCE_CONFIRMED",
                evidence_family=f"REFERENCE:{reference.source or 'unknown'}",
                source=reference.source or "reference",
                value=reference.value,
                authoritative=True,
                version=reference.version,
                metadata={
                    "matching_attributes": reference.matched_attributes,
                    "conflicts": reference.conflicts,
                },
            )
        )
    elif reference and (reference.contradiction or reference.conflicts):
        bundle.contradictions.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E5,
                evidence_type="REFERENCE_CONTRADICTION",
                evidence_family=f"REFERENCE:{reference.source or 'unknown'}",
                source=reference.source or "reference",
                value=reference.value,
                authoritative=True,
                version=reference.version,
                metadata={
                    "matching_attributes": reference.matched_attributes,
                    "conflicts": reference.conflicts,
                },
            )
        )
    for fact in sorted(cross_field_evidence or set()):
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E6,
                evidence_type=fact,
                evidence_family=f"CROSS_FIELD:{fact}",
                source="claim_reconciliation",
                deterministic=True,
            )
        )
    for index, item in enumerate([*bundle.items, *bundle.contradictions]):
        item.evidence_id = uuid5(
            NAMESPACE_URL,
            "|".join(
                (
                    field_name,
                    str(index),
                    item.evidence_class.value,
                    item.evidence_type,
                    item.evidence_family,
                    item.source,
                    item.value or "",
                    item.supports_candidate_id or "",
                    item.version or "",
                )
            ),
        )
    return bundle
