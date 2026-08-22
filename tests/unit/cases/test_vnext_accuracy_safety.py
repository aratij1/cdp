from pathlib import Path

import pytest
import yaml
from PIL import Image

from evaluation.run_atomic_ocr import (
    _relationship_from_pixels,
    _safe_to_accept,
    _should_suppress_duplicate_patient_address,
    normalize_atomic,
    prepare_field_image,
)
from evaluation.schemas import PredictedField
from packages.domain.enums import ClaimFormType
from packages.templates.readiness import missing_reference_templates, require_reference_templates
from packages.templates.registry import TemplateRegistry


def _template(reference: str | None) -> dict:
    return {
        "template_id": "cms",
        "version": "1",
        "form_type": "CMS1500",
        "reference_dimensions": {"width_px": 100, "height_px": 100},
        "anchor_definitions": [],
        "field_regions": [],
        "reference_image_path": reference,
    }


def test_critical_names_never_accept_without_authoritative_identity():
    assert not _safe_to_accept(
        "patient_first", "SEAN", True, {"RAPID_ONNX_FAMILY", "PADDLE_FAMILY"}
    )


def test_noncritical_field_requires_independent_engine_families():
    assert not _safe_to_accept("insured_state", "AZ", False, {"PADDLE_FAMILY"})
    assert _safe_to_accept(
        "insured_state", "AZ", False, {"PADDLE_FAMILY", "TESSERACT_FAMILY"}
    )


def test_form_vocabulary_is_not_a_person_name():
    assert normalize_atomic("patient_first", "ADMISSION") == ""
    assert normalize_atomic("patient_first", "SHIPPE, TIMOTHY BIRTHDATE") == "TIMOTHY"


def test_leading_address_suffix_is_moved_after_street_name():
    assert normalize_atomic("insured_addr1", "AVE 4019 IDAHO") == "4019 IDAHO AVE"
    assert normalize_atomic("insured_addr1", "610 RD GIFFORD") == "610 GIFFORD RD"


def test_small_field_crop_is_contrast_normalized_and_upscaled():
    image = Image.new("RGB", (100, 30), "gray")
    assert prepare_field_image("patient_first", image).size == (200, 60)
    assert prepare_field_image("type_of_bill", image).size == (300, 90)


def test_relationship_checkbox_reads_interior_marks_not_labels():
    image = Image.new("L", (388, 56), "white")
    for x0, x1 in ((67, 96), (165, 194), (245, 273), (344, 373)):
        for x in range(x0, x1 + 1):
            image.putpixel((x, 20), 0)
            image.putpixel((x, 48), 0)
        for y in range(20, 49):
            image.putpixel((x0, y), 0)
            image.putpixel((x1, y), 0)
    for offset in range(12):
        image.putpixel((74 + offset, 28 + offset), 0)
        image.putpixel((88 - offset, 28 + offset), 0)
    assert _relationship_from_pixels(image) == "01"


def test_self_relationship_suppresses_only_meaningful_duplicate_address():
    relationship = PredictedField(field_name="rel_code", raw_value="01")
    meaningful = PredictedField(field_name="insured_addr1", raw_value="4019 IDAHO AVE")
    unknown = PredictedField(field_name="insured_addr1", raw_value="UNKNOWN")
    assert _should_suppress_duplicate_patient_address(relationship, meaningful)
    assert not _should_suppress_duplicate_patient_address(relationship, unknown)


def test_template_readiness_fails_closed_when_reference_is_absent(tmp_path: Path):
    (tmp_path / "cms.yaml").write_text(yaml.safe_dump(_template(None)), encoding="utf-8")
    registry = TemplateRegistry.load_from_directory(tmp_path)
    assert missing_reference_templates(registry, [ClaimFormType.CMS1500]) == ["cms@1"]
    with pytest.raises(RuntimeError, match="non-PHI operator-approved blank references"):
        require_reference_templates(registry, [ClaimFormType.CMS1500])


def test_template_readiness_passes_with_a_real_configured_asset(tmp_path: Path):
    Image.new("L", (100, 100), "white").save(tmp_path / "blank.png")
    (tmp_path / "cms.yaml").write_text(
        yaml.safe_dump(_template("blank.png")), encoding="utf-8"
    )
    registry = TemplateRegistry.load_from_directory(tmp_path)
    require_reference_templates(registry, [ClaimFormType.CMS1500])
