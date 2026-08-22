import argparse
import json
from pathlib import Path

import pytest

from evaluation.calibrate_confidence import run
from packages.confidence import (
    CalibrationRegistry,
    calibration_metrics,
    fit_isotonic,
    fit_platt,
)


def test_isotonic_fit_is_monotonic_and_bounded() -> None:
    model = fit_isotonic([0.1, 0.2, 0.3, 0.4], [False, True, False, True], "iso-v1")
    values = [model.predict(score / 10) for score in range(11)]
    assert values == sorted(values)
    assert all(0 <= value <= 1 for value in values)


def test_platt_fit_separates_simple_binary_scores() -> None:
    model = fit_platt([0.1, 0.2, 0.8, 0.9], [False, False, True, True], "platt-v1")
    assert model.predict(0.9) > model.predict(0.1)


def test_calibration_metrics_report_brier_ece_precision_and_curve() -> None:
    metrics = calibration_metrics([0.1, 0.8, 0.99], [False, True, True], threshold=0.99)
    assert metrics.brier_score == pytest.approx((0.01 + 0.04 + 0.0001) / 3)
    assert metrics.precision_at_threshold == 1.0
    assert metrics.acceptance_rate_at_threshold == pytest.approx(1 / 3)
    assert metrics.reliability_curve


def test_registry_loads_versioned_models(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "SHADOW_ONLY",
                "models": [
                    {
                        "engine": "*",
                        "field_name": "patient_name",
                        "type": "platt",
                        "slope": 2,
                        "intercept": -1,
                        "version": "v1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    probability, version = CalibrationRegistry.load(path).calibrate(
        "rapidocr", "patient_name", 0.8
    )
    assert 0 < probability < 1
    assert version == "v1"


def test_calibration_cli_excludes_holdout_and_marks_registry_shadow_only(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    report = run(
        argparse.Namespace(
            truth=Path("evaluation_data/ground_truth.json"),
            predictions=Path(
                "evaluation_results/vnext_accuracy_improvement/predictions_with_unstructured.json"
            ),
            output_dir=tmp_path / "output",
            registry=registry,
            version="test-v1",
        )
    )
    assert report["holdout_used"] is False
    assert report["holdout_documents_excluded"] == 5
    assert {"calibration", "validation"} == {
        json.loads(line)["split"]
        for line in (tmp_path / "output" / "features.jsonl").read_text("utf-8").splitlines()
    }
    assert json.loads(registry.read_text("utf-8"))["status"] == "SHADOW_ONLY"
