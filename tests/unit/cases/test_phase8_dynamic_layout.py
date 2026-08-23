from decimal import Decimal

from PIL import Image, ImageDraw

from packages.document_taxonomy.taxonomy import DocumentClass
from packages.extraction_geometry import (
    ExtractionGeometryDecision,
    ExtractionGeometryMode,
    FormIdentityDecision,
    FormIdentityStatus,
)
from packages.field_localization import DynamicROIResolver
from packages.forms.cms1500 import CMS1500FieldGraph
from packages.forms.ub04 import UB04StructuralMapDetector
from packages.local_evidence_cascade import decide_local_candidate
from packages.page_observation import PageObservationCache, PageObservationService
from workers.page_detection.text_extraction import TextLine
from workers.table_extraction import UB04ServiceLineEngine
from workers.table_extraction.observation_service_lines import UB04ObservationServiceLineExtractor


class CountingOCR:
    model_version = "phi-free-fixture-v1"

    def __init__(self, lines):
        self.lines = lines
        self.calls = 0

    def extract(self, _image):
        self.calls += 1
        return self.lines


def test_page_observation_runs_full_page_ocr_once_and_reuses_cache():
    ocr = CountingOCR([TextLine("PATIENT NAME", 50, 100, 220, 125, .98)])
    service = PageObservationService(ocr, preprocessing_version="fixture-v1",
                                     cache=PageObservationCache())
    image = Image.new("RGB", (1000, 1200), "white")

    first = service.observe("page-1", image)
    second = service.observe("page-1", image)

    assert first is second
    assert first.full_page_ocr_calls == 1
    assert ocr.calls == 1


def test_cms_field_graph_uses_bounded_fuzzy_anchor_and_dynamic_roi_priority():
    ocr = CountingOCR([
        TextLine("PATlENT NAME", 80, 120, 260, 145, .98),
        TextLine("DOE JANE", 85, 160, 220, 185, .96),
    ])
    observation = PageObservationService(
        ocr, preprocessing_version="fixture-v1"
    ).observe("cms-page", Image.new("RGB", (1000, 1200), "white"))
    location = CMS1500FieldGraph().locate(observation)["patient_name"]
    geometry = ExtractionGeometryDecision(
        mode=ExtractionGeometryMode.ANCHOR_RELATIVE,
        form_identity=FormIdentityDecision(
            family=DocumentClass.CMS1500, status=FormIdentityStatus.VERIFIED, score=.99
        ),
    )

    result = DynamicROIResolver().resolve(
        "patient_name", anchor=location, structural=None, geometry=geometry,
        registered_template_bbox=(1, 1, 10, 10),
    )

    assert result.mode.value == "ANCHOR_RELATIVE"
    assert "DYNAMIC_PRIORITY_1_ANCHOR" in result.reason_codes
    assert result.bbox != (1, 1, 10, 10)


def test_ub_service_rows_reuse_observation_tokens_without_cell_ocr():
    image = Image.new("RGB", (1711, 2216), "white")
    draw = ImageDraw.Draw(image)
    for y in range(568, 1276, 32):
        draw.line((30, y, 1603, y), fill="black", width=2)
    for x in (30, 122, 613, 910, 1048, 1208, 1406, 1603):
        draw.line((x, 568, x, 1275), fill="black", width=2)
    lines = [
        TextLine("0450", 40, 580, 90, 594, .96),
        TextLine("EMERGENCY", 150, 580, 260, 594, .96),
        TextLine("99281", 650, 580, 710, 594, .96),
        TextLine("010224", 930, 580, 1000, 594, .96),
        TextLine("1", 1080, 580, 1090, 594, .96),
        TextLine("125.50", 1240, 580, 1310, 594, .96),
    ]
    ocr = CountingOCR(lines)
    observation = PageObservationService(
        ocr, preprocessing_version="fixture-v1"
    ).observe("ub-page", image)
    structure = UB04StructuralMapDetector().detect(observation)
    result = UB04ObservationServiceLineExtractor(
        UB04ServiceLineEngine(hcpcs_reference={"99281"})
    ).extract(observation, structure, claim_total=Decimal("125.50"))

    assert ocr.calls == 1
    assert result.geometry_strategy == "PAGE_OBSERVATION_TOKEN_GEOMETRY"
    assert "NO_CELL_OCR" in result.fallback_trace
    assert result.lines[0].revenue_code == "0450"


def test_valid_primary_candidate_skips_secondary_ocr():
    result = decide_local_candidate("99213", "CPT_HCPCS")

    assert result.accepted is True
    assert result.secondary_engine is None


def test_invalid_date_selects_only_configured_local_secondary():
    result = decide_local_candidate("not-a-date", "DATE")

    assert result.accepted is False
    assert result.secondary_engine == "TESSERACT_CONSTRAINED"
