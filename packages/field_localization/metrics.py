"""Ground-truth localization metrics and confidence reliability tables."""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum

from pydantic import Field

from packages.domain.common import DomainModel


class RegionOutcome(StrEnum):
    GEOMETRIC_MATCH = "GEOMETRIC_MATCH"
    VALUE_CONTAINED = "VALUE_CONTAINED"
    OVER_CROP = "OVER_CROP"
    UNDER_CROP = "UNDER_CROP"
    WRONG_NEIGHBOR = "WRONG_NEIGHBOR"
    WRONG_REGION = "WRONG_REGION"
    EMPTY_REGION = "EMPTY_REGION"


class LocalizationMetricRecord(DomainModel):
    document_id: str
    document_family: str
    field_name: str
    source: str
    critical: bool
    strategy: str
    predicted_bbox: tuple[int, int, int, int] | None
    expected_bbox: tuple[int, int, int, int]
    confidence: float = Field(ge=0, le=1)
    wrong_crop_detected: bool
    competing_neighbor_bbox: tuple[int, int, int, int] | None = None
    predicted_text_empty: bool = False


def intersection_over_union(left, right) -> float:
    if left is None:
        return 0.0
    intersection = _intersection(left, right)
    union = _area(left) + _area(right) - intersection
    return intersection / union if union else 0.0


def value_containment(predicted, expected) -> float:
    return _intersection(predicted, expected) / _area(expected) if predicted else 0.0


def classify_region(record: LocalizationMetricRecord) -> RegionOutcome:
    predicted = record.predicted_bbox
    if predicted is None or record.predicted_text_empty:
        return RegionOutcome.EMPTY_REGION
    containment = value_containment(predicted, record.expected_bbox)
    neighbor = value_containment(predicted, record.competing_neighbor_bbox) if (
        record.competing_neighbor_bbox
    ) else 0.0
    if neighbor >= .50 and containment < .95:
        return RegionOutcome.WRONG_NEIGHBOR
    if containment >= .95:
        excess = _area(predicted) / max(1, _area(record.expected_bbox))
        if excess > 3.0:
            return RegionOutcome.OVER_CROP
        if intersection_over_union(predicted, record.expected_bbox) >= .50:
            return RegionOutcome.GEOMETRIC_MATCH
        return RegionOutcome.VALUE_CONTAINED
    if containment > 0:
        return RegionOutcome.UNDER_CROP
    return RegionOutcome.WRONG_REGION


def aggregate_localization(records: list[LocalizationMetricRecord]) -> dict:
    outcomes = [(record, classify_region(record)) for record in records]
    correct = {
        RegionOutcome.GEOMETRIC_MATCH,
        RegionOutcome.VALUE_CONTAINED,
        RegionOutcome.OVER_CROP,
    }
    actual_wrong = [outcome not in correct for _, outcome in outcomes]
    detected = [record.wrong_crop_detected for record, _ in outcomes]
    true_positive = sum(a and d for a, d in zip(actual_wrong, detected, strict=True))
    false_positive = sum(not a and d for a, d in zip(actual_wrong, detected, strict=True))
    by_dimension: dict[str, dict[str, list[tuple[LocalizationMetricRecord, RegionOutcome]]]] = {
        name: defaultdict(list) for name in ("document_family", "field_name", "source", "critical", "strategy")
    }
    for record, outcome in outcomes:
        for dimension in by_dimension:
            by_dimension[dimension][str(getattr(record, dimension))].append((record, outcome))
    return {
        **_summary(outcomes),
        "wrong_crop_recall": true_positive / max(1, sum(actual_wrong)),
        "wrong_crop_precision": true_positive / max(1, true_positive + false_positive),
        "by": {
            dimension: {key: _summary(values) for key, values in groups.items()}
            for dimension, groups in by_dimension.items()
        },
        "calibration": calibration_table(records),
    }


def calibration_table(records: list[LocalizationMetricRecord]) -> list[dict]:
    buckets = ((.50, .60), (.60, .70), (.70, .80), (.80, .90),
               (.90, .95), (.95, .99), (.99, 1.0000001))
    table = []
    for low, high in buckets:
        scoped = [record for record in records if low <= record.confidence < high]
        if not scoped:
            continue
        outcomes = [(record, classify_region(record)) for record in scoped]
        accurate = sum(outcome in {
            RegionOutcome.GEOMETRIC_MATCH, RegionOutcome.VALUE_CONTAINED, RegionOutcome.OVER_CROP
        } for _, outcome in outcomes)
        table.append({
            "confidence_bucket": f"{low:.2f}-{min(high, 1):.2f}",
            "sample_count": len(scoped),
            "actual_localization_accuracy": accurate / len(scoped),
            "wrong_crop_rate": 1 - accurate / len(scoped),
            "field_families": sorted({record.document_family for record in scoped}),
            "sources": sorted({record.source for record in scoped}),
        })
    return table


def _summary(values: list[tuple[LocalizationMetricRecord, RegionOutcome]]) -> dict:
    count = len(values)
    contained = sum(value_containment(record.predicted_bbox, record.expected_bbox) >= .95
                    for record, _ in values)
    geometric = sum(outcome == RegionOutcome.GEOMETRIC_MATCH for _, outcome in values)
    correct = sum(outcome in {
        RegionOutcome.GEOMETRIC_MATCH, RegionOutcome.VALUE_CONTAINED, RegionOutcome.OVER_CROP
    } for _, outcome in values)
    return {
        "samples": count,
        "anchor_detection_accuracy": sum(record.predicted_bbox is not None for record, _ in values) / max(1, count),
        "mean_region_iou": sum(intersection_over_union(record.predicted_bbox, record.expected_bbox)
                               for record, _ in values) / max(1, count),
        "value_span_containment": contained / max(1, count),
        "exact_region_match": geometric / max(1, count),
        "localization_accuracy": correct / max(1, count),
        "wrong_neighbor_rate": sum(outcome == RegionOutcome.WRONG_NEIGHBOR for _, outcome in values) / max(1, count),
        "empty_region_rate": sum(outcome == RegionOutcome.EMPTY_REGION for _, outcome in values) / max(1, count),
        "under_crop_rate": sum(outcome == RegionOutcome.UNDER_CROP for _, outcome in values) / max(1, count),
        "over_crop_rate": sum(outcome == RegionOutcome.OVER_CROP for _, outcome in values) / max(1, count),
        "outcomes": {outcome.value: sum(item == outcome for _, item in values) for outcome in RegionOutcome},
    }


def _area(box) -> float:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _intersection(left, right) -> float:
    if left is None or right is None:
        return 0.0
    return max(0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0, min(left[3], right[3]) - max(left[1], right[1])
    )
