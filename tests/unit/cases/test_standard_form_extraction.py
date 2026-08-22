"""Regional CMS-1500/UB-04 extraction: template-region-only OCR, field
normalization, and service-line row stopping."""

from PIL import Image
from decimal import Decimal

from packages.domain.enums import ValidationStatus
from packages.templates import TemplateRegistry
from packages.templates.registry import DEFAULT_TEMPLATE_DIR
from workers.page_detection.text_extraction import TextLine
from workers.standard_form_extraction.extractor import StandardFormExtractionService


class RegionScriptedTextExtractor:
    """A `TextExtractor` whose `extract_region` returns a scripted string
    (optionally with a scripted confidence, default 0.9) for whichever known
    (field_name, region) the requested crop best matches, and raises if
    `extract` (whole-page OCR) is ever called -- this enforces the
    "template-region OCR only" acceptance criterion."""

    def __init__(
        self, scripted: dict[tuple[int, int, int, int], str | tuple[str, float]]
    ) -> None:
        self._scripted = {
            region: value if isinstance(value, tuple) else (value, 0.9)
            for region, value in scripted.items()
        }
        self.region_calls: list[tuple[int, int, int, int]] = []

    def extract(self, image: Image.Image) -> list[TextLine]:  # pragma: no cover - must not be called
        raise AssertionError("whole-page OCR must never be called for standard-form extraction")

    def extract_region(self, image, x0, y0, x1, y1) -> list[TextLine]:
        self.region_calls.append((x0, y0, x1, y1))
        for (rx0, ry0, rx1, ry1), (text, confidence) in self._scripted.items():
            # requested region is the field region + padding, so containment
            if x0 <= rx0 and y0 <= ry0 and x1 >= rx1 and y1 >= ry1:
                return [TextLine(text=text, x0=rx0, y0=ry0, x1=rx1, y1=ry1, confidence=confidence)]
        return []


def _registry() -> TemplateRegistry:
    return TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)


def test_extracts_all_cms1500_field_regions_with_scripted_values():
    template = _registry().get("cms1500", "02-12")
    scripted = {
        (f.x0, f.y0, f.x1, f.y1): {
            "patient_name": "DOE, JOHN",
            "federal_tax_id": "12-3456789",
            "total_charge": "$1,675.00",
        }.get(f.field_name, "")
        for f in template.field_regions
    }
    extractor = RegionScriptedTextExtractor(scripted)
    service = StandardFormExtractionService(extractor)
    image = Image.new("L", (template.reference_dimensions.width_px, template.reference_dimensions.height_px), 255)

    fields = service.extract_fields(image, template, page_number=1)

    assert len(fields) == len(template.field_regions)
    by_name = {f.field_name: f for f in fields}
    assert by_name["patient_name"].raw_value == "DOE, JOHN"
    assert by_name["federal_tax_id"].normalized_value == "123456789"
    assert by_name["total_charge"].normalized_value == "1675.00"
    assert by_name["total_charge"].validation_status == ValidationStatus.PENDING


def test_name_projection_improves_accuracy_without_duplicate_ocr():
    template = _registry().get("ub04", "2014")
    name_regions = [field for field in template.field_regions
                    if field.field_name in {"patient_first", "patient_last"}]
    bounds = (name_regions[0].x0, name_regions[0].y0,
              name_regions[0].x1, name_regions[0].y1)
    extractor = RegionScriptedTextExtractor({bounds: "DOE, JOHN"})
    service = StandardFormExtractionService(extractor)
    image = Image.new("L", (template.reference_dimensions.width_px,
                            template.reference_dimensions.height_px), 255)

    fields = service.extract_fields(image, template, page_number=1)

    by_name = {field.field_name: field for field in fields}
    assert by_name["patient_last"].normalized_value == "DOE"
    assert by_name["patient_first"].normalized_value == "JOHN"
    name_calls = [call for call in extractor.region_calls
                  if call[0] <= bounds[0] and call[1] <= bounds[1]
                  and call[2] >= bounds[2] and call[3] >= bounds[3]]
    assert len(name_calls) == 1


def test_near_identical_cms_name_regions_are_coalesced():
    template = _registry().get("cms1500", "02-12")
    extractor = RegionScriptedTextExtractor({})
    service = StandardFormExtractionService(extractor)
    image = Image.new("L", (template.reference_dimensions.width_px,
                            template.reference_dimensions.height_px), 255)

    service.extract_fields(image, template, page_number=1)

    assert len(extractor.region_calls) == len(template.field_regions) - 1
    assert service.last_field_ocr_cost == {
        "logical_regional_requests": len(template.field_regions),
        "executed_regional_requests": len(template.field_regions) - 1,
        "coalesced_requests": 1,
        "request_reduction_rate": 1 / len(template.field_regions),
    }


def test_field_confidence_reflects_real_ocr_confidence_not_a_placeholder():
    template = _registry().get("cms1500", "02-12")
    scripted = {
        (f.x0, f.y0, f.x1, f.y1): {
            "patient_name": ("DOE, JOHN", 0.42),
            "federal_tax_id": ("12-3456789", 0.99),
        }.get(f.field_name, ("", 0.0))
        for f in template.field_regions
    }
    extractor = RegionScriptedTextExtractor(scripted)
    service = StandardFormExtractionService(extractor)
    image = Image.new("L", (template.reference_dimensions.width_px, template.reference_dimensions.height_px), 255)

    fields = service.extract_fields(image, template, page_number=1)

    by_name = {f.field_name: f for f in fields}
    # a genuinely low-confidence OCR read must not be clamped to a fixed
    # placeholder (0.85) -- that would hide it from the model router's
    # retry-escalation decision.
    assert by_name["patient_name"].confidence == 0.42
    assert by_name["federal_tax_id"].confidence == 0.99
    # empty (no lines found) regions are still confidence 0.0
    empty_field = next(f for f in fields if f.field_name not in ("patient_name", "federal_tax_id"))
    assert empty_field.confidence == 0.0


