"""Cost-aware field cascade with deterministic controlled disposition."""

from __future__ import annotations

from dataclasses import dataclass, replace

from packages.ocr.contracts import OCRCandidate, OCREngine, OCRRequest
from workers.cascade.handwriting_detection import HandwritingDetector, WritingType
from workers.cascade.reconciliation import (
    FieldDisposition,
    ReconciliationResult,
)
from workers.retry.alternate_preprocessing import (
    adaptive_threshold,
    aggressive_contrast,
    remove_printed_lines,
    sharpen,
    upscale,
)


@dataclass(frozen=True)
class FieldCascadeResult:
    reconciliation: ReconciliationResult
    candidates: tuple[OCRCandidate, ...]
    writing_type: WritingType


class FieldCascade:
    def __init__(
        self,
        primary: OCREngine,
        secondary_factory,
        handwriting: OCREngine | None,
        detector: HandwritingDetector,
        reconciler_factory,
    ) -> None:
        self._primary = primary
        self._secondary_factory = secondary_factory
        self._handwriting = handwriting
        self._detector = detector
        self._reconciler_factory = reconciler_factory

    def run(self, request: OCRRequest) -> FieldCascadeResult:
        detection = self._detector.classify(request.image)
        candidates: list[OCRCandidate] = []
        if detection.writing_type is WritingType.BLANK:
            reconciliation = self._reconciler_factory(request).reconcile(
                [],
                request.criticality,
                request.field_name,
                document_family=request.form_type.value,
            )
            return FieldCascadeResult(reconciliation, (), detection.writing_type)

        if detection.writing_type in {WritingType.PRINTED, WritingType.MIXED}:
            candidates.extend(self._primary.recognize(request))
            provisional = self._reconciler_factory(request).reconcile(
                candidates,
                request.criticality,
                request.field_name,
                document_family=request.form_type.value,
            )
            if provisional.disposition is not FieldDisposition.VALIDATED_AUTOMATICALLY:
                candidates.extend(self._alternate_print_candidates(request))
            candidates.extend(self._secondary_factory(request.field_type).recognize(request))

        if (
            detection.writing_type in {WritingType.HANDWRITTEN, WritingType.MIXED}
            and self._handwriting is not None
        ):
            candidates.extend(self._handwriting.recognize(request))

        reconciliation = self._reconciler_factory(request).reconcile(
            candidates,
            request.criticality,
            request.field_name,
            document_family=request.form_type.value,
        )
        return FieldCascadeResult(
            reconciliation, tuple(candidates), detection.writing_type
        )

    def _alternate_print_candidates(self, request: OCRRequest) -> list[OCRCandidate]:
        variants = [
            ("upscale_2x", upscale(request.image, 2)),
            ("clahe", aggressive_contrast(request.image)),
            ("adaptive_threshold", adaptive_threshold(request.image)),
            ("sharpen", sharpen(request.image)),
        ]
        line_removed, accepted, _ = remove_printed_lines(request.image)
        if accepted:
            variants.append(("printed_line_removal", line_removed))
        candidates: list[OCRCandidate] = []
        for name, image in variants:
            for candidate in self._primary.recognize(replace(request, image=image)):
                candidates.append(replace(candidate, preprocessing_variant=name))
        return candidates
