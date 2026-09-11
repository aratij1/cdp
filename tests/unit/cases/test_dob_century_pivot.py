"""Unit tests for healthcare DOB century pivot normalization and boundaries."""

from __future__ import annotations

from packages.field_normalization import DEFAULT_PIVOT_YEAR, normalize_date


def test_dob_century_pivot_default_invocation_deterministic() -> None:
    # Test default invocation without passing current_year
    val_26, ok_26 = normalize_date("01/01/26")
    assert ok_26 is True
    assert val_26 == "2026-01-01"

    val_27, ok_27 = normalize_date("01/01/27")
    assert ok_27 is True
    assert val_27 == "1927-01-01"

    val_45, ok_45 = normalize_date("03/15/45")
    assert ok_45 is True
    assert val_45 == "1945-03-15"

    val_99, ok_99 = normalize_date("12/31/99")
    assert ok_99 is True
    assert val_99 == "1999-12-31"

    val_00, ok_00 = normalize_date("12/31/00")
    assert ok_00 is True
    assert val_00 == "2000-12-31"


def test_dob_century_pivot_current_year_boundary() -> None:
    # Boundary: yy == 26 with current_year=2026 -> maps to 2026
    val, ok = normalize_date("01/01/26", current_year=2026)
    assert ok is True
    assert val == "2026-01-01"


def test_dob_century_pivot_next_year_boundary() -> None:
    # Boundary: yy == 27 with current_year=2026 -> future year in 2000s, pivots to 1927
    val, ok = normalize_date("01/01/27", current_year=2026)
    assert ok is True
    assert val == "1927-01-01"


def test_dob_century_pivot_lower_bound_2000s() -> None:
    # Boundary: yy == 00 with current_year=2026 -> maps to 2000
    val, ok = normalize_date("12/31/00", current_year=2026)
    assert ok is True
    assert val == "2000-12-31"


def test_dob_century_pivot_upper_bound_1900s() -> None:
    # Boundary: yy == 99 with current_year=2026 -> maps to 1999
    val, ok = normalize_date("12/31/99", current_year=2026)
    assert ok is True
    assert val == "1999-12-31"


def test_dob_century_pivot_historical_adult_dob() -> None:
    # Sample DOB e.g. 45 -> maps to 1945
    val, ok = normalize_date("03/15/45", current_year=2026)
    assert ok is True
    assert val == "1945-03-15"


def test_dob_four_digit_year_preservation() -> None:
    # 4-digit years remain untouched
    val, ok = normalize_date("05/10/1985")
    assert ok is True
    assert val == "1985-05-10"

    val_2024, ok_2024 = normalize_date("01/15/2024")
    assert ok_2024 is True
    assert val_2024 == "2024-01-15"


def test_dob_leap_year_handling() -> None:
    val, ok = normalize_date("02/29/04")
    assert ok is True
    assert val == "2004-02-29"


def test_dob_invalid_date() -> None:
    val, ok = normalize_date("invalid_date")
    assert ok is False
    assert val is None