def test_never_calls_whole_page_ocr():
    template = _registry().get("cms1500", "02-12")
    extractor = RegionScriptedTextExtractor({})
    service = StandardFormExtractionService(extractor)
    image = Image.new("L", (template.reference_dimensions.width_px, template.reference_dimensions.height_px), 255)

    service.extract_fields(image, template, page_number=1)
    service.extract_service_lines(image, template, page_number=1)
    # if extract() had been called, RegionScriptedTextExtractor.extract raises
    assert len(extractor.region_calls) > 0


def test_field_bounding_boxes_reference_template_dimensions():
    template = _registry().get("cms1500", "02-12")
    extractor = RegionScriptedTextExtractor({})
    service = StandardFormExtractionService(extractor)
    image = Image.new("L", (template.reference_dimensions.width_px, template.reference_dimensions.height_px), 255)

    fields = service.extract_fields(image, template, page_number=1)
    for field in fields:
        assert field.bounding_box.image_width == template.reference_dimensions.width_px
        assert field.bounding_box.image_height == template.reference_dimensions.height_px


def test_service_lines_stop_at_first_blank_row():
    template = _registry().get("cms1500", "02-12")
    table = template.service_line_region
    cpt_col = next(c for c in table.columns if c.field_name == "cpt_hcpcs")
    charges_col = next(c for c in table.columns if c.field_name == "charges")

    def row_y(i):
        return table.table_y0 + i * table.row_height_px

    scripted = {
        (cpt_col.x0, row_y(0), cpt_col.x1, row_y(0) + table.row_height_px): "99213",
        (charges_col.x0, row_y(0), charges_col.x1, row_y(0) + table.row_height_px): "150.00",
        (cpt_col.x0, row_y(1), cpt_col.x1, row_y(1) + table.row_height_px): "99214",
        (charges_col.x0, row_y(1), charges_col.x1, row_y(1) + table.row_height_px): "200.00",
        # row 2 intentionally blank -> extraction must stop here
        (cpt_col.x0, row_y(3), cpt_col.x1, row_y(3) + table.row_height_px): "99215",
        (charges_col.x0, row_y(3), charges_col.x1, row_y(3) + table.row_height_px): "300.00",
    }
    extractor = RegionScriptedTextExtractor(scripted)
    service = StandardFormExtractionService(extractor)
    image = Image.new("L", (template.reference_dimensions.width_px, template.reference_dimensions.height_px), 255)

    lines = service.extract_service_lines(image, template, page_number=1)

    assert len(lines) == 2  # stops before the blank row 2, never reaches row 3's data
    assert lines[0].line_number == 1
    assert lines[0].procedure_code == "99213"
    assert lines[0].charge_amount == 150.00
    assert lines[1].procedure_code == "99214"
    assert lines[1].charge_amount == 200.00


def test_extracts_ub04_service_lines_with_revenue_codes():
    template = _registry().get("ub04", "2014")
    table = template.service_line_region
    rev_col = next(c for c in table.columns if c.field_name == "revenue_code")
    total_col = next(c for c in table.columns if c.field_name == "total_charges")

    def row_y(i):
        return table.table_y0 + i * table.row_height_px

    scripted = {
        (rev_col.x0, row_y(0), rev_col.x1, row_y(0) + table.row_height_px): "0251",
        (total_col.x0, row_y(0), total_col.x1, row_y(0) + table.row_height_px): "500.00",
    }
    extractor = RegionScriptedTextExtractor(scripted)
    service = StandardFormExtractionService(extractor)
    image = Image.new("L", (template.reference_dimensions.width_px, template.reference_dimensions.height_px), 255)

    lines = service.extract_service_lines(image, template, page_number=1)

    assert len(lines) == 1
    assert lines[0].revenue_code == "0251"
    assert lines[0].charge_amount == 500.00


def test_specialized_ub04_engine_is_callable_from_live_extraction_service():
    template = _registry().get("ub04", "2014")

    class UBTableExtractor(RegionScriptedTextExtractor):
        def extract_region(self, image, x0, y0, x1, y1):
            return [
                TextLine("0251", 40, 575, 80, 590, .96),
                TextLine("PHARMACY", 150, 575, 300, 590, .96),
                TextLine("1", 1080, 575, 1100, 590, .96),
                TextLine("500.00", 1240, 575, 1320, 590, .96),
            ]

    service = StandardFormExtractionService(UBTableExtractor({}))
    image = Image.new("L", (
        template.reference_dimensions.width_px, template.reference_dimensions.height_px
    ), 255)
    lines, result = service.extract_ub04_service_lines(
        image, template, 1, registration_confidence=.95, claim_total=Decimal("500.00"),
    )

    assert result.geometry_valid
    assert result.totals_reconciled
    assert lines[0].revenue_code == "0251"
    assert lines[0].charge_amount == 500.00
