"""AI conflict agent picks one OCR rival and clears field review."""

from packages.extraction_recovery.conflict_agent import (
    collect_field_rivals,
    field_needs_conflict_agent,
    maybe_attach_conflict_agent_to_field_row,
    maybe_resolve_financial_conflict,
    resolve_field_conflict,
    resolve_financial_conflict,
    _match_financial_side,
    _match_rival,
)
from PIL import Image


class _FakeEngine:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def recognize_fields(self, crops, *, field_types, descriptions, prior_candidates):
        from packages.extraction_recovery.gpt4o_crop_residual import Gpt4oCropResidualResult

        self.calls += 1
        del field_types, descriptions, prior_candidates
        out = {}
        for name in crops:
            out[name] = Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=False,
                value=self.reply,
                raw_value=self.reply,
                shaped=True,
                insufficient_evidence=False,
                reason="CLAUDE_SHAPED",
                engine="anthropic_claude_crop",
                confidence=0.95,
            )
        return out


def test_collect_rivals_and_needs_agent():
    cands = [
        {"engine": "paddleocr", "value": "4972.00"},
        {"engine": "rapidocr", "value": "49.72"},
        {"engine": "azure_document_intelligence_read", "value": "4972.00"},
    ]
    rivals = collect_field_rivals("total_charge", cands)
    assert len(rivals) == 2
    assert field_needs_conflict_agent("total_charge", cands)
    assert not field_needs_conflict_agent(
        "total_charge",
        [
            {"engine": "paddleocr", "value": "49.72"},
            {"engine": "rapidocr", "value": "49.72"},
        ],
    )


def test_match_rival_and_financial_side():
    assert _match_rival("49.72", ["49.72", "4972.00"], "total_charge") == "49.72"
    assert _match_rival("$4,972.00", ["49.72", "4972.00"], "total_charge") == "4972.00"
    assert _match_rival("ABSTAIN", ["49.72", "4972.00"], "total_charge") is None
    assert _match_financial_side("BOX28") == "BOX28"
    assert _match_financial_side("use the line sum") == "LINES"
    assert _match_financial_side("unsure") is None


