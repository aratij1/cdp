"""DI confirms Claude on a name, and DI+partner mints charge E2 without place-shifts."""

from PIL import Image

from packages.evidence.builder import build_evidence_bundle
from packages.extraction_recovery.name_azure_di_confirm import (
    maybe_confirm_name_with_azure_di,
)
from packages.ocr.contracts import OCRCandidate
from packages.domain.common import BoundingBox


def _cand(engine, value, conf=0.9):
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine=engine,
        model_name=engine,
        model_version="test",
        preprocessing_variant="test",
        raw_confidence=conf,
        calibrated_confidence=conf,
        bounding_box=BoundingBox(x0=0, y0=0, x1=10, y1=10, image_width=20, image_height=20),
        latency_ms=0.0,
    )


def test_name_di_adopts_claude_spelling_when_they_agree():
    row = {
        "field": "patient_name",
        "ocr_region": [10, 10, 80, 40],
        "candidates": [
            {"engine": "rapidocr", "value": "CMOMXAUONI ANUA Y"},
            {"engine": "anthropic_claude_crop", "value": "FRANCAVILLA, THOMAS J"},
        ],
        "cascade": {"accepted": True, "value": "CMOMXAUONI ANUA Y"},
    }
    updated = maybe_confirm_name_with_azure_di(
        row,
        image=Image.new("RGB", (100, 40), "white"),
        reader=lambda _image, _field: "FRANCAVILLA, THOMAS J",
    )
    assert updated["cascade"]["value"] == "FRANCAVILLA, THOMAS J"
    assert updated["cascade"]["accept_reason"] == "NAME_DI_CLAUDE_AGREEMENT"
    assert updated["candidates"][0]["engine"] == "azure_document_intelligence_read"


def test_name_di_does_not_supersede_when_it_disagrees():
    row = {
        "field": "patient_name",
        "ocr_region": [10, 10, 80, 40],
        "candidates": [
            {"engine": "rapidocr", "value": "CMOMXAUONI ANUA Y"},
            {"engine": "anthropic_claude_crop", "value": "CHANQUIANI, ANYA M"},
        ],
        "cascade": {"accepted": True, "value": "CMOMXAUONI ANUA Y"},
    }
    updated = maybe_confirm_name_with_azure_di(
        row,
        image=Image.new("RGB", (100, 40), "white"),
        reader=lambda _image, _field: "Chanquiani, Anyja M",
    )
    assert updated["cascade"]["value"] == "CMOMXAUONI ANUA Y"
    assert any(a.get("reason") == "NAME_DI_DISAGREES" for a in updated["attempts"])


def test_charge_di_rapid_mints_e2_but_place_shift_does_not():
    agreed = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("azure_document_intelligence_read", "495.00"),
            _cand("rapidocr", "495.00"),
            _cand("paddleocr", "405.00"),
        ],
        registration_confidence=0.95,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID", "HARD_VALIDATION_PASSED"},
        hard_validation_passed=True,
    )
    e2 = [
        item
        for item in agreed.items
        if item.evidence_class.value == "E2" and item.independent
    ]
    assert e2 and e2[0].metadata.get("agreement_type") == "CHARGE_DI_PARTNER_AGREEMENT"
    assert any(
        item.evidence_class.value == "E4" and (item.metadata or {}).get("strength") == "STRONG"
        for item in agreed.items
    )

    shifted = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("azure_document_intelligence_read", "4972.00"),
            _cand("rapidocr", "4972.00"),
            _cand("paddleocr", "49.72"),
        ],
        registration_confidence=0.95,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID"},
        hard_validation_passed=True,
    )
    assert not any(
        item.evidence_class.value == "E2" and item.independent for item in shifted.items
    )


