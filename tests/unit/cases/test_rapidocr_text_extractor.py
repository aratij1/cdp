from PIL import Image

from packages.domain.enums import ExtractionMethod
from packages.templates import TemplateRegistry
from packages.templates.registry import DEFAULT_TEMPLATE_DIR
from workers.page_detection.text_extraction import RapidOCRTextExtractor
from workers.standard_form_extraction.extractor import StandardFormExtractionService


def test_rapidocr_adapter_translates_crop_geometry_to_page_coordinates():
    backend = lambda _image: (
        [([[1, 2], [11, 2], [11, 8], [1, 8]], "A123", 0.9)],
        0.1,
    )
    lines = RapidOCRTextExtractor(backend=backend).extract_region(
        Image.new("RGB", (200, 100), "white"), 20, 30, 80, 60
    )
    assert (lines[0].x0, lines[0].y0, lines[0].x1, lines[0].y1) == (21, 32, 31, 38)


def test_standard_form_service_marks_rapidocr_provenance():
    backend = lambda _image: (
        [([[0, 0], [5, 0], [5, 5], [0, 5]], "X", 0.8)],
        0.1,
    )
    template = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR).get("cms1500", "02-12")
    image = Image.new(
        "RGB",
        (template.reference_dimensions.width_px, template.reference_dimensions.height_px),
        "white",
    )
    fields = StandardFormExtractionService(RapidOCRTextExtractor(backend=backend)).extract_fields(
        image, template, 1
    )
    assert fields
    assert all(field.extraction_method == ExtractionMethod.REGIONAL_RAPIDOCR for field in fields)
