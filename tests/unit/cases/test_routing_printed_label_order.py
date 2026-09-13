"""Synthetic printed labels: preserve line geometry without weakening identity gates."""
from packages.document_routing.router import (
    _ordered_phrase_candidates,
    _phrase_match,
    _routing_tokens,
)
from workers.page_detection.text_extraction import TextLine


def test_label_crossing_fixed_y_bucket_keeps_left_to_right_order():
    # One line straddles the former round(y / 18) bucket boundary.
    lines = [TextLine('FEDERAL', 10, 28, 90, 44, .99),
             TextLine('TAX', 100, 26, 135, 42, .99),
             TextLine('I.D.', 145, 27, 180, 43, .99)]
    candidates = _ordered_phrase_candidates(lines, 'federal tax id')
    assert any(_phrase_match('federal tax id', c.text)[0] for c in candidates)


def test_reading_order_does_not_join_separate_visual_rows():
    lines = [TextLine('FEDERAL', 10, 10, 90, 25, .99),
             TextLine('TAX I.D.', 100, 100, 180, 115, .99)]
    assert not any(_phrase_match('federal tax id', c.text)[0]
                   for c in _ordered_phrase_candidates(lines, 'federal tax id'))


def test_reading_order_does_not_join_distant_columns():
    lines = [TextLine('FEDERAL', 10, 10, 90, 25, .99),
             TextLine('TAX I.D.', 900, 10, 980, 25, .99)]
    assert not any(_phrase_match('federal tax id', c.text)[0]
                   for c in _ordered_phrase_candidates(lines, 'federal tax id'))


def test_id_glyph_correction_requires_complete_printed_label():
    assert _routing_tokens("INSURED'S 1.0. NUMBER") == ['insured', 'id', 'number']
    assert _routing_tokens('version 1.0 number') == ['version', '1', '0', 'number']
    assert _routing_tokens('insured 1.0') == ['insured', '1', '0']
