"""DOB cloud residuals must use the full Box 3 cell, not a razor year strip."""

from packages.extraction_recovery.dob_azure_di_residual import dob_residual_bbox


def test_dob_residual_bbox_prefers_canonical_when_ocr_strip_too_thin():
    """M0471JEH.036: year-wide ocr_region ~18px tall → Claude abstain."""
    row = {
        "ocr_region": [761, 438, 870, 456],
        "canonical_region": [672, 424, 871, 457],
    }
    assert dob_residual_bbox(row) == (672, 424, 871, 457)


def test_dob_residual_bbox_keeps_tall_ocr_region():
    row = {
        "ocr_region": [672, 424, 871, 457],
        "canonical_region": [600, 400, 900, 500],
    }
    assert dob_residual_bbox(row) == (672, 424, 871, 457)
