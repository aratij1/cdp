"""Box 67 provenance and field-boundary regression checks."""

import hashlib
from dataclasses import replace

import pytest

from workers.field_candidates.box67_recovery import AUTHORITY, SourceBox67Anchor, generate_box67
from workers.page_detection.text_extraction import TextLine

IMAGE = b"synthetic source image identity"
HASH = hashlib.sha256(IMAGE).hexdigest()
ANCHOR = SourceBox67Anchor(HASH, (75, 1680, 245, 1740), AUTHORITY, "Source grid inspected")


def token(text, x0=100, y0=1695, x1=180, y1=1728):
    return TextLine(text, x0, y0, x1, y1, 0.9)


def generate(tokens, anchor=ANCHOR, image=IMAGE, token_hash=HASH):
    return generate_box67(tokens, image_bytes=image, token_image_sha256=token_hash, anchor=anchor)


def test_principal_only_never_admitting_or_adjacent_diagnosis():
    result = generate(
        [token("F33.3"), token("F25.9", y0=1760, y1=1790), token("F20.9", x0=260, x1=320)]
    )
    assert [c.value for c in result] == ["F33.3"]
    assert result[0].review_only
    assert result[0].token_indices == (0,)
    assert result[0].source_image_sha256 == HASH


@pytest.mark.parametrize("raw", ["E20.9", "F25.S", "F33.3", "F25.9", "F33.9"])
def test_preserves_ocr_without_reference_repair(raw):
    assert generate([token(raw)])[0].value == raw


@pytest.mark.parametrize(
    "anchor",
    [
        None,
        replace(ANCHOR, authority="AUTO"),
        replace(ANCHOR, evidence=""),
        replace(ANCHOR, bbox=(245, 1680, 75, 1740)),
    ],
)
def test_requires_reviewed_valid_source_anchor(anchor):
    assert generate([token("F33.3")], anchor=anchor) == []


def test_rejects_other_image_or_tokens_from_other_image():
    assert generate([token("F33.3")], image=b"other page") == []
    assert generate([token("F33.3")], token_hash="0" * 64) == []


def test_does_not_borrow_admitting_when_principal_empty():
    assert generate([token("F33.3", y0=1760, y1=1790)]) == []


@pytest.mark.parametrize("raw", ["66 DX", "67", "69 AD", "", "F25.9 F33.3"])
def test_labels_and_merged_cells_are_not_codes(raw):
    assert generate([token(raw)]) == []


def test_crossing_region_boundary_is_rejected():
    assert generate([token("F33.3", y0=1730, y1=1760)]) == []
