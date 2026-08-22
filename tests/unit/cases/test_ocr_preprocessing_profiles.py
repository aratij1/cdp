import numpy as np
from PIL import Image

from packages.ocr.preprocessing import PreprocessingRegistry


def test_field_profiles_are_resolved_from_versioned_configuration() -> None:
    registry = PreprocessingRegistry.load()
    assert registry.resolve("patient_dob", "text") == "DATE"
    assert registry.resolve("billing_provider_name", "text") == "NAME"
    assert registry.resolve("patient_address", "text") == "ADDRESS"
    assert registry.resolve("service_charge", "text") == "NUMERIC"
    assert registry.resolve("procedure_code", "text") == "ALPHANUMERIC_CODE"


def test_numeric_profile_is_bounded_and_upscales_only_the_crop() -> None:
    source = Image.fromarray(np.full((20, 60), 180, dtype=np.uint8))
    applied = PreprocessingRegistry.load().apply(source, "total_charge", "amount")
    assert applied.profile == "NUMERIC"
    assert applied.version == "1.1"
    assert applied.image.size == (136, 56)


def test_name_profile_avoids_destructive_binary_thresholding() -> None:
    registry = PreprocessingRegistry.load()
    assert "otsu" not in registry.config["profiles"]["NAME"]
