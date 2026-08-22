"""Small dependency-free inference implementations for calibrated confidence."""

from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass, field
from pathlib import Path


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


@dataclass(frozen=True)
class PlattCalibration:
    slope: float
    intercept: float
    version: str

    def predict(self, raw_score: float) -> float:
        score = _bounded(raw_score)
        z = self.slope * score + self.intercept
        if z >= 0:
            return 1.0 / (1.0 + math.exp(-z))
        exp_z = math.exp(z)
        return exp_z / (1.0 + exp_z)


@dataclass(frozen=True)
class IsotonicCalibration:
    thresholds: tuple[float, ...]
    probabilities: tuple[float, ...]
    version: str

    def __post_init__(self) -> None:
        if not self.thresholds or len(self.thresholds) != len(self.probabilities):
            raise ValueError("isotonic thresholds and probabilities must be non-empty and equal")
        if tuple(sorted(self.thresholds)) != self.thresholds:
            raise ValueError("isotonic thresholds must be sorted")
        if any(a > b for a, b in zip(self.probabilities, self.probabilities[1:])):
            raise ValueError("isotonic probabilities must be monotonic")

    def predict(self, raw_score: float) -> float:
        score = _bounded(raw_score)
        index = bisect.bisect_left(self.thresholds, score)
        if index <= 0:
            return _bounded(self.probabilities[0])
        if index >= len(self.thresholds):
            return _bounded(self.probabilities[-1])
        x0, x1 = self.thresholds[index - 1], self.thresholds[index]
        y0, y1 = self.probabilities[index - 1], self.probabilities[index]
        if x1 == x0:
            return _bounded(y1)
        return _bounded(y0 + (score - x0) * (y1 - y0) / (x1 - x0))


@dataclass
class CalibrationRegistry:
    """Lookup order: exact engine/field, engine wildcard, global fallback."""

    models: dict[tuple[str, str], PlattCalibration | IsotonicCalibration] = field(
        default_factory=dict
    )

    def resolve(self, engine: str, field_name: str):
        return (
            self.models.get((engine, field_name))
            or self.models.get((engine, "*"))
            or self.models.get(("*", field_name))
            or self.models.get(("*", "*"))
        )

    def calibrate(self, engine: str, field_name: str, raw_score: float) -> tuple[float, str]:
        model = self.resolve(engine, field_name)
        if model is None:
            return _bounded(raw_score), "uncalibrated-v0"
        return model.predict(raw_score), model.version

    @classmethod
    def load(cls, path: str | Path) -> CalibrationRegistry:
        payload = json.loads(Path(path).read_text("utf-8"))
        if payload.get("schema_version") != "1.0":
            raise ValueError("unsupported calibration registry schema")
        models = {}
        for item in payload.get("models", []):
            key = (str(item["engine"]), str(item["field_name"]))
            if item["type"] == "platt":
                model = PlattCalibration(float(item["slope"]), float(item["intercept"]), item["version"])
            elif item["type"] == "isotonic":
                model = IsotonicCalibration(
                    tuple(float(value) for value in item["thresholds"]),
                    tuple(float(value) for value in item["probabilities"]),
                    item["version"],
                )
            else:
                raise ValueError(f"unsupported calibration model type: {item['type']}")
            models[key] = model
        return cls(models)
