"""Crop-scoped Azure DI charge residual tests."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from packages.extraction_recovery.charge_azure_di_residual import (
    ChargeAzureDiResidualResult,
    _expand_bbox,
    is_charge_local_residual,
    maybe_attach_charge_azure_di_to_field_row,
    promote_currency_shaped,
    residual_candidate_dict,
    run_charge_azure_di_residual,
    try_charge_azure_di_crop,
)
from packages.tool_escalation import EscalationTool, plan_field_escalation
from scripts.ocr_from_geometry import prefer_currency_without_digit_drop


@dataclass
class _FakeCropEngine:
    text: str

    def recognize_crop(
        self, crop: Image.Image, field_name: str
    ) -> ChargeAzureDiResidualResult:
        assert crop.size[0] > 0 and crop.size[1] > 0
        assert field_name in {"charges", "total_charge"}
        return ChargeAzureDiResidualResult(
            attempted=True,
            configured=True,
            review_only=True,
            value=self.text,
            raw_value=self.text,
            currency_shaped=True,
            reason="AZURE_DI_CURRENCY_SHAPED_REVIEW_ONLY",
            validation_results=("SHADOW_REVIEW_ONLY",),
        )


def test_is_charge_local_residual_gates():
    assert is_charge_local_residual(
        field_name="charges",
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        local_accepted=False,
    )
    assert not is_charge_local_residual(
        field_name="charges",
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        local_accepted=True,
    )
    assert is_charge_local_residual(
        field_name="charges",
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        local_accepted=True,
        corroborate=True,
    )
    assert not is_charge_local_residual(
        field_name="patient_dob",
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        local_accepted=False,
    )


def test_planner_selects_azure_di_for_charge_crop(monkeypatch):
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    decision = plan_field_escalation(
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        field_name="charges",
        regional_ocr_attempted=True,
        azure_di_attempted=False,
    )
    assert decision.tool == EscalationTool.AZURE_DOCUMENT_INTELLIGENCE_READ


def test_planner_charge_conflict_before_docling(monkeypatch):
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    decision = plan_field_escalation(
        gap_class="CHARGE_DIGIT_CONFLICT",
        field_name="total_charge",
        regional_ocr_attempted=True,
        empty_financial_ink=True,
        azure_di_attempted=False,
    )
    assert decision.tool == EscalationTool.AZURE_DOCUMENT_INTELLIGENCE_READ


def test_planner_prefers_gpt4o_when_charge_di_disabled(monkeypatch):
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "0")
    decision = plan_field_escalation(
        gap_class="LINE_SUM_UNCORROBORATED",
        field_name="total_charge",
        regional_ocr_attempted=True,
        empty_financial_ink=True,
        azure_di_attempted=False,
    )
    assert decision.tool == EscalationTool.AZURE_GPT4O


def test_charge_di_residual_defaults_on_for_accuracy(monkeypatch):
    """Accuracy-first: DI charge residual ON by default (MISSING_E4 path)."""
    monkeypatch.delenv("CDP_AZURE_DI_CHARGE_RESIDUAL", raising=False)
    from packages.extraction_recovery.charge_azure_di_residual import (
        azure_di_charge_residual_enabled,
    )

    assert azure_di_charge_residual_enabled() is True
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "0")
    assert azure_di_charge_residual_enabled() is False
    decision = plan_field_escalation(
        gap_class="LINE_SUM_UNCORROBORATED",
        field_name="total_charge",
        regional_ocr_attempted=True,
        empty_financial_ink=True,
        azure_di_attempted=False,
        service_line_rows_missing=False,
    )
    assert decision.tool == EscalationTool.AZURE_GPT4O


def test_run_charge_azure_di_with_injected_engine(monkeypatch):
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_ACCEPT", "1")
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    result = run_charge_azure_di_residual(
        image=img,
        bbox=(10, 10, 180, 70),
        field_name="charges",
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        engine=_FakeCropEngine("1571.00"),
    )
    assert result.attempted is True
    assert result.currency_shaped is True
    promoted = promote_currency_shaped(result)
    assert promoted.review_only is False
    assert promoted.value == "1571.00"
    cand = residual_candidate_dict(promoted)
    assert cand is not None
    assert cand["engine"] == "azure_document_intelligence_read"


@dataclass
class _SizeSensitiveCropEngine:
    """JAJ.022-class: tight crop → label soup; expanded crop → currency."""

    min_area: int
    text: str
    calls: int = 0

    def recognize_crop(
        self, crop: Image.Image, field_name: str
    ) -> ChargeAzureDiResidualResult:
        self.calls += 1
        area = crop.size[0] * crop.size[1]
        if area < self.min_area:
            return ChargeAzureDiResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value="C -- C L $",
                raw_value="C -- C L $",
                currency_shaped=False,
                reason="AZURE_DI_UNSHAPED",
            )
        return ChargeAzureDiResidualResult(
            attempted=True,
            configured=True,
            review_only=True,
            value=self.text,
            raw_value=self.text,
            currency_shaped=True,
            reason="AZURE_DI_CURRENCY_SHAPED_REVIEW_ONLY",
            validation_results=("SHADOW_REVIEW_ONLY",),
        )


def test_expand_bbox_pads_within_image():
    assert _expand_bbox((100, 100, 200, 150), (1000, 1000), pad_ratio=0.35) == (
        65,
        83,
        235,
        167,
    )


def test_run_charge_azure_di_retries_expanded_crop(monkeypatch):
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_ACCEPT", "1")
    img = Image.new("RGB", (400, 200), color=(240, 240, 240))
    # Paint ink so blank-skip does not fire on either crop.
    for x in range(40, 360):
        for y in range(40, 160):
            img.putpixel((x, y), (20, 20, 20))
    engine = _SizeSensitiveCropEngine(min_area=120 * 80, text="635.00")
    result = run_charge_azure_di_residual(
        image=img,
        bbox=(100, 80, 220, 130),
        field_name="total_charge",
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        engine=engine,
    )
    assert engine.calls == 2
    assert result.currency_shaped is True
    assert result.value == "635.00"
    assert "EXPANDED_CROP" in result.reason


def test_try_charge_digit_drop_vs_local():
    """DI longer twin preferred over truncated local fast read."""
    preferred = prefer_currency_without_digit_drop("157.00", "1571.00")
    assert preferred == "1571.00"


def test_attach_skips_accepted_local_charge_when_corroborate_off(monkeypatch):
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_CORROBORATE", "0")
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    row = {
        "field": "total_charge",
        "canonical_region": [10, 10, 180, 70],
        "ocr_region": [10, 10, 180, 70],
        "candidates": [{"value": "270.00", "engine": "paddleocr"}],
        "cascade": {"accepted": True, "accept_reason": "LINE_TOTALS"},
    }
    updated = maybe_attach_charge_azure_di_to_field_row(
        row,
        image=img,
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        engine=_FakeCropEngine("1364.00"),
    )
    assert updated["azure_di_residual"]["reason"] == "NOT_CHARGE_LOCAL_RESIDUAL"


def test_attach_corroborates_accepted_local_charge(monkeypatch):
    """HJHO.005-class: weak local accept still gets box-28 DI twin."""
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_CORROBORATE", "1")
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_ACCEPT", "1")
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    row = {
        "field": "total_charge",
        "canonical_region": [10, 10, 180, 70],
        "ocr_region": [10, 10, 180, 70],
        "candidates": [{"value": "315.00", "engine": "paddleocr"}],
        "cascade": {"accepted": True, "accept_reason": "LINE_TOTALS", "value": "315.00"},
    }
    updated = maybe_attach_charge_azure_di_to_field_row(
        row,
        image=img,
        gap_class=None,
        engine=_FakeCropEngine("353.00"),
        corroborate=True,
    )
    assert updated["azure_di_residual"]["attempted"] is True
    assert updated["azure_di_residual"]["currency_shaped"] is True
    assert updated["azure_di_residual"]["value"] == "353.00"
    assert any(
        c.get("engine") == "azure_document_intelligence_read"
        and c.get("value") == "353.00"
        for c in updated["candidates"]
    )
    # Non-twin DI must not silently override local LINE_TOTALS accept.
    assert "LOCAL_CONFLICT_REVIEW" in updated["azure_di_residual"]["reason"]
    assert updated["cascade"].get("value") == "315.00"


def test_attach_does_not_let_di_supersede_a_shorter_local(monkeypatch):
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_CORROBORATE", "1")
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_ACCEPT", "1")
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    row = {
        "field": "total_charge",
        "canonical_region": [10, 10, 180, 70],
        "ocr_region": [10, 10, 180, 70],
        "candidates": [{"value": "157.00", "engine": "paddleocr"}],
        "cascade": {"accepted": True, "accept_reason": "LINE_TOTALS", "value": "157.00"},
    }
    updated = maybe_attach_charge_azure_di_to_field_row(
        row,
        image=img,
        gap_class=None,
        engine=_FakeCropEngine("1571.00"),
        corroborate=True,
    )
    assert updated["cascade"]["accepted"] is True
    # A longer DI read is not a local digit-drop confirm. 157 stays 157.
    assert updated["cascade"]["value"] == "157.00"
    assert "LOCAL_CONFLICT_REVIEW" in updated["azure_di_residual"]["reason"]


def test_attach_promotes_currency_shaped_on_miss(monkeypatch):
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_ACCEPT", "1")
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    row = {
        "field": "charges",
        "canonical_region": [10, 10, 180, 70],
        "ocr_region": [10, 10, 180, 70],
        "candidates": [],
        "cascade": {"accepted": False, "accept_reason": "EMPTY"},
    }
    updated = maybe_attach_charge_azure_di_to_field_row(
        row,
        image=img,
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        engine=_FakeCropEngine("701.00"),
    )
    assert updated["azure_di_residual"]["attempted"] is True
    assert updated["azure_di_residual"]["currency_shaped"] is True
    assert updated["cascade"]["accepted"] is True
    assert any(
        c.get("engine") == "azure_document_intelligence_read"
        for c in updated["candidates"]
    )


def test_try_charge_disabled(monkeypatch):
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "0")
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    result = try_charge_azure_di_crop(
        img, (10, 10, 180, 70), engine=_FakeCropEngine("100.00")
    )
    assert result.attempted is False
    assert result.reason == "AZURE_DI_CHARGE_RESIDUAL_DISABLED"


def test_charge_crop_looks_blank_on_white():
    from packages.extraction_recovery.charge_azure_di_residual import (
        charge_crop_looks_blank,
    )

    blank = Image.new("RGB", (200, 80), color=(255, 255, 255))
    assert charge_crop_looks_blank(blank) is True
    inked = Image.new("RGB", (200, 80), color=(255, 255, 255))
    for x in range(20, 160):
        for y in range(20, 55):
            inked.putpixel((x, y), (20, 20, 20))
    assert charge_crop_looks_blank(inked) is False


def test_blank_crop_skips_real_azure_path(monkeypatch):
    """Empty white box-28 must not spend an F0 analyze slot."""
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    img = Image.new("RGB", (200, 80), color=(255, 255, 255))
    result = run_charge_azure_di_residual(
        image=img,
        bbox=(10, 10, 180, 70),
        field_name="total_charge",
        gap_class="CHARGE_LOCAL_EXHAUSTED",
        engine=None,
    )
    assert result.attempted is False
    assert result.reason == "AZURE_DI_SKIPPED_BLANK_CROP"


def test_service_line_di_budget_defaults_to_one(monkeypatch):
    from scripts.ocr_from_geometry import _azure_di_service_line_budget

    monkeypatch.delenv("CDP_AZURE_DI_SERVICE_LINE_BUDGET", raising=False)
    assert _azure_di_service_line_budget() == 1
    monkeypatch.setenv("CDP_AZURE_DI_SERVICE_LINE_BUDGET", "0")
    assert _azure_di_service_line_budget() == 0
    monkeypatch.setenv("CDP_AZURE_DI_SERVICE_LINE_BUDGET", "3")
    assert _azure_di_service_line_budget() == 3
