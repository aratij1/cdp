"""STAGE_FAILURE guard: cash-ruling helpers must tolerate unparseable candidates."""

from __future__ import annotations

from packages.candidate_reconciliation.reconciler import (
    _charge_cash_ruling_confirms,
    _charge_di_printed_decimal_confirms,
)


def test_cash_ruling_skips_none_candidate_values():
    assert (
        _charge_cash_ruling_confirms(
            "157.07",
            [{"raw_value": "$ 157 :07", "value": None}],
        )
        is True
    )
    assert (
        _charge_cash_ruling_confirms(
            "25.43",
            [{"raw_value": "25|43", "value": "not-a-currency"}],
        )
        is True
    )


def test_di_printed_decimal_skips_none_candidate_values():
    assert (
        _charge_di_printed_decimal_confirms(
            "563.10",
            [
                {
                    "engine": "azure_document_intelligence_read",
                    "raw_value": "$ 563.10 L :",
                    "value": None,
                }
            ],
        )
        is True
    )
    # Unparseable cand_val must not raise AttributeError on format_currency(None).
    assert (
        _charge_di_printed_decimal_confirms(
            "10.00",
            [
                {
                    "engine": "azure_document_intelligence_read",
                    "raw_value": "$ x.yy",
                    "value": "junk",
                }
            ],
        )
        is False
    )
