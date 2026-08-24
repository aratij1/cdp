"""Boundary adapters into the canonical evidence-decision contract."""

from __future__ import annotations

from packages.domain.extraction import ExtractedField, FieldEvidence
from packages.ocr.contracts import OCRCandidate
from packages.ocr.independence import independence_group
from packages.ocr.provenance import EvidenceProvenance


def ocr_candidates_from_field(field: ExtractedField) -> list[OCRCandidate]:
    evidence = list(field.candidates) or [FieldEvidence(
        source=field.extraction_method,
        raw_text=field.raw_value,
        confidence=field.confidence,
        bounding_box=field.bounding_box,
        model_name=field.model_name,
        model_version=field.model_version,
    )]
    candidates = [
        OCRCandidate(
            value=item.raw_text,
            raw_value=item.raw_text,
            engine=(
                item.provenance.engine_name
                if item.provenance and item.provenance.engine_name
                else item.source.value
            ),
            model_name=item.model_name or item.source.value,
            model_version=item.model_version or "unknown",
            preprocessing_variant=(
                item.provenance.preprocessing_profile
                if item.provenance and item.provenance.preprocessing_profile
                else "unknown"
            ),
            raw_confidence=item.confidence,
            calibrated_confidence=None,
            bounding_box=item.bounding_box or field.bounding_box,
            latency_ms=0,
            validation_results=tuple(field.validation_reasons),
            evidence_reference=str(item.evidence_id),
            preprocessing_version=(
                item.provenance.preprocessing_version
                if item.provenance and item.provenance.preprocessing_version
                else "unknown"
            ),
            provenance=item.provenance or EvidenceProvenance(
                engine_family=independence_group(item.source.value),
                model_name=item.model_name,
                model_version=item.model_version,
                bbox=item.bounding_box or field.bounding_box,
                source_candidate_id=str(item.evidence_id),
                produced_at=item.produced_at,
            ),
        )
        for item in evidence
    ]
    return candidates
