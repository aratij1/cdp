"""Template registry: loads the real CMS-1500/UB-04 configs, coordinate
math sanity checks."""

import pytest
import yaml
from PIL import Image
from pydantic import ValidationError

from packages.domain.enums import ClaimFormType
from packages.templates import Template, TemplateNotFoundError, TemplateRegistry
from packages.templates.registry import DEFAULT_TEMPLATE_DIR


@pytest.fixture(scope="module")
def registry() -> TemplateRegistry:
    return TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)


def test_loads_cms1500_and_ub04_templates(registry):
    cms = registry.get("cms1500", "02-12")
    ub = registry.get("ub04", "2014")
    assert cms.form_type == ClaimFormType.CMS1500
    assert ub.form_type == ClaimFormType.UB04


def test_latest_for_form_type(registry):
    cms = registry.latest_for_form_type(ClaimFormType.CMS1500)
    assert cms.template_id == "cms1500"


def test_unknown_template_raises(registry):
    with pytest.raises(TemplateNotFoundError):
        registry.get("does-not-exist", "1.0")


def test_all_field_regions_are_within_reference_dimensions(registry):
    for template in (registry.get("cms1500", "02-12"), registry.get("ub04", "2014")):
        for field in template.field_regions:
            assert 0 <= field.x0 < field.x1 <= template.reference_dimensions.width_px, field
            assert 0 <= field.y0 < field.y1 <= template.reference_dimensions.height_px, field


def test_service_line_table_within_reference_dimensions(registry):
    for template in (registry.get("cms1500", "02-12"), registry.get("ub04", "2014")):
        table = template.service_line_region
        assert table is not None
        assert 0 <= table.table_x0 < table.table_x1 <= template.reference_dimensions.width_px
        assert 0 <= table.table_y0 < table.table_y1 <= template.reference_dimensions.height_px
        assert table.table_y0 + table.max_rows * table.row_height_px <= (
            template.reference_dimensions.height_px + table.row_height_px
        )
        for column in table.columns:
            assert 0 <= column.x0 < column.x1 <= template.reference_dimensions.width_px


def test_required_fields_are_defined_field_regions(registry):
    for template in (registry.get("cms1500", "02-12"), registry.get("ub04", "2014")):
        defined_names = {f.field_name for f in template.field_regions}
        for required in template.required_fields:
            assert required in defined_names, f"{required} not defined in {template.template_id}"


def test_field_region_lookup_helper(registry):
    cms = registry.get("cms1500", "02-12")
    assert cms.field_region("patient_name") is not None
    assert cms.field_region("does_not_exist") is None


def test_load_reference_image_uses_canonical_package_when_yaml_path_unset(registry):
    cms = registry.get("cms1500", "02-12")
    assert cms.reference_image_path is None
    image = registry.load_reference_image(cms)
    assert image is not None
    assert image.size == (1712, 2214)


def _template_yaml(reference_image_path: str | None) -> dict:
    return {
        "template_id": "x",
        "version": "1",
        "form_type": "CMS1500",
        "reference_dimensions": {"width_px": 20, "height_px": 10},
        "anchor_definitions": [],
        "field_regions": [],
        "reference_image_path": reference_image_path,
    }


def test_load_reference_image_returns_none_when_file_missing(tmp_path):
    config_dir = tmp_path / "templates"
    config_dir.mkdir()
    template_path = config_dir / "x.yaml"
    template_path.write_text(yaml.safe_dump(_template_yaml("reference_images/missing.png")))

    reg = TemplateRegistry.load_from_directory(config_dir)
    template = reg.get("x", "1")

    assert reg.load_reference_image(template) is None


def test_load_reference_image_returns_the_configured_image(tmp_path):
    config_dir = tmp_path / "templates"
    config_dir.mkdir()
    ref_dir = config_dir / "reference_images"
    ref_dir.mkdir()
    Image.new("L", (20, 10), color=128).save(ref_dir / "x.png")
    template_path = config_dir / "x.yaml"
    template_path.write_text(yaml.safe_dump(_template_yaml("reference_images/x.png")))

    reg = TemplateRegistry.load_from_directory(config_dir)
    template = reg.get("x", "1")

    image = reg.load_reference_image(template)
    assert image is not None
    assert image.size == (20, 10)


def test_template_model_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Template.model_validate(
            {
                "template_id": "x",
                "version": "1",
                "form_type": "CMS1500",
                "reference_dimensions": {"width_px": 10, "height_px": 10},
                "anchor_definitions": [],
                "field_regions": [],
                "not_a_real_field": True,
            }
        )
