from types import SimpleNamespace

import pytest
from PIL import Image

from packages.domain.common import BoundingBox
from workers.page_detection.text_extraction import TextLine
from workers.page_detection.text_extraction import RapidOCRFullPageTextExtractor

from packages.layout_intelligence import BundleDLayoutEngine, BundleDRegionEscalator, GenericRoute
from packages.layout_intelligence.labels import label_firewall
from packages.layout_intelligence.reading_order import normalize_text, reconstruct
from packages.layout_intelligence.tables import reconstruct_table


def _line(text, x0, y0, x1=None):
    return TextLine(text, x0, y0, x1 or x0 + max(40, len(text) * 8), y0 + 20, .96)


def test_reading_order_uses_geometry_not_ocr_return_order():
    lines = reconstruct([
        _line("second", 200, 100), _line("first", 20, 100), _line("third", 20, 150),
    ], page_number=1, width=1000, height=1000, engine="test")
    assert [line.text for line in lines] == ["first second", "third"]
    assert [token.reading_order for line in lines for token in line.tokens] == [0, 1, 2]


def test_label_firewall_rejects_form_vocabulary():
    vocabulary = {normalize_text("Patient Name"), normalize_text("Total Charge")}
    assert not label_firewall("PATIENT NAME", vocabulary)
    assert label_firewall("Jane Q Doe", vocabulary)


def test_engine_links_geometry_validates_datatypes_and_infers_schema():
    result = BundleDLayoutEngine().extract([
        _line("Patient Name: Jane Q Doe", 20, 40),
        _line("Member ID: AB12345", 20, 80),
        _line("Provider NPI:", 20, 120),
        _line("1234567893", 20, 150),
        _line("Procedure: 99213", 20, 200),
        _line("Total Charge: $125.00", 20, 240),
    ], page_number=1, width=1000, height=1200, engine="test_ocr")

    assert result.route is GenericRoute.UNKNOWN_STRUCTURED
    assert result.schema_evidence.schema_family == "PROFESSIONAL_CLAIM_LIKE"
    assert result.candidates["patient_name"][0].value == "Jane Q Doe"
    assert result.candidates["provider_npi"][0].datatype_valid
    assert result.candidates["provider_npi"][0].relationship_evidence.relationship == "LABEL_BELOW_VALUE"
    assert all(candidate.value != "Patient Name" for candidate in result.candidates["patient_name"])


def test_blank_page_is_non_claim():
    result = BundleDLayoutEngine().extract([], page_number=1, width=100, height=100, engine="test")
    assert result.route is GenericRoute.NON_CLAIM


def test_local_table_reconstruction_maps_headers_and_rows():
    lines = reconstruct([
        _line("Revenue", 20, 100), _line("HCPCS", 220, 100),
        _line("Units", 420, 100), _line("Charge", 620, 100),
        _line("0450", 20, 150), _line("99213", 220, 150),
        _line("2", 420, 150), _line("125.00", 620, 150),
    ], page_number=1, width=1000, height=1000, engine="test")
    result = reconstruct_table(lines)
    assert result.detected
    assert result.rows[0].revenue_code == "0450"
    assert result.rows[0].procedure_code == "99213"
    assert result.rows[0].charge == 125


def test_full_page_rapidocr_preserves_page_coordinates():
    backend = lambda _image: ([([[10, 20], [60, 20], [60, 40], [10, 40]], "DOB", .9)], None)
    lines = RapidOCRFullPageTextExtractor(backend=backend, max_full_page_side=100).extract(
        Image.new("RGB", (200, 100), "white")
    )
    assert lines[0].text == "DOB"
    assert (lines[0].x0, lines[0].y0, lines[0].x1, lines[0].y1) == (20, 40, 120, 80)


@pytest.mark.asyncio
async def test_region_ai_escalation_is_crop_only_auxiliary_candidate():
    captured = {}
    class Coordinator:
        async def resolve(self, action, request, *, estimated_cost_usd):
            captured.update(action=action, request=request)
            return SimpleNamespace(candidate=SimpleNamespace(
                value="AB123", confidence=.8, source="vertex", model="cheap",
                model_version="1", validation_results=(), actual_cost_usd=.001,
            ))
    box = BoundingBox(x0=10, y0=10, x1=80, y1=50, image_width=100, image_height=100)
    candidate = await BundleDRegionEscalator(Coordinator()).resolve(
        route="AI_CHEAP", tenant_id="tenant", document_id="doc",
        field_name="insured_id_number", expected_type="MEMBER_ID",
        page=Image.new("RGB", (100, 100), "white"), region=box,
        label="Policy Ref", candidates=[], contains_phi=False,
    )
    assert captured["request"].scope == "FIELD_CROP"
    assert captured["request"].nearby_label == "Policy Ref"
    assert candidate.validation_results == ("E7_AUXILIARY_ONLY",)
    assert candidate.evidence_reference == "ai_gateway:AI_CHEAP"
