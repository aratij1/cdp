"""LineChargeSelector — charge-column selection without Box 28 / line-sum."""

from packages.claim_evidence.line_charge_selector import (
    apply_line_charge_selector,
    select_line_charge,
)
from packages.claim_evidence.financial_geometry_authority import (
    evaluate_financial_geometry_arithmetic,
)


def _cand(engine, value, raw=None, bbox=None):
    payload = {
        "engine": engine,
        "value": value,
        "raw_value": raw if raw is not None else value,
    }
    if bbox is not None:
        x0, y0, x1, y1 = bbox
        payload["bounding_box"] = {
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "image_width": 1712,
            "image_height": 2214,
        }
    return payload


# Charge-column band inside Box 24F (reference px).
_CHARGE_BBOX = (1050.0, 1458.0, 1180.0, 1513.0)
_UNITS_BBOX = (1210.0, 1458.0, 1280.0, 1513.0)
_POS_BBOX = (420.0, 1458.0, 470.0, 1513.0)


def test_selects_dual_local_stem_over_units_concat():
    """6401 bleed loses to dual-local 640.00 in the charge column."""
    line = {
        "charges": "6401.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "640.00", "640", _CHARGE_BBOX),
            _cand("rapidocr", "640.00", "640", _CHARGE_BBOX),
            _cand("paddleocr", "6401.00", "6401", _CHARGE_BBOX),
            _cand("rapidocr", "640.40", "64040", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "640.00"


def test_three_digit_units_concat_loses_to_local_stem():
    """DJKH.048: dollars-ruling ``701`` beside Claude+paddle ``70`` is units bleed."""
    line = {
        "charges": "701.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "70.00", "70.00", _CHARGE_BBOX),
            _cand("paddleocr", "70.00", "70!00", _CHARGE_BBOX),
            _cand("rapidocr", "7010.00", "7010(", _CHARGE_BBOX),
            _cand("paddleocr", "701.00", "701C", _CHARGE_BBOX),
            _cand("rapidocr", "701.00", "701C", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "70.00"
    out = apply_line_charge_selector([line])
    assert out[0]["charges"] == "70.00"


def test_whitelist_underread_does_not_units_concat_real_charge():
    """EJG7.001: whitelist ``51`` from ``5100`` must not veto dual-local ``510``."""
    line = {
        "charges": "510.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "510.00", "510.00", _CHARGE_BBOX),
            _cand("paddleocr", "510.00", "510", _CHARGE_BBOX),
            _cand("rapidocr", "510.00", "510", _CHARGE_BBOX),
            _cand("paddleocr", "51.00", "5100", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "510.00"


def test_ambiguous_tiny_single_local_does_not_enter_line_sum():
    """EJG7.017: ``1.01`` from ``1\\n01`` must not inflate Σ past Box 28 ``175``."""
    lines = [
        {
            "charges": "175.00",
            "canonical_region": list(_CHARGE_BBOX),
            "candidates": [
                _cand("paddleocr", "175.00", "175", _CHARGE_BBOX),
                _cand("rapidocr", "175.00", "175", _CHARGE_BBOX),
            ],
        },
        {
            "charges": "1.01",
            "canonical_region": list(_CHARGE_BBOX),
            "candidates": [
                _cand("paddleocr", "01.00", "0\n01", _CHARGE_BBOX),
                _cand("rapidocr", "01.00", "1\n01", _CHARGE_BBOX),
            ],
        },
    ]
    out = apply_line_charge_selector(lines)
    assert out[0]["charges"] == "175.00"
    assert out[1].get("charges") in (None, "")
    assert out[1].get("line_charge_ambiguous")


def test_rejects_pos_shell_and_selects_real_charge():
    """Selected 1.00 junk loses to dual-local 270.00."""
    line = {
        "charges": "1.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "1.00", "1", _POS_BBOX),
            _cand("paddleocr", "270.00", "270", _CHARGE_BBOX),
            _cand("rapidocr", "270.00", "270", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "270.00"


def test_rejects_units_column_overlap():
    line = {
        "charges": "2.00",
        "candidates": [
            _cand("paddleocr", "2.00", "2", _UNITS_BBOX),
            _cand("rapidocr", "2.00", "2", _UNITS_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "UNREADABLE_LINE_CHARGE"


def test_place_shift_4972_rejected_when_49_72_present():
    line = {
        "charges": "4972.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "4972.00", "4972", _CHARGE_BBOX),
            _cand("rapidocr", "49.72", "49.72", _CHARGE_BBOX),
            _cand("paddleocr", "49.72", "49.72", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "49.72"


def test_vision_fuller_not_vetoed_by_local_underread_place_shift():
    """DJJM.016-class: paddle 1.75 must not mark rapid+Claude 175.00 as soup."""
    line = {
        "charges": "1.75",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "1.75", "1\n1.75\n0", _CHARGE_BBOX),
            _cand("rapidocr", "175.00", "1\nia\n175.", _CHARGE_BBOX),
            _cand("anthropic_claude_crop", "175.00", "175.00", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "175.00"
    assert result.amount != "1.75"


def test_claude_only_fuller_beats_paddle_place_shift_under_read():
    """EJGE.003 L2: Claude 150.00 must win over paddle 1.50 geometry under-read."""
    line = {
        "charges": "1.50",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "150.00", "150.00", _CHARGE_BBOX),
            _cand("paddleocr", "1.50", "1.50", _CHARGE_BBOX),
            _cand(
                "paddleocr",
                "1.50",
                "1.5ni\nn",
                _CHARGE_BBOX,
            ),
        ],
    }
    # Tag dollars_ruling-style geometry on the under-read.
    line["candidates"][1]["preprocessing_variant"] = "CURRENCY_DECIMAL_V2|dollars_ruling"
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "150.00"
    assert result.amount != "1.50"


def test_bare_digit_soup_alone_is_ambiguous_not_selected():
    """4972 with no observed-decimal peer stays conflict/HITL, not SELECTED."""
    line = {
        "charges": "4972.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "4972.00", "4972", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "4972.00", "4972.00", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "AMBIGUOUS_LINE_CHARGE"
    assert result.reason in {
        "ONLY_BLEED_OR_SOUP_CANDIDATES",
        "NO_DUAL_LOCAL_AGREEMENT",
    }


def test_cents_first_raw_00_212_selects_dual_local():
    """OCR ``00\\n212`` must not collapse to SELECTION_NOISE 0.00."""
    line = {
        "charges": "212.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "212.00", "00\n212", _CHARGE_BBOX),
            _cand("rapidocr", "212.00", "00\n212", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "212.00", "212.00", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "212.00"
    assert result.reason == "DUAL_LOCAL_CHARGE_COLUMN"


def test_dollars_ruling_bbox_near_cents_line_is_in_column():
    """Dollars-ruling crop ending at x1≈1161 must still count as charge-column."""
    dollars_bbox = (1050.0, 1458.0, 1161.0, 1513.0)
    line = {
        "charges": "212.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "212.00", "212", dollars_bbox),
            _cand("rapidocr", "212.00", "212", dollars_bbox),
            _cand("azure_gpt4o_crop", "212.00", "212.00", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "212.00"


def test_geometry_cents_attempt_promoted_over_bare_soup():
    """GEOMETRY_CENTS on attempts unlocks selection when candidates are soup."""
    line = {
        "charges": "4972.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "4972.00", "4972", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "4972.00", "4972.00", _CHARGE_BBOX),
        ],
        "attempts": [
            {
                "engine": "rapidocr",
                "reason": "GEOMETRY_CENTS",
                "observation": {
                    "shaped": "49.72",
                    "raw_digit_sequence": "4972",
                    "canonical_monetary_value": "49.72",
                },
            }
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "49.72"


def test_dollars_ruling_truncation_does_not_beat_geometry():
    """Dual-local ``129.00`` must not erase GEOMETRY_CENTS ``1291.15``."""
    dollars_bbox = (1050.0, 1458.0, 1160.0, 1513.0)
    line = {
        "charges": "1291.15",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("azure_gpt4o_crop", "129.15", "129.15", _CHARGE_BBOX),
            _cand("paddleocr", "12919.00", "12919", _CHARGE_BBOX),
            _cand("paddleocr", "129.00", "129\n1", dollars_bbox),
            _cand("rapidocr", "129.00", "11\n129", dollars_bbox),
        ],
        "attempts": [
            {
                "engine": "rapidocr",
                "reason": "GEOMETRY_CENTS",
                "observation": {
                    "shaped": "1291.15",
                    "raw_digit_sequence": "129115",
                    "canonical_monetary_value": "1291.15",
                },
            }
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "AMBIGUOUS_LINE_CHARGE"
    assert result.reason == "DOLLARS_TRUNCATION_VS_FULLER_READ"


def test_vision_fuller_cents_selected_when_locals_are_dollars_truncation():
    """Claude/gpt-4o ``157.07`` wins over dual-local dollars-ruling ``157.00``."""
    dollars_bbox = (1050.0, 1458.0, 1165.0, 1513.0)
    line = {
        "charges": "1571.07",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "157.07", "157.07", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "157.07", "157.07", _CHARGE_BBOX),
            _cand("paddleocr", "15707.00", "15707", _CHARGE_BBOX),
            _cand("paddleocr", "157.00", "157", dollars_bbox),
            _cand("rapidocr", "157.00", "157", dollars_bbox),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "157.07"
    assert result.reason == "VISION_FULLER_DOLLARS_STEM_CORROBORATED"


def test_dual_vision_overrides_geometry_cents_place_shift_soup():
    """gpt-4o+Claude 157.07 beat GEOMETRY_CENTS 1571.07 when locals stem-agree."""
    dollars_bbox = (1050.0, 1458.0, 1165.0, 1513.0)
    line = {
        "charges": "1571.07",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "157.07", "157.07", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "157.07", "157.07", _CHARGE_BBOX),
            _cand("paddleocr", "157.00", "157", dollars_bbox),
            _cand("rapidocr", "157.00", "157", dollars_bbox),
        ],
        "attempts": [
            {
                "engine": "rapidocr",
                "reason": "GEOMETRY_CENTS",
                "observation": {
                    "shaped": "1571.07",
                    "canonical_monetary_value": "1571.07",
                },
            }
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "157.07"
    assert result.reason == "DUAL_VISION_FULLER_DOLLARS_STEM_CORROBORATED"


def test_units_prefix_raw_keeps_trailing_dollars_stem():
    """``70\\\\n157`` is units bleed then dollars, not dual-local 70.00."""
    from packages.claim_evidence.line_charge_selector import _shaped_amount

    shaped = _shaped_amount(_cand("paddleocr", "157.00", "70\n157", _CHARGE_BBOX))
    assert shaped == "157.00"
    shaped7 = _shaped_amount(_cand("paddleocr", "157.00", "7c\n157", _CHARGE_BBOX))
    assert shaped7 == "157.00"


def test_dual_vision_selects_when_locals_only_have_units_bleed():
    """DJKH.008-class: Claude+gpt4o 157.07 wins with no dual-local 157.00."""
    line = {
        "charges": "1571.07",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "157.07", "157.07", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "157.07", "157.07", _CHARGE_BBOX),
            # Upstream value is 157.00 but raw was units-prefix bleed.
            _cand("paddleocr", "157.00", "70\n157", _CHARGE_BBOX),
            _cand("rapidocr", "15710.00", "15710:", _CHARGE_BBOX),
            _cand("rapidocr", "1571.00", "1571c", _CHARGE_BBOX),
        ],
        "attempts": [
            {
                "engine": "rapidocr",
                "reason": "GEOMETRY_CENTS",
                "observation": {
                    "shaped": "1571.07",
                    "canonical_monetary_value": "1571.07",
                },
            }
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "157.07"
    assert result.reason in {
        "DUAL_VISION_AGREEMENT_WITHOUT_DUAL_LOCAL",
        "DUAL_VISION_FULLER_DOLLARS_STEM_CORROBORATED",
        "VISION_FULLER_DOLLARS_STEM_CORROBORATED",
    }


def test_whole_dollar_place_shift_is_not_dollars_truncation():
    """``116.00`` vs ``1165.00`` is digit insertion, not cents fuller."""
    from packages.claim_evidence.line_charge_selector import _is_dollar_truncation

    assert not _is_dollar_truncation("116.00", "1165.00")
    assert _is_dollar_truncation("157.00", "157.07")
    assert _is_dollar_truncation("129.00", "1291.15")


def test_dual_vision_rejects_whole_dollar_place_shift_without_geo():
    """DJJM.036-class: dual vision ``1165.00`` must not win via ``116.00`` stem."""
    line = {
        "charges": "1165.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "1165.00", "1165.00", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "1165.00", "1165.00", _CHARGE_BBOX),
            _cand("paddleocr", "11.00", "11h5", _CHARGE_BBOX),
            _cand("rapidocr", "116.00", "116.5", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.amount != "1165.00"
    assert result.disposition == "AMBIGUOUS_LINE_CHARGE"


def test_vision_fuller_beats_peer_place_shift_soup_without_dual_local():
    """DJKH.018-class: Claude ``25.43`` + local ``25.00`` beats gpt-4o ``25143``."""
    line = {
        "charges": "25143.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "25.43", "25.43", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "25143.00", "25143.00", _CHARGE_BBOX),
            _cand("paddleocr", "25.00", "25", _CHARGE_BBOX),
            _cand("rapidocr", "14.00", "25\n14", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "25.43"
    assert result.reason == "VISION_FULLER_STEM_WITHOUT_DUAL_LOCAL"


def test_ruling_split_raw_reconstructs_cents():
    """Local ``34\\n25`` is dollars|cents ink, not a dual-local 25.00."""
    line = {
        "charges": "25.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "25.00", "34\n25", _CHARGE_BBOX),
            _cand("rapidocr", "25.00", "34\n25", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "34.25", "34.25", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "34.25"


def test_cash_ruling_split_colon_and_pipe_with_scrap():
    """DJKH.002/005: ``7 $ 157 :07`` / ``$ 222 |22`` keep cents, not bare dollars."""
    from packages.claim_evidence.line_charge_selector import _ruling_split_amount

    assert _ruling_split_amount("7 $ 157 :07") == "157.07"
    assert _ruling_split_amount("$ 157 :07 1") == "157.07"
    assert _ruling_split_amount("$ 222 |22") == "222.22"
    assert _ruling_split_amount("J $ 228 |32") == "228.32"


def test_leading_one_cents_bleed_reconstructs_decimal():
    """``523\\n156`` for printed ``523.56`` — drop leading-1 cents bleed, not ``523.00``."""
    from packages.claim_evidence.line_charge_selector import (
        _ruling_split_amount,
        is_ruling_split_digit_glue,
        promote_ruling_split_candidate_value,
    )

    assert _ruling_split_amount("523\n156\nS") == "523.56"
    assert _ruling_split_amount("523 156") == "523.56"
    # Still keep classic dollars|cents and units-bleed behaviors.
    assert _ruling_split_amount("34\n25") == "34.25"
    assert _ruling_split_amount("212\n100") == "212.00"
    assert is_ruling_split_digit_glue("523.56", "523156")
    assert is_ruling_split_digit_glue("523.56", "523156.00")
    assert is_ruling_split_digit_glue("34.25", "3425")
    assert not is_ruling_split_digit_glue("523.56", "500.00")
    # M0463JEM.017: ruling tick OCR'd as junk ``8`` before ``156``.
    assert _ruling_split_amount("LAL\n523\n8156\nS") == "523.56"
    assert _ruling_split_amount("523\n8156") == "523.56"
    cand_corrupt = {
        "engine": "paddleocr",
        "value": "8156.00",
        "raw_value": "LAL\n523\n8156\nS",
        "preprocessing_variant": "CURRENCY_DECIMAL_V2",
    }
    assert promote_ruling_split_candidate_value(cand_corrupt) == "523.56"
    assert cand_corrupt["value"] == "523.56"
    # RapidOCR cents-only span must promote to the ruled total.
    cand = {
        "engine": "rapidocr",
        "value": "156.00",
        "raw_value": "523\n156\nS",
        "preprocessing_variant": "CURRENCY_DECIMAL_V2",
    }
    assert promote_ruling_split_candidate_value(cand) == "523.56"
    assert cand["value"] == "523.56"


def test_units_bleed_tail_keeps_leading_dollars():
    """``212\\n100`` is dollars 212 with units bleed, not dual-local 100.00."""
    line = {
        "charges": "100.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "100.00", "212 i00", _CHARGE_BBOX),
            _cand("rapidocr", "100.00", "212\n100", _CHARGE_BBOX),
            _cand("azure_gpt4o_crop", "212.00", "212.00", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "212.00"


def test_ambiguous_without_dual_local():
    line = {
        "charges": "200.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [_cand("paddleocr", "200.00", "200", _CHARGE_BBOX)],
    }
    result = select_line_charge(line)
    assert result.disposition == "AMBIGUOUS_LINE_CHARGE"


def test_apply_rewrites_service_line_charges():
    lines = [
        {
            "line_number": 1,
            "charges": "6401.00",
            "canonical_region": list(_CHARGE_BBOX),
            "candidates": [
                _cand("paddleocr", "640.00", "640", _CHARGE_BBOX),
                _cand("rapidocr", "640.00", "640", _CHARGE_BBOX),
                _cand("paddleocr", "6401.00", "6401", _CHARGE_BBOX),
            ],
        },
        {
            "line_number": 2,
            "charges": "2601.00",
            "canonical_region": [1050.0, 1513.0, 1180.0, 1568.0],
            "candidates": [
                _cand("paddleocr", "260.00", "260", (1050.0, 1513.0, 1180.0, 1568.0)),
                _cand("rapidocr", "260.00", "260", (1050.0, 1513.0, 1180.0, 1568.0)),
                _cand("paddleocr", "2601.00", "2601", (1050.0, 1513.0, 1180.0, 1568.0)),
            ],
        },
    ]
    out = apply_line_charge_selector(lines)
    assert out[0]["charges"] == "640.00"
    assert out[1]["charges"] == "260.00"
    assert out[0]["line_charge_selection"]["disposition"] == "SELECTED_LOCAL_CHARGE"


def test_financial_geometry_confirms_exact_arithmetic():
    lines = [
        {
            "charges": "115.00",
            "canonical_region": list(_CHARGE_BBOX),
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "115.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
            "candidates": [
                _cand("paddleocr", "115.00", "115.00", _CHARGE_BBOX),
                _cand("rapidocr", "115.00", "115.00", _CHARGE_BBOX),
            ],
        }
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="115.00",
        service_lines=lines,
        box28_observation={
            "text": "115.00",
            "raw_digit_sequence": "11500",
            "canonical_monetary_value": "115.00",
            "adopted": True,
        },
    )
    assert decision.confirmed
    assert decision.amount == "115.00"
    assert decision.reason == "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED"


def test_financial_geometry_ignores_same_stem_box28_twin():
    """1160.40 beside confirmed 1160.00 is OCR twin noise, not a true conflict."""
    lines = [
        {
            "charges": "640.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "640.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
            "candidates": [
                _cand("paddleocr", "640.00", "640", _CHARGE_BBOX),
                _cand("rapidocr", "640.00", "640", _CHARGE_BBOX),
            ],
        },
        {
            "charges": "260.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "260.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
            "candidates": [
                _cand("paddleocr", "260.00", "260", _CHARGE_BBOX),
                _cand("rapidocr", "260.00", "260", _CHARGE_BBOX),
            ],
        },
        {
            "charges": "260.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "260.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
            "candidates": [
                _cand("paddleocr", "260.00", "260", _CHARGE_BBOX),
                _cand("rapidocr", "260.00", "260", _CHARGE_BBOX),
            ],
        },
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="1160.00",
        service_lines=lines,
        box28_field_payload={
            "ranked_candidate": {
                "ocr_candidate": {"value": "1160.00", "raw_value": "1160.00"}
            },
            "alternatives": [
                {"ocr_candidate": {"value": "1160.40", "raw_value": "1160.40"}},
            ],
        },
        box28_observation={
            "text": "1160.00",
            "raw_digit_sequence": "116000",
            "canonical_monetary_value": "1160.00",
            "adopted": True,
        },
    )
    assert decision.confirmed
    assert decision.amount == "1160.00"


def test_financial_geometry_keeps_true_conflict_as_hitl():
    lines = [
        {
            "charges": "260.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "260.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
            "candidates": [
                _cand("paddleocr", "260.00", "260", _CHARGE_BBOX),
                _cand("rapidocr", "260.00", "260", _CHARGE_BBOX),
            ],
        }
    ]
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="2605.00",
        service_lines=lines,
        box28_observation={"text": "2605.00", "raw_digit_sequence": "260500"},
    )
    assert not decision.confirmed
    assert decision.reason == "ARITHMETIC_MISMATCH"


def test_ambiguous_without_amount_clears_unsupported_stale_charges():
    """M.008: geometry 49.77 must not stick when selector amount is null."""
    lines = [
        {
            "line_number": 1,
            "charges": "49.77",
            "canonical_region": list(_CHARGE_BBOX),
            "candidates": [
                _cand("paddleocr", "4972.00", "4972", _CHARGE_BBOX),
                _cand("azure_gpt4o_crop", "4972.00", "4972.00", _CHARGE_BBOX),
            ],
            "attempts": [
                {
                    "engine": "rapidocr",
                    "reason": "GEOMETRY_CENTS",
                    "observation": {
                        "shaped": "49.77",
                        "raw_digit_sequence": "4977",
                        "canonical_monetary_value": "49.77",
                    },
                }
            ],
        }
    ]
    out = apply_line_charge_selector(lines)
    assert out[0]["line_charge_selection"]["disposition"] == "AMBIGUOUS_LINE_CHARGE"
    assert out[0]["line_charge_selection"]["amount"] is None
    assert out[0]["charges"] is None
    assert out[0]["charge_amount"] is None


def test_ambiguous_keeps_charge_when_gpt4o_candidate_supports_it():
    """gpt-4o fuller cents + local dollars stem selects without dual-local."""
    lines = [
        {
            "line_number": 1,
            "charges": "222.22",
            "canonical_region": list(_CHARGE_BBOX),
            "candidates": [
                _cand("azure_gpt4o_crop", "222.22", "222.22", _CHARGE_BBOX),
                _cand("paddleocr", "222.00", "222", _CHARGE_BBOX),
                _cand("rapidocr", "22.00", "22", _CHARGE_BBOX),
            ],
        }
    ]
    out = apply_line_charge_selector(lines)
    assert out[0]["line_charge_selection"]["disposition"] == "SELECTED_LOCAL_CHARGE"
    assert out[0]["line_charge_selection"]["amount"] == "222.22"
    assert out[0]["line_charge_selection"]["reason"] == "VISION_FULLER_STEM_WITHOUT_DUAL_LOCAL"
    assert out[0]["charges"] == "222.22"


def test_same_stem_cents_twin_does_not_force_dollars_truncation_ambiguity():
    """Rapid ``640.40`` beside paddle+Claude ``640.00`` is OCR twin, not fuller.

    DJJF.002-class false AMBIGUOUS left FG summing only one line → FINANCIAL_CONFLICT.
    """
    line = {
        "charges": "640.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "640.00", "640.00", _CHARGE_BBOX),
            _cand("rapidocr", "640.40", "640.400", _CHARGE_BBOX),
            _cand("paddleocr", "64010.00", "64010", _CHARGE_BBOX),
            _cand("anthropic_claude_crop", "640.00", "640.00", _CHARGE_BBOX),
            _cand("rapidocr", "6401.00", "640100", _CHARGE_BBOX),
        ],
        "attempts": [
            {
                "engine": "rapidocr",
                "reason": "GEOMETRY_CENTS",
                "observation": {
                    "shaped": "6401.00",
                    "raw_digit_sequence": "640100",
                    "canonical_monetary_value": "6401.00",
                },
            }
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "640.00"


def test_djjf002_style_lines_sum_confirms_same_stem_box28():
    """Full DJJF.002 path: select all lines, FG confirms 1160.40 twin of Σ 1160."""
    from packages.claim_evidence.financial_geometry_authority import (
        evaluate_financial_geometry_arithmetic,
    )

    lines = [
        {
            "charges": "640.00",
            "canonical_region": list(_CHARGE_BBOX),
            "candidates": [
                _cand("paddleocr", "640.00", "640.00", _CHARGE_BBOX),
                _cand("rapidocr", "640.40", "640.400", _CHARGE_BBOX),
                _cand("anthropic_claude_crop", "640.00", "640.00", _CHARGE_BBOX),
                _cand("rapidocr", "6401.00", "640100", _CHARGE_BBOX),
            ],
            "attempts": [
                {
                    "engine": "rapidocr",
                    "reason": "GEOMETRY_CENTS",
                    "observation": {
                        "shaped": "6401.00",
                        "canonical_monetary_value": "6401.00",
                    },
                }
            ],
        },
        {
            "charges": "260.00",
            "canonical_region": list(_CHARGE_BBOX),
            "candidates": [
                _cand("paddleocr", "260.00", "260.00", _CHARGE_BBOX),
                _cand("rapidocr", "260.00", "260.00", _CHARGE_BBOX),
                _cand("rapidocr", "260.01", "260.01", _CHARGE_BBOX),
                _cand("anthropic_claude_crop", "260.00", "260.00", _CHARGE_BBOX),
                _cand("rapidocr", "2601.00", "260100", _CHARGE_BBOX),
            ],
        },
        {
            "charges": "260.00",
            "canonical_region": list(_CHARGE_BBOX),
            "candidates": [
                _cand("paddleocr", "260.00", "260.00", _CHARGE_BBOX),
                _cand("rapidocr", "260.00", "260.00", _CHARGE_BBOX),
                _cand("anthropic_claude_crop", "260.00", "260.00", _CHARGE_BBOX),
            ],
        },
    ]
    selected = apply_line_charge_selector(lines)
    assert all(
        ln["line_charge_selection"]["disposition"] == "SELECTED_LOCAL_CHARGE"
        for ln in selected
    )
    decision = evaluate_financial_geometry_arithmetic(
        box28_amount="1160.40",
        service_lines=selected,
    )
    assert decision.confirmed
    assert decision.line_sum == "1160.00"
    assert decision.amount == "1160.40"


def test_digit_drop_vision_does_not_veto_fuller_local():
    """Blind-50 1851 must survive a Claude 185 crop (one dropped digit)."""
    line = {
        "charges": "185.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "185.00", "185.00", _CHARGE_BBOX),
            _cand("rapidocr", "1851.00", "1851.00", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "1851.00"
    assert result.reason == "DIGIT_DROP_FULLER_LOCAL"


def test_two_locals_on_digit_drop_keep_the_shorter_local():
    """A local ``185`` makes ``1851`` units-concat, not a vision digit-drop."""
    line = {
        "charges": "185.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "185.00", "185.00", _CHARGE_BBOX),
            _cand("rapidocr", "1851.00", "1851.00", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "185.00"
    assert result.reason != "DIGIT_DROP_FULLER_LOCAL"


def test_cents_twin_dual_local_prefers_observed_decimal():
    """457.60 and 457.00 are one amount, not a line conflict."""
    line = {
        "charges": "4571.60",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "457.60", "457.60", _CHARGE_BBOX),
            _cand("rapidocr", "457.60", "457.60", _CHARGE_BBOX),
            _cand("paddleocr", "457.00", "457.00", _CHARGE_BBOX),
            _cand("rapidocr", "457.00", "457.00", _CHARGE_BBOX),
            _cand("rapidocr", "4571.60", "4571.60", _CHARGE_BBOX),
        ],
    }
    line["candidates"][-1]["preprocessing_variant"] = "GEOMETRY_CENTS"
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "457.60"
    out = apply_line_charge_selector([line])
    assert out[0]["charges"] == "457.60"


def test_ambiguous_clears_scale_shifted_geometry_shell():
    """A lone 4571.60 geometry read must not survive beside dual-local 457.60."""
    line = {
        "charges": "4571.60",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "457.60", "457.60", _CHARGE_BBOX),
            _cand("rapidocr", "457.60", "457.60", _CHARGE_BBOX),
            _cand("paddleocr", "100.00", "100.00", _CHARGE_BBOX),
            _cand("rapidocr", "100.00", "100.00", _CHARGE_BBOX),
            _cand("rapidocr", "4571.60", "4571.60", _CHARGE_BBOX),
        ],
    }
    line["candidates"][-1]["preprocessing_variant"] = "GEOMETRY_CENTS"
    out = apply_line_charge_selector([line])
    assert out[0]["line_charge_selection"]["disposition"] == "AMBIGUOUS_LINE_CHARGE"
    assert out[0]["charges"] is None


def test_trailing_third_decimal_does_not_drop_a_whole_dollar_line():
    """Rapid ``200.100`` is a ruling zero, not a printed ``200.10``."""
    line = {
        "charges": "200.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "200.00", "200..00", _CHARGE_BBOX),
            _cand("rapidocr", "200.10", "200.100", _CHARGE_BBOX),
            _cand("paddleocr", "2000.00", "2000", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "200.00"
    assert result.reason == "SAME_STEM_CENTS_RULING_JITTER"
    out = apply_line_charge_selector([line])
    assert out[0]["charges"] == "200.00"


def test_clean_dime_read_is_not_stripped_to_whole_dollars():
    line = {
        "charges": "200.10",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "200.00", "200.00", _CHARGE_BBOX),
            _cand("rapidocr", "200.10", "200.10", _CHARGE_BBOX),
        ],
    }
    result = select_line_charge(line)
    assert result.amount != "200.00" or result.disposition != "SELECTED_LOCAL_CHARGE"
    assert result.reason != "SAME_STEM_CENTS_RULING_JITTER"


def test_di_corroborated_ruling_split_beats_geometry_scale():
    """``25/43`` and DI ``25 |43`` are $25.43. Geometry ``25143`` is the ruling tick."""
    line = {
        "charges": "251.43",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "43.00", "25/43", _CHARGE_BBOX),
            _cand("rapidocr", "1.25", "1\n25", _CHARGE_BBOX),
            _cand("azure_document_intelligence_read", "43.00", "25 |43", _CHARGE_BBOX),
            _cand("rapidocr", "251.43", "25143", _CHARGE_BBOX),
        ],
    }
    line["candidates"][-1]["preprocessing_variant"] = "GEOMETRY_CENTS"
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "25.43"
    assert result.reason == "RULING_SPLIT_DI_CORROBORATED"
    out = apply_line_charge_selector([line])
    assert out[0]["charges"] == "25.43"


def test_ruling_split_without_di_stays_unresolved():
    line = {
        "charges": "251.43",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "43.00", "25/43", _CHARGE_BBOX),
            _cand("rapidocr", "251.43", "25143", _CHARGE_BBOX),
        ],
    }
    line["candidates"][-1]["preprocessing_variant"] = "GEOMETRY_CENTS"
    result = select_line_charge(line)
    assert result.reason != "RULING_SPLIT_DI_CORROBORATED"
    assert result.amount != "25.43"


def test_geometry_scale_shift_does_not_outrank_dual_local_dollars():
    """Raw ``157107`` → ``1571.07`` is a ruling tick, not a fuller charge."""
    dollars_bbox = (1050.0, 1458.0, 1165.0, 1513.0)
    line = {
        "charges": "1571.07",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "157.00", "157", dollars_bbox),
            _cand("rapidocr", "157.00", "157", dollars_bbox),
            _cand("rapidocr", "1571.07", "157107", _CHARGE_BBOX),
        ],
    }
    line["candidates"][-1]["preprocessing_variant"] = "GEOMETRY_CENTS"
    result = select_line_charge(line)
    assert result.disposition == "SELECTED_LOCAL_CHARGE"
    assert result.amount == "157.00"
    assert result.reason == "DUAL_LOCAL_CHARGE_COLUMN"
    assert ("1571.07", "GEOMETRY_SCALE_SHIFT") in result.rejected
    out = apply_line_charge_selector([line])
    assert out[0]["charges"] == "157.00"


def test_geometry_ruling_tick_is_not_digit_drop_fuller():
    """``200100`` → ``2001.00`` must not beat a local ``200.00`` dollars read."""
    line = {
        "charges": "2001.00",
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("paddleocr", "200.00", "200.00", _CHARGE_BBOX),
            _cand("anthropic_claude_crop", "200.00", "200.00", _CHARGE_BBOX),
            _cand("rapidocr", "2001.00", "200100", _CHARGE_BBOX),
        ],
    }
    line["candidates"][-1]["preprocessing_variant"] = "GEOMETRY_CENTS"
    result = select_line_charge(line)
    assert result.reason != "DIGIT_DROP_FULLER_LOCAL"
    assert result.amount != "2001.00"
    out = apply_line_charge_selector([line])
    assert out[0]["charges"] != "2001.00"


def test_geometry_digit_drop_survives_claude_short_crop():
    """Single-line geometry×Claude stays closed; multi-line HJDF.022 promotes."""
    line_a = {
        "charges": None,
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "185.00", "185.00", _CHARGE_BBOX),
            _cand("paddleocr", "18500.00", "18500", _CHARGE_BBOX),
            _cand("rapidocr", "1851.00", "185100", _CHARGE_BBOX),
        ],
    }
    line_a["candidates"][-1]["preprocessing_variant"] = "GEOMETRY_CENTS"
    # Per-line: do not promote geometry 1851 over Claude-only 185 — that same
    # pattern is the DJKN.001 ruling tick (2001 vs 200) on single-line claims.
    single = select_line_charge(line_a)
    assert single.disposition != "SELECTED_LOCAL_CHARGE" or single.amount != "1851.00"
    assert single.reason != "DIGIT_DROP_FULLER_LOCAL"
    closed = apply_line_charge_selector([line_a])
    assert closed[0].get("charges") != "1851.00"

    line_b = {
        "charges": None,
        "canonical_region": list(_CHARGE_BBOX),
        "candidates": [
            _cand("anthropic_claude_crop", "155.00", "155.00", _CHARGE_BBOX),
            _cand("paddleocr", "15500.00", "15500", _CHARGE_BBOX),
            _cand("rapidocr", "1551.00", "155100", _CHARGE_BBOX),
        ],
    }
    line_b["candidates"][-1]["preprocessing_variant"] = "GEOMETRY_CENTS"
    out = apply_line_charge_selector([line_a, line_b])
    assert out[0]["charges"] == "1851.00"
    assert out[1]["charges"] == "1551.00"
    assert out[0]["line_charge_selection"]["reason"] == "MULTI_LINE_GEOMETRY_DIGIT_DROP"
    assert out[1]["line_charge_selection"]["reason"] == "MULTI_LINE_GEOMETRY_DIGIT_DROP"




def test_preserve_frozen_digit_drop_fuller_when_live_selector_ambiguous():
    """DJKN.004: Box 28 under-read restore keeps extract DIGIT_DROP_FULLER_LOCAL."""
    from packages.claim_evidence.line_charge_selector import apply_line_charge_selector
    from packages.claim_evidence.line_sum_authority import is_currency_digit_drop_twin

    lines = [
        {
            "charges": "2001.00",
            "canonical_region": list(_CHARGE_BBOX),
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "2001.00",
                "reason": "DIGIT_DROP_FULLER_LOCAL",
                "supporting_engines": ["rapidocr"],
            },
            "candidates": [
                _cand("anthropic_claude_crop", "200.00", "200.00", _CHARGE_BBOX),
                _cand("rapidocr", "2001.00", "200100", _CHARGE_BBOX),
            ],
            "attempts": [
                {
                    "engine": "rapidocr",
                    "reason": "GEOMETRY_CENTS",
                    "observation": {"shaped": "2001.00", "raw_digit_sequence": "200100"},
                }
            ],
        }
    ]
    # Live selector alone may drop the fuller; under-read restore is gated on Box 28.
    out = apply_line_charge_selector(lines)
    assert out[0]["line_charge_selection"]["disposition"] != "SELECTED_LOCAL_CHARGE" or (
        out[0]["charges"] in {"200.00", "2001.00"}
    )
    assert is_currency_digit_drop_twin("200.00", "2001.00")
