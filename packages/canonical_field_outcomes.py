"""PHI-free first-outcome reporting; never materializes missing predictions."""
from enum import StrEnum

from packages.domain.extraction import ExtractedField


class FieldStageOutcome(StrEnum):
    FIELD_EMITTED = "FIELD_EMITTED"
    NO_CANONICAL_REGION = "NO_CANONICAL_REGION"
    REGISTRATION_UNAVAILABLE = "REGISTRATION_UNAVAILABLE"
    EMPTY_CROP = "EMPTY_CROP"
    OCR_EMPTY = "OCR_EMPTY"
    OCR_RESULT_REJECTED = "OCR_RESULT_REJECTED"
    NORMALIZATION_FAILED = "NORMALIZATION_FAILED"
    AMBIGUOUS_MULTIROW = "AMBIGUOUS_MULTIROW"
    FIELD_ASSEMBLY_DROPPED = "FIELD_ASSEMBLY_DROPPED"
    PERSISTENCE_DROPPED = "PERSISTENCE_DROPPED"
    OTHER = "OTHER"


def canonical_field_outcomes(expected: set[str], fields: list[ExtractedField], *,
        registered: bool, region_names: set[str], persisted_ids: set[str]) -> dict[str, str]:
    result = {}
    for name in sorted(expected):
        matched = [f for f in fields if f.field_name == name]
        if not registered:
            outcome = FieldStageOutcome.REGISTRATION_UNAVAILABLE
        elif name not in region_names:
            outcome = FieldStageOutcome.NO_CANONICAL_REGION
        elif len(matched) != 1:
            outcome = (FieldStageOutcome.FIELD_ASSEMBLY_DROPPED if not matched else FieldStageOutcome.OTHER)
        else:
            field = matched[0]
            if any(c.bounding_box and (c.bounding_box.x1 <= c.bounding_box.x0
                    or c.bounding_box.y1 <= c.bounding_box.y0) for c in field.candidates):
                outcome = FieldStageOutcome.EMPTY_CROP
            elif not any(c.raw_text.strip() for c in field.candidates) and not field.raw_value.strip():
                outcome = FieldStageOutcome.OCR_EMPTY
            elif "AMBIGUOUS_MULTIROW" in field.validation_reasons:
                outcome = FieldStageOutcome.AMBIGUOUS_MULTIROW
            elif not field.raw_value.strip():
                outcome = FieldStageOutcome.OCR_RESULT_REJECTED
            elif field.normalized_value is None:
                outcome = FieldStageOutcome.NORMALIZATION_FAILED
            elif str(field.field_id) not in persisted_ids:
                outcome = FieldStageOutcome.PERSISTENCE_DROPPED
            else:
                outcome = FieldStageOutcome.FIELD_EMITTED
        result[name] = outcome.value
    return result
