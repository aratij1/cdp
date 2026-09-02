from types import SimpleNamespace

import pytest
from PIL import Image

from packages.domain.common import BoundingBox
from workers.page_detection.text_extraction import TextLine
from workers.page_detection.text_extraction import RapidOCRFullPageTextExtractor

from packages.layout_intelligence import BundleDLayoutEngine, BundleDRegionEscalator, GenericRoute
from packages.layout_intelligence.labels import label_firewall
from packages.layout_intelligence.labels.matcher import _similarity
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


# --- Regression coverage for the _similarity() substring/token over-match
# fix. Each case is a (alias, unrelated boilerplate line) pair drawn from
# real CMS-1500 wording -- confirms the alias no longer wins a perfect
# score merely because it appears as a fragment inside a much longer,
# differently-meaning line.
FALSE_POSITIVE_CASES = [
    ("patient name", "6 patient relationship to insured"),
    ("patient name", "12 patients or authorized persons signature authorizes release of medical information"),
    ("insured name", "11 insureds policy group or feca number"),
    ("subscriber name", "11 insureds policy group or feca number"),
    ("patient address", "7 insureds address no street"),
    ("dob", "1a insureds date of birth sex"),
    ("policy number", "11 insureds policy group or feca number"),
    ("npi", "33 billing provider info and ph number"),
]

# Each case is (alias, the real label line it must still match).
TRUE_POSITIVE_CASES = [
    ("patient name", "2 patient name"),
    ("insured name", "4 insured name"),
    ("patient address", "5 patient address no street"),
    ("dob", "3 patient dob"),
    ("policy number", "policy number"),
    ("npi", "npi"),
]


@pytest.mark.parametrize("alias,text", FALSE_POSITIVE_CASES)
def test_similarity_rejects_alias_fragment_in_unrelated_line(alias, text):
    score = _similarity(normalize_text(alias), normalize_text(text))
    assert score < 0.84, f"{alias!r} scored {score} against unrelated line {text!r}"


@pytest.mark.parametrize("alias,text", TRUE_POSITIVE_CASES)
def test_similarity_still_matches_the_real_label(alias, text):
    score = _similarity(normalize_text(alias), normalize_text(text))
    assert score >= 0.84, f"{alias!r} scored only {score} against its own real label {text!r}"


def test_040_replay_selects_real_name_not_item_11_label():
    """Reproduces the M048JJH1.040 failure using the real OCR'd text
    observed on that document: a genuine 'Patient Name' label/value pair,
    a decoy boilerplate line containing the bare word 'patient'
    ('6.PATIENT RELATIONSHIP TO INSURED'), and the unrelated item-11 label
    ('11. INSURED'S POLICY GROUP OR FECA NUMBER') that was incorrectly
    selected as patient_name's value before the fix."""
    result = BundleDLayoutEngine().extract([
        _line("2. Patient Name", 20, 40),
        _line("HAYNES, LULA M", 20, 70),
        _line("6.PATIENT RELATIONSHIP TO INSURED", 20, 110),
        _line("11. INSURED'S POLICY GROUP OR FECA NUMBER", 20, 150),
        _line("10811", 20, 180),
    ], page_number=1, width=1000, height=1200, engine="test_ocr")

    assert "patient_name" in result.candidates
    top = result.candidates["patient_name"][0]
    assert top.value == "HAYNES, LULA M"
    assert "INSURED'S POLICY GROUP" not in top.value
    assert all(c.value != "11. INSURED'S POLICY GROUP OR FECA NUMBER" for c in result.candidates["patient_name"])


def test_patient_name_and_subscriber_name_do_not_share_a_bounding_box():
    """A patient-name label/value pair and an insured/subscriber-name
    label/value pair placed in clearly distinct regions of the page must
    resolve to their own, correct, distinct bounding boxes -- not collide
    on one shared box the way the M048JJH1.040 bug did."""
    result = BundleDLayoutEngine().extract([
        _line("2. Patient Name", 20, 40),
        _line("HAYNES, LULA M", 20, 70),
        _line("Procedure: 99213", 20, 110),
        _line("4. Insured Name", 20, 300),
        _line("HAYNES, ROBERT", 20, 330),
        _line("Total Charge: $125.00", 20, 370),
    ], page_number=1, width=1000, height=1200, engine="test_ocr")

    assert "patient_name" in result.candidates
    assert "subscriber_name" in result.candidates
    patient_bbox = result.candidates["patient_name"][0].bbox
    subscriber_bbox = result.candidates["subscriber_name"][0].bbox
    assert (patient_bbox.x0, patient_bbox.y0, patient_bbox.x1, patient_bbox.y1) != (
        subscriber_bbox.x0, subscriber_bbox.y0, subscriber_bbox.x1, subscriber_bbox.y1,
    )
    assert result.candidates["patient_name"][0].value == "HAYNES, LULA M"
    assert result.candidates["subscriber_name"][0].value == "HAYNES, ROBERT"


def test_bbox_conflict_resolution_keeps_higher_confidence_field_untouched():
    """When two fields' label matches genuinely collide on one bbox, the
    stronger-evidence field must keep it -- the safeguard only demotes the
    weaker field's conflicting candidate, never both, and never by name."""
    from packages.layout_intelligence.engine import _resolve_bbox_conflicts
    from packages.layout_intelligence.models import CanonicalLayoutCandidate, LabelValueLinkEvidence

    def _candidate(field_name, value, confidence, mapping_confidence, bbox_y0):
        bbox = BoundingBox(x0=0, y0=bbox_y0, x1=100, y1=bbox_y0 + 20, image_width=1000, image_height=1000)
        evidence = LabelValueLinkEvidence(
            field_name=field_name, label_text="x", label_bbox=bbox, candidate_text=value,
            candidate_bbox=bbox, horizontal_distance=0, vertical_distance=0, same_row=True,
            same_column=True, datatype_valid=True, label_similarity=mapping_confidence,
            spatial_score=1.0, total_score=confidence, relationship="LABEL_BELOW_VALUE",
        )
        return CanonicalLayoutCandidate(
            field_name=field_name, value=value, confidence=confidence, bbox=bbox,
            original_label="x", matched_alias="x", mapping_confidence=mapping_confidence,
            datatype_valid=True, relationship_evidence=evidence,
        )

    candidates = {
        "patient_name": [_candidate("patient_name", "HAYNES, LULA M", 0.95, 0.95, 100)],
        "subscriber_name": [_candidate("subscriber_name", "11. INSURED'S POLICY GROUP", 0.55, 0.55, 100)],
    }
    _resolve_bbox_conflicts(candidates)
    assert candidates["patient_name"][0].value == "HAYNES, LULA M"
    assert "subscriber_name" not in candidates


def test_ub04_field_labels_are_not_falsely_matched_by_generic_aliases():
    result = BundleDLayoutEngine().extract([
        _line("Type of Bill", 20, 40), _line("131", 20, 70),
        _line("Revenue Code", 20, 110), _line("0450", 20, 140),
        _line("Units", 20, 180), _line("2", 20, 210),
        _line("Some unrelated narrative mentioning units of measurement elsewhere", 20, 260),
    ], page_number=1, width=1000, height=1200, engine="test_ocr")

    assert result.candidates["type_of_bill"][0].value == "131"
    assert result.candidates["revenue_code"][0].value == "0450"
    assert result.candidates["units"][0].value == "2"


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
