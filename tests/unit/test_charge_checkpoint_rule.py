"""Semantic guards for review-only claim-total recovery."""

import inspect
from dataclasses import replace

import pytest

from evaluation.charge_checkpoint_rule import ChargeCell, discover, numeric_text, ocr_allowed
from workers.page_detection.text_extraction import TextLine

SHA = "a" * 64
CELL = ChargeCell("CMS1500", SHA, (0.60, 0.80, 0.74, 0.85), 0.70, True, True)


def token(text, x0=650, y0=810, x1=730, y1=835):
    return TextLine(text, x0, y0, x1, y1, 0.95)


def run(tokens, pilot="B", cell=CELL, form="CMS1500", sha=SHA):
    return discover(
        tokens, form_type=form, source_sha256=sha, width=1000, height=1000, cell=cell, pilot=pilot
    )


@pytest.mark.parametrize(
    "raw,value",
    [
        ("12500", "125.00"),
        ("  $ 1,234.56 ", "1234.56"),
        ("22500s", "225.00"),
        ("180:00", "180.00"),
        ("582 00", "582.00"),
    ],
)
def test_observed_digits_and_punctuation(raw, value):
    result = run([token(raw)], "A" if "." in raw else "B")
    assert result[0]["value"] == value
    assert result[0]["raw_tokens"][0]["text"] == raw
    assert result[0]["review_only"] and result[0]["authority"] == "ENGINEERING_ONLY"


@pytest.mark.parametrize(
    "raw", ["90d00", "582CO", "1S000", "1,23.45", "12.3", "-12500", "(12500)", "12500 000"]
)
def test_no_character_repair_or_missing_digits(raw):
    assert run([token(raw)]) == []


def test_cents_column_proof_required():
    assert run([token("12500")], cell=replace(CELL, cents_column_verified=False)) == []
    assert run([token("12500", x0=610, x1=660)]) == []


def test_split_dollars_cents_and_missing_zero():
    assert run([token("6", x0=670, x1=699), token("00", x0=701, x1=730)])[0]["value"] == "6.00"
    assert run([token("654", x0=640, x1=699), token("0", x0=701, x1=730)]) == []
    assert run([token("6", x0=670, x1=699), token("00", x0=701, x1=730, y0=837, y1=849)]) == []


def test_line_charges_paid_and_noncovered_excluded():
    rows = [
        token("999.00", y0=650, y1=675),
        token("25.00", x0=750, x1=800),
        token("1000", x0=800, x1=900),
    ]
    assert run(rows, "A") == []
    assert run(rows) == []
    assert run([token("12500")], cell=replace(CELL, role="SERVICE_LINE")) == []


def test_ub_has_separate_topology_and_does_not_sum_lines():
    cell = replace(
        CELL, form_type="UB", normalized_region=(0.68, 0.57, 0.84, 0.60), cents_separator=0.80
    )
    rows = [
        token("500", x0=780, x1=825, y0=575, y1=590),
        token("99900", x0=780, x1=825, y0=300, y1=320),
        token("999.00", x0=860, x1=940, y0=575, y1=590),
    ]
    assert run(rows, cell=cell, form="UB")[0]["value"] == "5.00"
    assert run(rows, cell=cell, form="CMS1500") == []


@pytest.mark.parametrize("form", ["OTHER", "UNKNOWN", "UB04", "", "CMS"])
def test_strict_identity(form):
    assert run([token("12500")], form=form) == []


def test_hash_and_review_required():
    assert run([token("12500")], sha="b" * 64) == []
    assert run([token("12500")], cell=replace(CELL, source_reviewed=False)) == []


@pytest.mark.parametrize(
    "visible,present,allowed",
    [(True, False, True), (True, True, False), (False, False, False), (False, True, False)],
)
def test_ocr_gate(visible, present, allowed):
    assert (
        ocr_allowed(
            CELL,
            form_type="CMS1500",
            source_sha256=SHA,
            value_visible=visible,
            primary_value_present=present,
        )
        == allowed
    )
    assert not ocr_allowed(
        CELL,
        form_type="UNKNOWN",
        source_sha256=SHA,
        value_visible=visible,
        primary_value_present=present,
    )


def test_no_truth_input_and_conflicts_are_retained():
    assert not (
        {"reference", "expected", "claim_alias", "expected_length"}
        & set(inspect.signature(discover).parameters)
    )
    rows = run([token("100.00"), token("200.00")], "A")
    assert {r["value"] for r in rows} == {"100.00", "200.00"}
    assert all(r["review_only"] for r in rows)


def test_boundary_currency_and_multi_cell_token_rejection():
    assert run([token("22500s", x0=680, x1=755)])[0]["value"] == "225.00"
    assert run([token("22500 000", x0=680, x1=820)]) == []
    assert numeric_text("TOTAL 22500") is None