def test_charge_di_strong_e4_even_when_dual_local_e2_already_emitted():
    """EJGE.001: paddle+rapid E2 must not skip DI strong E4 minting."""
    bundle = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("paddleocr", "125.00"),
            _cand("rapidocr", "125.00"),
            _cand("azure_document_intelligence_read", "125.00"),
        ],
        registration_confidence=0.95,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID", "HARD_VALIDATION_PASSED"},
        hard_validation_passed=True,
    )
    assert any(
        item.evidence_class.value == "E2"
        and item.independent
        and (item.metadata or {}).get("agreement_type") == "CHARGE_DI_PARTNER_AGREEMENT"
        for item in bundle.items
    )
    assert any(
        item.evidence_class.value == "E4"
        and (item.metadata or {}).get("strength") == "STRONG"
        and (item.metadata or {}).get("fact") == "CHARGE_DI_LOCAL_CONFIRMED"
        for item in bundle.items
    )


def test_charge_di_paddle_partner_mints_strong_e4():
    """EJGE.010: DI + paddle alone (no rapid) still confirms charge."""
    bundle = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _cand("paddleocr", "9800.00"),
            _cand("azure_document_intelligence_read", "9800.00"),
        ],
        registration_confidence=0.95,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID", "HARD_VALIDATION_PASSED"},
        hard_validation_passed=True,
    )
    assert any(
        item.evidence_class.value == "E4"
        and (item.metadata or {}).get("strength") == "STRONG"
        for item in bundle.items
    )


def test_cash_ruling_split_di_mints_e4_beside_junk_insert_paddle():
    """DJKH.002: DI raw ``7 $ 157 :07`` + Claude 157.07 ignore paddle 1571.07 soup."""
    from packages.domain.common import BoundingBox

    def _raw_cand(engine, value, raw):
        return OCRCandidate(
            value=value,
            raw_value=raw,
            engine=engine,
            model_name=engine,
            model_version="test",
            preprocessing_variant="test",
            raw_confidence=0.9,
            calibrated_confidence=0.9,
            bounding_box=BoundingBox(
                x0=0, y0=0, x1=10, y1=10, image_width=20, image_height=20
            ),
            latency_ms=0.0,
        )

    bundle = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _raw_cand(
                "azure_document_intelligence_read", "157.00", "7 $ 157 :07"
            ),
            _raw_cand("anthropic_claude_crop", "157.07", "157.07"),
            _raw_cand("paddleocr", "1571.07", "157107"),
        ],
        registration_confidence=0.95,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID", "HARD_VALIDATION_PASSED"},
        hard_validation_passed=True,
    )
    assert any(
        item.evidence_class.value == "E4"
        and (item.metadata or {}).get("fact") == "CHARGE_DI_LOCAL_CONFIRMED"
        for item in bundle.items
    )
    e2 = [
        item
        for item in bundle.items
        if item.evidence_class.value == "E2" and item.independent
    ]
    assert e2 and e2[0].value == "157.07"


def test_newline_ruling_split_di_glue_mints_e4():
    """M0463JEM.017: Rapid ``523\\n156`` → 523.56; DI glued ``523156`` corroborates."""
    from packages.domain.common import BoundingBox

    def _raw_cand(engine, value, raw):
        return OCRCandidate(
            value=value,
            raw_value=raw,
            engine=engine,
            model_name=engine,
            model_version="test",
            preprocessing_variant="test",
            raw_confidence=0.9,
            calibrated_confidence=0.9,
            bounding_box=BoundingBox(
                x0=0, y0=0, x1=10, y1=10, image_width=20, image_height=20
            ),
            latency_ms=0.0,
        )

    bundle = build_evidence_bundle(
        field_name="total_charge",
        candidates=[
            _raw_cand("rapidocr", "156.00", "523\n156\nS"),
            _raw_cand(
                "azure_document_intelligence_read", "523156.00", "523156 $"
            ),
            _raw_cand("paddleocr", "523156.00", "523156"),
        ],
        registration_confidence=0.95,
        wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID", "HARD_VALIDATION_PASSED"},
        hard_validation_passed=True,
    )
    assert any(
        item.evidence_class.value == "E4"
        and (item.metadata or {}).get("fact") == "CHARGE_DI_LOCAL_CONFIRMED"
        for item in bundle.items
    )
    e2 = [
        item
        for item in bundle.items
        if item.evidence_class.value == "E2" and item.independent
    ]
    assert e2 and e2[0].value == "523.56"
