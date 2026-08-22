import pytest

from packages.confidence import CalibrationRegistry, IsotonicCalibration, PlattCalibration


def test_isotonic_interpolates_and_records_version():
    registry = CalibrationRegistry(
        {
            ("rapidocr", "npi"): IsotonicCalibration(
                (0.0, 0.5, 1.0), (0.1, 0.6, 0.95), "npi-rapid-v3"
            )
        }
    )
    probability, version = registry.calibrate("rapidocr", "npi", 0.75)
    assert probability == pytest.approx(0.775)
    assert version == "npi-rapid-v3"


def test_isotonic_rejects_non_monotonic_model():
    with pytest.raises(ValueError):
        IsotonicCalibration((0.0, 1.0), (0.8, 0.2), "bad")


def test_platt_output_is_bounded():
    model = PlattCalibration(5.0, -2.0, "global-v1")
    assert 0 < model.predict(0.9) < 1
