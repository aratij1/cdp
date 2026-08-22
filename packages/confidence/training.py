"""Dependency-free Platt/isotonic fitting and calibration metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass

from packages.confidence.models import IsotonicCalibration, PlattCalibration


@dataclass(frozen=True)
class CalibrationMetrics:
    count: int
    brier_score: float
    expected_calibration_error: float
    precision_at_threshold: float | None
    acceptance_rate_at_threshold: float
    reliability_curve: tuple[dict[str, float | int], ...]


def fit_platt(
    scores: list[float], labels: list[bool], version: str, iterations: int = 3000
) -> PlattCalibration:
    if not scores or len(scores) != len(labels):
        raise ValueError("scores and labels must be non-empty and equal length")
    slope = 1.0
    positive_rate = min(1 - 1e-6, max(1e-6, sum(labels) / len(labels)))
    intercept = math.log(positive_rate / (1 - positive_rate)) - slope * sum(scores) / len(scores)
    rate = 0.08
    regularization = 1e-3
    for _ in range(iterations):
        grad_slope = grad_intercept = 0.0
        for score, label in zip(scores, labels):
            z = max(-30.0, min(30.0, slope * score + intercept))
            probability = 1 / (1 + math.exp(-z))
            error = probability - float(label)
            grad_slope += error * score
            grad_intercept += error
        slope -= rate * (grad_slope / len(scores) + regularization * slope)
        intercept -= rate * grad_intercept / len(scores)
    return PlattCalibration(slope, intercept, version)


def fit_isotonic(scores: list[float], labels: list[bool], version: str) -> IsotonicCalibration:
    if not scores or len(scores) != len(labels):
        raise ValueError("scores and labels must be non-empty and equal length")
    grouped: list[list[float]] = []
    for score, label in sorted(zip(scores, labels)):
        if grouped and grouped[-1][0] == score:
            grouped[-1][1] += float(label)
            grouped[-1][2] += 1
        else:
            grouped.append([score, float(label), 1])
    blocks: list[list[float]] = []
    for score, positives, count in grouped:
        blocks.append([score, score, positives, count])
        while len(blocks) >= 2 and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]:
            right = blocks.pop()
            left = blocks.pop()
            blocks.append([left[0], right[1], left[2] + right[2], left[3] + right[3]])
    thresholds: list[float] = []
    probabilities: list[float] = []
    for start, end, positives, count in blocks:
        probability = positives / count
        thresholds.extend([start, end] if end != start else [start])
        probabilities.extend([probability, probability] if end != start else [probability])
    return IsotonicCalibration(tuple(thresholds), tuple(probabilities), version)


def calibration_metrics(
    probabilities: list[float], labels: list[bool], *, bins: int = 10, threshold: float = 0.99
) -> CalibrationMetrics:
    if not probabilities or len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must be non-empty and equal length")
    brier = sum((probability - float(label)) ** 2 for probability, label in zip(probabilities, labels)) / len(labels)
    curve = []
    ece = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        members = [
            (probability, label)
            for probability, label in zip(probabilities, labels)
            if (lower <= probability <= upper)
            if index == bins - 1
            or probability < upper
        ]
        if not members:
            continue
        mean_confidence = sum(item[0] for item in members) / len(members)
        accuracy = sum(item[1] for item in members) / len(members)
        ece += len(members) / len(labels) * abs(accuracy - mean_confidence)
        curve.append(
            {
                "lower": lower,
                "upper": upper,
                "count": len(members),
                "mean_confidence": mean_confidence,
                "accuracy": accuracy,
            }
        )
    accepted = [label for probability, label in zip(probabilities, labels) if probability >= threshold]
    return CalibrationMetrics(
        count=len(labels),
        brier_score=brier,
        expected_calibration_error=ece,
        precision_at_threshold=sum(accepted) / len(accepted) if accepted else None,
        acceptance_rate_at_threshold=len(accepted) / len(labels),
        reliability_curve=tuple(curve),
    )