def test_field_conflict_agent_adopts_chosen_rival(monkeypatch):
    monkeypatch.setenv("CDP_CONFLICT_AGENT", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    row = {
        "field": "total_charge",
        "ocr_region": [10, 10, 80, 40],
        "candidates": [
            {"engine": "paddleocr", "value": "405.00"},
            {"engine": "azure_document_intelligence_read", "value": "495.00"},
        ],
        "cascade": {"accepted": False},
    }
    engine = _FakeEngine("495.00")
    updated = maybe_attach_conflict_agent_to_field_row(
        row,
        image=Image.new("RGB", (100, 50), "white"),
        engine=engine,
    )
    assert updated["conflict_agent"]["resolved"] is True
    assert updated["cascade"]["value"] == "495.00"
    assert updated["candidates"][0]["value"] == "495.00"
    assert engine.calls == 1


def test_field_conflict_agent_idempotent_skips_second_claude(monkeypatch):
    """Residual + end-of-OCR must not pay Claude twice on the same field."""
    monkeypatch.setenv("CDP_CONFLICT_AGENT", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    row = {
        "field": "total_charge",
        "ocr_region": [10, 10, 80, 40],
        "candidates": [
            {"engine": "paddleocr", "value": "405.00"},
            {"engine": "azure_document_intelligence_read", "value": "495.00"},
        ],
        "cascade": {"accepted": False},
    }
    engine = _FakeEngine("495.00")
    img = Image.new("RGB", (100, 50), "white")
    once = maybe_attach_conflict_agent_to_field_row(row, image=img, engine=engine)
    assert engine.calls == 1
    twice = maybe_attach_conflict_agent_to_field_row(once, image=img, engine=engine)
    assert engine.calls == 1
    assert twice["conflict_agent"]["chosen"] == once["conflict_agent"]["chosen"]
    assert sum(
        1
        for a in twice.get("attempts") or []
        if "conflict_agent" in str(a.get("engine") or "").casefold()
    ) == 1


def test_financial_conflict_agent_prefers_box28(monkeypatch):
    monkeypatch.setenv("CDP_CONFLICT_AGENT", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    fields = [
        {
            "field": "total_charge",
            "ocr_region": [10, 10, 80, 40],
            "candidates": [
                {"engine": "paddleocr", "value": "783.00"},
                {"engine": "rapidocr", "value": "783.00"},
            ],
        }
    ]
    lines = [
        {"charges": "261.00", "canonical_region": [1, 1, 2, 2]},
        {"charges": "261.00", "canonical_region": [1, 2, 2, 3]},
    ]
    out_fields, _ = maybe_resolve_financial_conflict(
        image=Image.new("RGB", (100, 50), "white"),
        fields=fields,
        service_lines=lines,
        engine=_FakeEngine("BOX28"),
    )
    agent = out_fields[0]["financial_conflict_agent"]
    assert agent["side"] == "BOX28"
    assert agent["value"] == "783.00"


def test_financial_conflict_rewrites_glued_box28_to_ruling_split(monkeypatch):
    """BOX28 pick of glued ``523156`` becomes ruled ``523.56`` from Rapid raw."""
    monkeypatch.setenv("CDP_CONFLICT_AGENT", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    fields = [
        {
            "field": "total_charge",
            "ocr_region": [10, 10, 80, 40],
            "candidates": [
                {
                    "engine": "rapidocr",
                    "value": "156.00",
                    "raw_value": "523\n156\nS",
                },
                {
                    "engine": "azure_document_intelligence_read",
                    "value": "523156.00",
                    "raw_value": "523156 $",
                },
            ],
        }
    ]
    lines = [
        {"charges": "250.00", "canonical_region": [1, 1, 2, 2]},
        {"charges": "250.00", "canonical_region": [1, 2, 2, 3]},
    ]
    out_fields, _ = maybe_resolve_financial_conflict(
        image=Image.new("RGB", (100, 50), "white"),
        fields=fields,
        service_lines=lines,
        engine=_FakeEngine("BOX28"),
    )
    agent = out_fields[0]["financial_conflict_agent"]
    assert agent["side"] == "BOX28"
    assert agent["value"] == "523.56"
    assert out_fields[0]["value"] == "523.56"


def test_cents_column_prefers_line_without_asking_claude(monkeypatch):
    monkeypatch.setenv("CDP_CONFLICT_AGENT", "1")
    fields = [
        {
            "field": "total_charge",
            "ocr_region": [10, 10, 80, 40],
            "candidates": [
                {"engine": "paddleocr", "value": "4972.00"},
                {"engine": "azure_document_intelligence_read", "value": "4972.00"},
            ],
        }
    ]
    lines = [
        {
            "charges": "49.77",
            "candidates": [
                {"engine": "rapidocr", "value": "49.77"},
                {"engine": "anthropic_claude_crop", "value": "4972.00"},
            ],
        }
    ]
    out_fields, _ = maybe_resolve_financial_conflict(
        image=Image.new("RGB", (100, 50), "white"),
        fields=fields,
        service_lines=lines,
        engine=_FakeEngine("BOX28"),  # would wrongly pick box if asked
    )
    agent = out_fields[0]["financial_conflict_agent"]
    assert agent["side"] == "LINES"
    assert agent["value"] == "49.77"
    assert "CENTS_COLUMN" in agent["reason"]
    assert out_fields[0]["candidates"][0]["model_version"] == "conflict-agent-v1"


def test_financial_conflict_agent_abstain_keeps_hitl(monkeypatch):
    monkeypatch.setenv("CDP_CONFLICT_AGENT", "1")
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "1")
    fields = [
        {
            "field": "total_charge",
            "ocr_region": [10, 10, 80, 40],
            "candidates": [{"engine": "paddleocr", "value": "783.00"}],
        }
    ]
    lines = [{"charges": "261.00"}, {"charges": "261.00"}]
    out_fields, _ = maybe_resolve_financial_conflict(
        image=Image.new("RGB", (100, 50), "white"),
        fields=fields,
        service_lines=lines,
        engine=_FakeEngine("ABSTAIN"),
    )
    assert "financial_conflict_agent" not in out_fields[0]
    assert out_fields[0]["conflict_agent"]["resolved"] is False


def test_field_needs_conflict_skips_when_name_locals_settled():
    cands = [
        {"engine": "paddleocr", "value": "SMITH, JOHN"},
        {"engine": "rapidocr", "value": "SMITH, JOHN"},
        {"engine": "anthropic_claude_crop", "value": "SMITH JOHN"},
    ]
    # Soft-equivalent locals settle → no conflict agent on names.
    assert field_needs_conflict_agent("patient_name", cands) is False
    # Charge rivals still need the agent.
    charge = [
        {"engine": "paddleocr", "value": "50.00"},
        {"engine": "rapidocr", "value": "660.00"},
    ]
    assert field_needs_conflict_agent("total_charge", charge) is True
