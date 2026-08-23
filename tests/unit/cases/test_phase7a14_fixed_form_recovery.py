from decimal import Decimal

from PIL import Image, ImageDraw

from evaluation.fixed_form_recovery_v1.contracts import RegistrationFailureReason
from workers.page_detection.template_alignment import align_to_reference
from workers.page_detection.template_compatibility import (
    TemplateCompatibilityStatus,
    assess_template_compatibility,
)
from workers.table_extraction import UB04ServiceLineEngine, UB04Token
from workers.table_extraction import UB04ServiceLineExtractor
from packages.templates import TemplateRegistry
from workers.page_detection.text_extraction import TextLine


def _grid() -> Image.Image:
    image = Image.new("L", (600, 800), 255)
    draw = ImageDraw.Draw(image)
    for y in range(80, 740, 55):
        draw.line((30, y, 570, y), fill=0, width=2)
    for x in range(30, 590, 90):
        draw.line((x, 80, x, 740), fill=0, width=2)
    return image


def test_template_compatibility_accepts_same_structural_lineage():
    reference = _grid()
    evidence = assess_template_compatibility(reference.copy(), reference, family="UB04")
    assert evidence.status == TemplateCompatibilityStatus.COMPATIBLE
    assert evidence.compatibility_score >= .72


def test_template_compatibility_rejects_sparse_different_lineage():
    reference = _grid()
    candidate = Image.new("L", reference.size, 255)
    ImageDraw.Draw(candidate).rectangle((25, 25, 575, 120), outline=0, width=2)
    evidence = assess_template_compatibility(candidate, reference, family="UB04")
    assert evidence.status == TemplateCompatibilityStatus.INCOMPATIBLE
    assert "TEMPLATE_LINEAGE_MISMATCH" in evidence.reason_codes


def test_alignment_trace_preserves_cheap_evidence_and_skips_sift_when_incompatible():
    reference = _grid()
    candidate = Image.new("L", reference.size, 255)
    ImageDraw.Draw(candidate).line((20, 40, 580, 40), fill=0, width=2)
    result = align_to_reference(
        candidate, reference, family="UB04", enforce_compatibility_precheck=True
    )
    assert result.success is False
    assert result.sift_attempted is False
    assert result.cheap_evidence is not None
    assert result.compatibility.status == TemplateCompatibilityStatus.INCOMPATIBLE


def test_failure_taxonomy_includes_explicit_template_lineage_reason():
    assert RegistrationFailureReason.TEMPLATE_LINEAGE_MISMATCH.value == "TEMPLATE_LINEAGE_MISMATCH"


def test_ub04_rows_expose_auditable_geometry_candidates_and_confidence():
    def token(text, x):
        return UB04Token(text=text, bbox=(x, 580, x + 30, 592), confidence=.96)

    result = UB04ServiceLineEngine(hcpcs_reference={"99281"}).reconstruct(
        [token("0450", 40), token("EMERGENCY", 150), token("99281", 650),
         token("010224", 930), token("1", 1080), token("125.50", 1240)],
        registration_confidence=.95,
        claim_total=Decimal("125.50"),
    )
    row = result.lines[0]
    assert row.row_bbox is not None
    assert "revenue_code" in row.column_bboxes
    assert row.ocr_candidates["revenue_code"][0].text == "0450"
    assert row.validation_status == "VALID"
    assert row.reconstruction_confidence > 0


def test_ub04_service_line_extractor_uses_detected_grid_and_one_ocr_call():
    template = TemplateRegistry.load_from_directory().get("ub04", "2014")
    table = template.service_line_region
    image = Image.new("L", (template.reference_dimensions.width_px,
                            template.reference_dimensions.height_px), 255)
    draw = ImageDraw.Draw(image)
    xs = [column.x0 for column in table.columns] + [table.columns[-1].x1]
    for x in xs:
        draw.line((x, table.table_y0, x, table.table_y1), fill=0, width=2)
    for y in (table.table_y0, table.table_y0 + table.row_height_px,
              table.table_y0 + 2 * table.row_height_px):
        draw.line((table.table_x0, y, table.table_x1, y), fill=0, width=2)

    class OneCallOCR:
        calls = 0

        def extract_region(self, *_args):
            self.calls += 1
            y = table.table_y0 + 10
            return [
                TextLine("0450", table.columns[0].x0 + 5, y, table.columns[0].x0 + 40, y + 10, .96),
                TextLine("ER", table.columns[1].x0 + 5, y, table.columns[1].x0 + 30, y + 10, .96),
                TextLine("99281", table.columns[2].x0 + 5, y, table.columns[2].x0 + 50, y + 10, .96),
                TextLine("010224", table.columns[3].x0 + 5, y, table.columns[3].x0 + 55, y + 10, .96),
                TextLine("1", table.columns[4].x0 + 5, y, table.columns[4].x0 + 15, y + 10, .96),
                TextLine("125.50", table.columns[5].x0 + 5, y, table.columns[5].x0 + 60, y + 10, .96),
            ]

    ocr = OneCallOCR()
    result = UB04ServiceLineExtractor(
        ocr, UB04ServiceLineEngine(hcpcs_reference={"99281"})
    ).extract(image, template, registration_confidence=.95, claim_total=Decimal("125.50"))
    assert ocr.calls == 1
    assert result.geometry_strategy == "DETERMINISTIC_LINE_GRID"
    assert result.lines[0].revenue_code == "0450"
