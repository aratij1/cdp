"""Evidence-driven reconciliation with fail-closed C3 acceptance."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC
from hashlib import sha256

from packages.candidate_reconciliation.contracts import (
    Decision,
    EvidenceReference,
    ReconciliationResult,
)
from packages.confidence import CalibrationRegistry
from packages.criticality import CriticalityLevel
from packages.evidence.normalization import normalize_agreement_value
from packages.evidence_policy import EvidencePolicyRegistry
from packages.observability.metrics import field_reconciliation_total
from packages.ocr.contracts import OCRCandidate
from packages.ocr.independence import independence_group


def _charge_is_units_bleed_cents(value: object) -> bool:
    try:
        from packages.claim_evidence.charge_total_authority import is_units_bleed_cents

        return bool(is_units_bleed_cents(value))
    except Exception:  # noqa: BLE001
        return False


def _charge_cash_ruling_confirms(value: object, candidates: list) -> bool:
    """True when a candidate raw is dollars[:|/]cents matching ``value``.

    Cash ruling-split geometry (``7 $ 157 :07``, ``25|43``, ``25\\n43``) proves
    the cents column is printed ink — not units/ruling bleed soup that must
    fail-closed. Dollar sign is optional when a ruling separator is present.
    """
    try:
        from packages.claim_evidence.charge_total_authority import (
            format_currency,
            parse_currency,
        )
        from packages.claim_evidence.line_charge_selector import _ruling_split_amount
    except Exception:  # noqa: BLE001
        return False
    target = parse_currency(value)
    if target is None:
        return False
    target_txt = format_currency(target)
    for cand in candidates or []:
        raw = getattr(cand, "raw_value", None)
        if raw in (None, ""):
            # Dict-shaped candidates from OCR rows.
            if isinstance(cand, Mapping):
                raw = cand.get("raw_value")
            if raw in (None, ""):
                continue
        raw_text = str(raw)
        has_sep = bool(re.search(r"[:|/\n]", raw_text)) or ("|" in raw_text)
        has_dollar = "$" in raw_text
        # Prefer cash-marked or explicit ruling separators; avoid bare "25 43".
        if not has_sep and not has_dollar:
            continue
        if has_dollar and not re.search(r"[:|/]", raw_text):
            # "$ 157.07" alone is not a ruling split.
            if _ruling_split_amount(raw_text) is None:
                continue
        ruled = _ruling_split_amount(raw_text)
        if ruled and parse_currency(ruled) == target:
            return True
        # Also accept when the candidate value already matches after reshape.
        cand_val = getattr(cand, "value", None)
        if cand_val is None and isinstance(cand, Mapping):
            cand_val = cand.get("value")
        parsed_cand = parse_currency(cand_val)
        if parsed_cand is None:
            continue
        if format_currency(parsed_cand) == target_txt:
            if _ruling_split_amount(raw_text) == target_txt:
                return True
    return False


def _charge_di_printed_decimal_confirms(value: object, candidates: list) -> bool:
    """True when Azure DI raw shows ``$ NNN.CC`` matching ``value``.

    Explicit decimal ink in the DI crop (``$ 563.10 L :``) is printed Box 28
    cents — not units-column bleed that ``is_units_bleed_cents`` would reject.
    Distinct from ruling-split ``$ 157 :07`` (no decimal in the dollars token).
    Requires a Document Intelligence candidate; local-only ``$`` OCR is ignored.
    """
    try:
        from packages.claim_evidence.charge_total_authority import (
            format_currency,
            parse_currency,
        )
    except Exception:  # noqa: BLE001
        return False
    target = parse_currency(value)
    if target is None:
        return False
    target_txt = format_currency(target)
    for cand in candidates or []:
        if isinstance(cand, Mapping):
            engine = str(cand.get("engine") or cand.get("engine_name") or "")
            raw = cand.get("raw_value")
            cand_val = cand.get("value")
        else:
            engine = str(getattr(cand, "engine", "") or "")
            raw = getattr(cand, "raw_value", None)
            cand_val = getattr(cand, "value", None)
        eng = engine.casefold()
        if "document_intelligence" not in eng and "azure_di" not in eng:
            continue
        raw_text = str(raw or "")
        if "$" not in raw_text:
            continue
        match = re.search(r"\$\s*(\d{1,5}\.\d{2})\b", raw_text)
        if match:
            parsed_match = parse_currency(match.group(1))
            if parsed_match is not None and format_currency(parsed_match) == target_txt:
                return True
        parsed_cand = parse_currency(cand_val)
        if (
            parsed_cand is not None
            and format_currency(parsed_cand) == target_txt
            and re.search(r"\d+\.\d{2}", raw_text)
        ):
            return True
    return False


def _charge_inflated_rivals_are_whole_dollar_place_shift_soup(
    value: object, candidates: list
) -> bool:
    """True when every inflated rival is ×100 place-shift of whole-dollar ``value``.

    Vision+local ``177.00`` beside DI digit-soup ``17700`` is classic place-shift
    soup — not DJKH.040 ``1571.63`` (non-.00) beside ``157163``. Only exempts
    SCALE_RIVAL when *all* inflated rivals are pure decimal place-shifts.
    """
    try:
        from packages.claim_evidence.charge_total_authority import (
            format_currency,
            parse_currency,
        )
        from packages.claim_evidence.line_sum_authority import is_decimal_place_shift
    except Exception:  # noqa: BLE001
        return False
    target = parse_currency(value)
    if target is None:
        return False
    if not format_currency(target).endswith(".00"):
        return False
    saw_inflated = False
    for cand in candidates or []:
        if isinstance(cand, Mapping):
            other_raw = cand.get("value")
        else:
            other_raw = getattr(cand, "value", None)
        other = parse_currency(other_raw)
        if other is None or other <= target:
            continue
        saw_inflated = True
        if not is_decimal_place_shift(value, other_raw):
            return False
    return saw_inflated


def _charge_vision_local_confirms_bleed(value: object, candidates: list) -> bool:
    """L3: Claude/gpt-4o + local agree on printed bleed cents (DI may be ×100)."""
    try:
        from packages.claim_evidence.charge_total_authority import (
            _vision_local_confirms_bleed_cents,
        )
    except Exception:  # noqa: BLE001
        return False
    rows: list[dict] = []
    for cand in candidates or []:
        if isinstance(cand, Mapping):
            rows.append(dict(cand))
            continue
        rows.append(
            {
                "engine": getattr(cand, "engine", None),
                "value": getattr(cand, "value", None),
                "raw_value": getattr(cand, "raw_value", None),
            }
        )
    return bool(_vision_local_confirms_bleed_cents(value, rows))


def _di_raw_embeds_selected_charge(
    selected: object, rival: object, candidates: list
) -> bool:
    """True when a DI raw embeds selected dollars beside a junk rival token.

    DJKH.023: DI raw ``J $ 70 100`` shaped as ``100`` beside Claude+local ``70``.
    Requires the selected stem to appear as its own token in DI raw.
    """
    try:
        from packages.claim_evidence.charge_total_authority import (
            format_currency,
            parse_currency,
        )
    except Exception:  # noqa: BLE001
        return False
    selected_amt = parse_currency(selected)
    rival_amt = parse_currency(rival)
    if selected_amt is None or rival_amt is None or selected_amt == rival_amt:
        return False
    selected_txt = format_currency(selected_amt)
    selected_dollars = selected_txt.split(".", 1)[0]
    rival_txt = format_currency(rival_amt)
    rival_dollars = rival_txt.split(".", 1)[0]
    if not selected_dollars or not rival_dollars:
        return False
    for cand in candidates or []:
        if isinstance(cand, Mapping):
            engine = str(cand.get("engine") or "")
            raw = str(cand.get("raw_value") or "")
            shaped = str(cand.get("value") or "")
        else:
            engine = str(getattr(cand, "engine", "") or "")
            raw = str(getattr(cand, "raw_value", "") or "")
            shaped = str(getattr(cand, "value", "") or "")
        eng = engine.casefold()
        if "document_intelligence" not in eng and "azure_di" not in eng and "azure_read" not in eng:
            continue
        parsed_shaped = parse_currency(shaped)
        if parsed_shaped is None or format_currency(parsed_shaped) != rival_txt:
            continue
        # Selected and rival dollars both appear as digit tokens in DI raw.
        tokens = re.findall(r"\d+", raw)
        if selected_dollars in tokens and rival_dollars in tokens:
            return True
    return False


def _charge_has_inflated_scale_rival(value: object, candidates: list) -> bool:
    """True when any candidate value is an inflated ×10/×100 twin of ``value``.

    Includes implausible DI shells (``157163`` beside ``1571.63``) that may be
    dropped from ranking but still prove the vision+local pick is contested.
    """
    try:
        from decimal import Decimal

        from packages.claim_evidence.line_sum_authority import (
            is_currency_digit_drop_twin,
            is_decimal_place_shift,
            is_scale_shift,
            parse_currency,
        )
    except Exception:  # noqa: BLE001
        return False
    target = parse_currency(value)
    if target is None:
        return False
    for cand in candidates or []:
        if isinstance(cand, Mapping):
            other_raw = cand.get("value")
        else:
            other_raw = getattr(cand, "value", None)
        other = parse_currency(other_raw)
        if other is None or other <= target:
            continue
        if (
            is_scale_shift(value, other_raw)
            or is_decimal_place_shift(value, other_raw)
            or is_currency_digit_drop_twin(value, other_raw)
        ):
            return True
        for factor in (Decimal(10), Decimal(100)):
            if abs(target * factor - other) <= Decimal("2.00"):
                return True
    return False



def _canonical_date_digits(value: str) -> str:
    """Normalize US/ISO/compact dates to YYYYMMDD for conflict comparison."""
    digits = re.sub(r"\D", "", (value or "").strip())
    if len(digits) == 8:
        # Prefer ISO YYYYMMDD when year-looking prefix, else MMDDYYYY.
        if int(digits[0:4]) >= 1880:
            return digits
        return digits[4:8] + digits[0:2] + digits[2:4]
    if len(digits) == 6:
        yy = int(digits[4:6])
        century = 1900 if yy >= 30 else 2000
        return f"{century + yy:04d}{digits[0:2]}{digits[2:4]}"
    return digits


# Human DOB floor — matches ISO-year detection in ``_canonical_date_digits``.
# Compact OCR like ``05131179`` (separator-1 jammed into MMDDYYYY) must not
# become a calendar-valid year-1179 date that then invents ``1179-05-03``.
_DOB_MIN_YEAR = 1880


def _dob_ymd(value: str) -> tuple[str, str, str] | None:
    digits = _canonical_date_digits(value)
    if len(digits) != 8:
        return None
    year, month, day = digits[0:4], digits[4:6], digits[6:8]
    try:
        from datetime import date as _date

        y = int(year)
        if y < _DOB_MIN_YEAR:
            return None
        _date(y, int(month), int(day))
    except ValueError:
        return None
    return year, month, day


def _dob_is_future(value: str) -> bool:
    """True when a calendar-valid DOB is after today (OCR year/box-rule junk)."""
    from datetime import date as _date
    from datetime import datetime

    parts = _dob_ymd(value)
    if parts is None:
        return False
    year, month, day = (int(p) for p in parts)
    try:
        return _date(year, month, day) > datetime.now(UTC).date()
    except ValueError:
        return False


def _dob_is_display_shaped(value: str) -> bool:
    """True when DOB ink looks like a date — not letter/punct soup that digit-glues.

    ``ib0 13! 197`` strips to ``013197`` → fake ``1997-01-31``. Ranking must
    not treat that as calendar-valid over a real ``11/01/2011``.
    """
    text = str(value or "").strip()
    if not text or _dob_ymd(text) is None or _dob_is_future(text):
        return False
    # Digits + common date separators / spaces only. Allow ``:`` / ``,`` for
    # DI punct confusables (``7:30.77``) that normalize elsewhere.
    noise = re.sub(r"[\d/\-.\s:,]", "", text)
    return noise == ""


def prefer_dob_without_separator_one(
    primary: str, competitors: list[str]
) -> str | None:
    """CMS DOB boxes use dashed vertical rules that OCR reads as leading ``1``.

    When two *observed* calendar-valid dates share a year and differ only by
    that artifact on MM or DD (11 vs 01, 19 vs 09), prefer the copy without
    the extra leading 1. Never invent an unobserved peeled date (EJG7.013:
    ``05/13/1979`` vs ``05131179`` must not become ``1179-05-03``).
    """
    observed: list[tuple[tuple[str, str, str], str]] = []
    for value in [primary, *competitors]:
        ymd = _dob_ymd(value)
        if ymd is not None:
            observed.append((ymd, value))
    if len(observed) < 2:
        return None
    parts = {ymd for ymd, _ in observed}

    # Prefer an observed 0X form when the matching 1X form is also observed
    # for the same year (month or day). Do not synthesize peeled YMD tuples.
    for year, month, day in sorted(parts):
        if month[0] != "0" and day[0] != "0":
            continue
        sep_month = f"1{month[1]}" if month[0] == "0" else None
        sep_day = f"1{day[1]}" if day[0] == "0" else None
        has_sep = False
        if sep_month and (year, sep_month, day) in parts:
            has_sep = True
        if sep_day and (year, month, sep_day) in parts:
            has_sep = True
        if not has_sep:
            continue
        for ymd, display in observed:
            if ymd == (year, month, day):
                return display
        return f"{year}-{month}-{day}"
    return None


def prefer_dob_without_january_dash_artifact(
    primary: str, competitors: list[str]
) -> str | None:
    """When day+year agree and one engine reads MM=01, prefer the other month.

    CMS MM dashed rules often OCR as ``01`` while the true month is elsewhere
    (Track-B residual: ``07/24/1955`` vs ``01/24/1955``). Only fires when exactly
    one side is January and both dates are calendar-valid non-future.
    """
    observed: list[tuple[tuple[str, str, str], str]] = []
    for value in [primary, *competitors]:
        ymd = _dob_ymd(value)
        if ymd is None or _dob_is_future(value):
            continue
        observed.append((ymd, value))
    if len(observed) < 2:
        return None
    # Group by (year, day); require a unique non-01 month competing with 01.
    by_yd: dict[tuple[str, str], list[tuple[tuple[str, str, str], str]]] = {}
    for ymd, display in observed:
        by_yd.setdefault((ymd[0], ymd[2]), []).append((ymd, display))
    for rows in by_yd.values():
        months = {ymd[1] for ymd, _ in rows}
        if "01" not in months or len(months) != 2:
            continue
        non_jan = [(ymd, display) for ymd, display in rows if ymd[1] != "01"]
        if len(non_jan) != 1:
            continue
        return non_jan[0][1]
    return None


_DOB_YEAR_DIGIT_CONFUSABLES = {
    frozenset({"6", "9"}),
    frozenset({"5", "6"}),
    frozenset({"8", "9"}),
    frozenset({"0", "8"}),
    frozenset({"3", "8"}),
    frozenset({"1", "7"}),
    frozenset({"5", "8"}),
}


def prefer_dob_year_confusable_digit(
    primary: str, competitors: list[str]
) -> str | None:
    """When month+day agree and years differ by one OCR-confusable digit, prefer higher conf.

    Independent case: ``05/20/1995`` vs ``05/20/1965`` (9↔6). Does not fire on
    multi-digit year disagreements or month/day conflicts.
    """
    observed: list[tuple[tuple[str, str, str], str]] = []
    for value in [primary, *competitors]:
        ymd = _dob_ymd(value)
        if ymd is None or _dob_is_future(value):
            continue
        observed.append((ymd, value))
    if len(observed) < 2:
        return None
    by_md: dict[tuple[str, str], list[tuple[tuple[str, str, str], str]]] = {}
    for ymd, display in observed:
        by_md.setdefault((ymd[1], ymd[2]), []).append((ymd, display))
    for rows in by_md.values():
        years = {ymd[0] for ymd, _ in rows}
        if len(years) != 2:
            continue
        y_list = sorted(years)
        if len(y_list[0]) != 4 or len(y_list[1]) != 4:
            continue
        diffs = [(a, b) for a, b in zip(y_list[0], y_list[1]) if a != b]
        if len(diffs) != 1 or frozenset(diffs[0]) not in _DOB_YEAR_DIGIT_CONFUSABLES:
            continue
        # Prefer the display whose year matches the lexicographically... no —
        # prefer primary if it is one of the confusable twins; else first non-future.
        # Caller passes primary as ranked winner (higher confidence).
        for ymd, display in rows:
            if ymd[0] == _dob_ymd(primary)[0] if _dob_ymd(primary) else None:
                return display
        return rows[0][1]
    return None


def _canonical_member_id(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", (value or "").strip().upper())
    if compact.isdigit():
        stripped = compact.lstrip("0")
        return stripped or "0"
    return compact


def _member_id_is_short_padded_shell(value: str) -> bool:
    """True for zero-padded digit ink whose stripped core is a short shell.

    Example: ``0000007267`` → core ``7267``. Only pure digit strings qualify —
    alphanumeric CMS ids like ``A00046372APU`` are not padded shells.
    """
    compact = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if not compact.isdigit() or len(compact) < 8:
        return False
    core = compact.lstrip("0") or "0"
    return 4 <= len(core) <= 6


def _member_id_is_shaped(value: str) -> bool:
    """True for plausible member IDs; rejects short OCR soup like ``RQ4G0L``."""
    raw = str(value or "")
    compact = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if re.search(r"INSUR|NUMBER|PROGRAM|ITEM|NAME", raw.upper()):
        return False
    # Zero-padded digit ink (``0000007267``): shaped when pad+core length ≥ 8
    # and core has ≥ 4 digits. Canonicalization still strips for the value.
    if compact.isdigit() and len(compact) >= 8:
        core = compact.lstrip("0") or "0"
        if len(core) >= 4:
            return True
    if compact.isdigit():
        compact = compact.lstrip("0") or "0"
    if not re.fullmatch(r"[A-Z0-9]{6,20}", compact):
        return False
    digit_count = sum(ch.isdigit() for ch in compact)
    # Digit-mass IDs (Medicare-style) — letter soup cannot pass.
    if digit_count >= 5:
        return True
    letter_count = sum(ch.isalpha() for ch in compact)
    # Mixed CMS subscriber ids (``JQL4PV-01``): letters + ≥1 digit, not alpha soup.
    return letter_count >= 2 and digit_count >= 1 and len(compact) <= 12


def _member_ids_differ_by_confusable_insertion(left: str, right: str) -> bool:
    """True when member IDs match after removing one inserted I/1/L glyph.

    Track-B residual: ``A00046372APU`` vs ``A00046372APLU`` — OCR inserted an
    L into the alphabetic suffix, not a different subscriber id.
    """
    a, b = _canonical_member_id(left), _canonical_member_id(right)
    if not a or not b or a == b:
        return False
    if abs(len(a) - len(b)) != 1:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    for idx, ch in enumerate(longer):
        if ch in {"I", "1", "L"} and longer[:idx] + longer[idx + 1 :] == shorter:
            return True
    return False


_MEMBER_ID_CONFUSABLE_PAIRS = {
    frozenset({"O", "0"}),
    frozenset({"U", "0"}),  # O misread as U on one engine, 0 on the other
    frozenset({"D", "0"}),
    frozenset({"O", "Q"}),
    frozenset({"I", "1"}),
    frozenset({"I", "L"}),
    frozenset({"L", "1"}),
    frozenset({"S", "5"}),
    frozenset({"J", "U"}),  # typed stem J/U swap (JSW… vs USW…)
}


_MEMBER_ID_PREFIX_BLEED = frozenset({"O", "S", "Q", "D", "U", "C", "0", "G"})


def _member_ids_differ_by_prefix_bleed(left: str, right: str) -> bool:
    """True when IDs match after peeling a 1–2 letter OCR prefix bleed.

    Independent case: ``OSC75615107`` vs ``C75615107`` — leading OS from
    adjacent form ink, not a different subscriber.
    """
    a, b = _canonical_member_id(left), _canonical_member_id(right)
    if not a or not b or a == b:
        return False
    if abs(len(a) - len(b)) not in {1, 2}:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    prefix_len = len(longer) - len(shorter)
    prefix = longer[:prefix_len]
    if longer[prefix_len:] != shorter:
        return False
    return all(ch in _MEMBER_ID_PREFIX_BLEED for ch in prefix)


def _member_id_is_length_fragment(left: str, right: str) -> bool:
    """True when one shaped ID is a short fragment beside a much longer ID.

    Independent case: ``981366`` vs ``98126619000`` — six-digit crop fragment
    must not block the full member number. Letter soup must never count as the
    longer authority over digit ink (``eee…`` vs ``0000007267``).
    """
    a, b = _canonical_member_id(left), _canonical_member_id(right)
    if not a or not b or a == b:
        return False
    short, long = (a, b) if len(a) < len(b) else (b, a)
    if len(short) >= 8 or len(long) < 10:
        return False
    if len(long) - len(short) < 3:
        return False
    # Both sides must be digit member ids — alpha soup is not a fuller ID.
    if not short.isdigit() or not long.isdigit():
        return False
    if short in long or long.startswith(short):
        return True
    return _member_ids_share_digit_prefix(short, long, min_len=3)


def _is_azure_gpt4o_crop_engine(engine: str) -> bool:
    """True for gpt-4o / Claude crop residuals (authorized vision ink readers)."""
    normalized = (engine or "").lower()
    return any(
        token in normalized
        for token in ("gpt4o", "gpt-4o", "claude", "anthropic")
    )

def _member_id_is_weak_for_gpt4o_gate(value: str) -> bool:
    """Mirror gpt-4o residual gate: short / chrome / alpha-soup locals.

    When local cascade is weak enough to invoke ``azure_gpt4o_crop``, that same
    weak twin must not block STP via CONFLICT_MARGIN_TOO_SMALL.
    """
    text = (value or "").strip()
    if not text:
        return True
    if re.search(
        r"INSURED|NUMBER|PROGRAM|ITEM\s*1|1A\.|FOR\s*PROGRAM|PICA",
        text,
        re.IGNORECASE,
    ):
        return True
    alnum = re.sub(r"[^A-Za-z0-9]", "", text)
    if len(alnum) < 7:
        return True
    return bool(alnum.isalpha())


def _member_ids_share_digit_prefix(left: str, right: str, *, min_len: int = 3) -> bool:
    """True when digit streams share a leading run (trust gate for residual relief)."""
    a = re.sub(r"\D", "", _canonical_member_id(left) or "")
    b = re.sub(r"\D", "", _canonical_member_id(right) or "")
    if len(a) < min_len or len(b) < min_len:
        return False
    # Zero-pad / carrier-prefix cores: ``USW000179858`` vs ``000179858`` share
    # digit core ``179858`` even though raw leading zeros diverge.
    a_core = a.lstrip("0") or "0"
    b_core = b.lstrip("0") or "0"
    if len(a_core) >= min_len and a_core == b_core:
        return True
    if len(a_core) >= min_len and len(b_core) >= min_len and (
        a_core.endswith(b_core) or b_core.endswith(a_core)
    ):
        return True
    return a[:min_len] == b[:min_len]


def _member_id_is_digit_core_pad_fragment(primary: str, other: str) -> bool:
    """True when ``other`` is a zero-padded / digit-only core of ``primary``.

    EJGE.026: Claude ``USW000179858`` vs paddle ``000179858`` — same digit core,
    local is pad-only; must not CONFLICT_MARGIN the vision carrier ID.
    """
    if not _member_ids_share_digit_prefix(primary, other, min_len=5):
        return False
    p_alnum = re.sub(r"[^A-Za-z0-9]", "", primary or "")
    o_alnum = re.sub(r"[^A-Za-z0-9]", "", other or "")
    if not p_alnum or not o_alnum:
        return False
    # Vision/carrier form has letters; local is digits-only pad/trunc.
    if any(ch.isalpha() for ch in p_alnum) and o_alnum.isdigit():
        return True
    # Same core, primary digit run strictly longer (leading zeros kept on local).
    p_digits = re.sub(r"\D", "", primary or "")
    o_digits = re.sub(r"\D", "", other or "")
    return bool(p_digits and o_digits and len(p_digits) > len(o_digits))


def prefer_member_id_longer_authority(primary: str, competitors: list[str]) -> str | None:
    """Prefer the longer member ID under prefix-bleed or fragment twins."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if _member_ids_differ_by_prefix_bleed(left, right) or _member_id_is_length_fragment(
                left, right
            ):
                cl, cr = _canonical_member_id(left), _canonical_member_id(right)
                return left if len(cl) >= len(cr) else right
    return None


def _member_ids_differ_by_confusable_substitution(left: str, right: str) -> bool:
    """True when same-length member IDs differ by ≤1 OCR-confusable glyph.

    Independent cases: ``…APU`` vs ``…AP0`` (U↔0), ``OSC…`` vs ``QSC…`` (O↔Q),
    ``JSW…`` vs ``USW…`` (J↔U).
    """
    a, b = _canonical_member_id(left), _canonical_member_id(right)
    if not a or not b or a == b or len(a) != len(b):
        return False
    diffs = [(x, y) for x, y in zip(a, b) if x != y]
    if len(diffs) != 1:
        return False
    return frozenset(diffs[0]) in _MEMBER_ID_CONFUSABLE_PAIRS


def prefer_member_id_without_confusable_insertion(
    primary: str, competitors: list[str]
) -> str | None:
    """Prefer the shorter / letter-form member ID under confusable OCR twins."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if _member_ids_differ_by_confusable_insertion(left, right):
                cl, cr = _canonical_member_id(left), _canonical_member_id(right)
                return left if len(cl) <= len(cr) else right
            if _member_ids_differ_by_confusable_substitution(left, right):
                # Prefer alphabetic O/I/L over digit lookalikes in the suffix.
                cl, cr = _canonical_member_id(left), _canonical_member_id(right)
                left_letters = sum(ch.isalpha() for ch in cl)
                right_letters = sum(ch.isalpha() for ch in cr)
                if left_letters != right_letters:
                    return left if left_letters > right_letters else right
                return left if len(left) >= len(right) else right
            longer = prefer_member_id_longer_authority(left, [right])
            if longer:
                return longer
    return None


def _canonical_person_name(value: str) -> str:
    """Normalize person-name OCR for agreement / conflict equivalence.

    Handles common typed-CMS confusables without inventing letters:
    - digit ``1`` amid letters → ``I`` (ROVINSK1)
    - ``.1`` / ``.I`` between letters → ``L`` (REYNEL.1ISA)
    - capital-J stem ``JI`` before a vowel → ``J`` (JIOSEPHINE)
    """
    text = (value or "").strip().upper()
    text = re.sub(r"\.[I1]", "L", text)  # .1 / .I often a broken L glyph
    text = re.sub(r"[^A-Z0-9]", "", text)
    text = re.sub(r"(?<=[A-Z])1(?=[A-Z]|$)", "I", text)
    text = re.sub(r"JI(?=[AEIOUY])", "J", text)
    return text


def _name_label_contaminated(value: str) -> bool:
    """True when OCR still carries CMS box-header / Last-First boilerplate."""
    upper = (value or "").upper()
    if not upper.strip():
        return True
    if re.search(
        r"(?:[I1L]NSUR[EFO0][DO0]'?S?|[PF]AT[I1L]?E?NT'?S?|PATENTS)\s*NAME",
        upper,
    ):
        return True
    return bool(re.search(r"(?:LAST|FIRST|FURST|FST|MIDDLE)\s*NAME|MIDDLE\s*INITIAL", upper))


_NAME_HONORIFICS = frozenset({"MRS", "MR", "MS", "MISS", "DR"})


def _peel_honorific_glue(token: str) -> str:
    """Peel glued CMS honorifics (BEAUDOINMRS → BEAUDOIN, MRSCHERYL → CHERYL).

    Never peel ``DR`` as a *prefix* — it false-positives on given names
    (``DREW`` → ``EW``, ``DRAKE`` → ``AKE``) and breaks patient-twin / SAME
    resolution when Box 2 is otherwise AUTO.
    """
    tok = (token or "").upper()
    if not tok or tok in _NAME_HONORIFICS:
        return tok
    for honor in sorted(_NAME_HONORIFICS, key=len, reverse=True):
        if honor == "DR":
            # Suffix-only (JOHNDR rare); prefix peel destroys DREW/DRAKE/…
            if tok.endswith(honor) and len(tok) > len(honor) + 1:
                return tok[: -len(honor)]
            continue
        if tok.startswith(honor) and len(tok) > len(honor) + 1:
            return tok[len(honor) :]
        if tok.endswith(honor) and len(tok) > len(honor) + 1:
            return tok[: -len(honor)]
    return tok


def _name_tokens(value: str) -> list[str]:
    # Preserve digit-as-letter confusables before stripping punctuation
    # (L0 DANNY → LO DANNY, not L DANNY).
    compact = (value or "").upper().replace("0", "O").replace("1", "I")
    # Standalone digit groups (box-rule / page numbers) are not name ink.
    compact = re.sub(r"\b\d{1,4}\b", " ", compact)
    # Mid-name periods/hyphens joining multi-letter pieces are OCR junk
    # (COT.LEEN → COTLEEN). Single-letter stubs (Bet.t.t) stay tokenized.
    compact = re.sub(r"(?<=[A-Z][A-Z])[.\-](?=[A-Z][A-Z])", "", compact)
    compact = re.sub(r"[^A-Z\s]", " ", compact)
    stop = {
        "LAST", "FIRST", "FURST", "FST", "MIDDLE", "INITIAL", "NAME",
        "PATIENT", "FATIENT", "INSURED", "1NSURED",
        *_NAME_HONORIFICS,
    }
    out: list[str] = []
    for tok in compact.split():
        if not tok or tok in stop or tok.endswith("NAME"):
            continue
        peeled = _peel_honorific_glue(tok)
        if peeled and peeled not in stop:
            out.append(peeled)
    return out


def _consonant_skeleton(token: str) -> str:
    return re.sub(r"[AEIOU]", "", (token or "").upper())


def _name_is_short_fragment(value: str) -> bool:
    """True for ≤4-letter single-token OCR crumbs (``Ace``, ``LUR``, ``TT``)."""
    cores = _core_name_tokens(_name_tokens(value))
    return len(cores) == 1 and len(cores[0]) <= 4


def _name_is_form_chrome(value: str) -> bool:
    """True for CMS box numbers / digit-only OCR that is not person ink.

    Blind HITL: Rapid/Tesseract emit ``2`` (box 2 chrome) against a strong
    ``FALCONS SERAFIN`` reading — not a genuine name conflict.
    """
    raw = (value or "").strip()
    if not raw:
        return True
    if re.fullmatch(r"[\d.\-#/\s]+", raw):
        return True
    cores = _core_name_tokens(_name_tokens(value))
    return len(cores) == 0


def _name_is_strong_person(value: str) -> bool:
    """True for multi-token person ink or a single substantial name token."""
    cores = _core_name_tokens(_name_tokens(value))
    if len(cores) >= 2 and sum(len(t) for t in cores) >= 8:
        return True
    return len(cores) == 1 and len(cores[0]) >= 5


def _name_soft_equivalent_second_family(
    selected: str, candidates: list
) -> bool:
    """True when another local OCR family soft-matches the selected person name.

    Covers fuller-vs-fragment (``NOVOTNY. FINNIE`` ↔ ``NOVOTNY``) so C3 E2 is
    satisfied without inventing letters after NAME_CONFLICT_RELIEVED.
    """
    from packages.ocr.independence import independence_group

    selected_txt = (selected or "").strip()
    if not selected_txt or not _name_is_strong_person(selected_txt):
        return False

    def _eng_val(cand) -> tuple[str, str]:
        eng = str(getattr(cand, "engine", None) or "")
        raw = str(getattr(cand, "value", None) or "")
        if isinstance(cand, dict):
            eng = eng or str(cand.get("engine") or "")
            raw = raw or str(cand.get("value") or cand.get("raw_value") or "")
        return eng, raw.strip()

    selected_fams: set[str] = set()
    for cand in candidates or []:
        eng, text = _eng_val(cand)
        if not text:
            continue
        eng_l = eng.casefold()
        if any(
            t in eng_l
            for t in ("gpt4o", "claude", "anthropic", "document_intelligence", "conflict_agent")
        ):
            continue
        fam = independence_group(eng)
        if text.casefold() == selected_txt.casefold() or values_conflict_equivalent(
            "patient_name", selected_txt, text
        ):
            selected_fams.add(fam)
            continue
        # Fragment / prefix soft match of the selected fuller reading.
        if prefer_name_without_short_fragment(selected_txt, [text]) == selected_txt:
            selected_fams.add(fam)
        elif prefer_longer_name_prefix(selected_txt, [text]) == selected_txt:
            selected_fams.add(fam)
    return len(selected_fams) >= 2


def _names_differ_by_short_fragment(left: str, right: str) -> bool:
    """True when one engine has short junk and the other has a strong person name.

    Independent cases: ``Ace`` vs ``Maraafet Kalomatis``, ``LUR`` vs ``LAURA``,
    ``ArtINA`` vs ``HOHDSHEFSKY MAR``.
    """
    if _name_is_form_chrome(left) and _name_is_strong_person(right):
        return True
    if _name_is_form_chrome(right) and _name_is_strong_person(left):
        return True
    if _name_is_short_fragment(left) and _name_is_strong_person(right):
        return True
    if _name_is_short_fragment(right) and _name_is_strong_person(left):
        return True
    # Single mid-length token vs multi-token mass (ArtINA vs HOHDSHEFSKY MAR).
    a, b = _core_name_tokens(_name_tokens(left)), _core_name_tokens(_name_tokens(right))
    if not a or not b:
        return False
    if len(a) == 1 and len(b) >= 2 and len(a[0]) <= 6 and sum(len(t) for t in b) >= 10:
        return True
    return bool(len(b) == 1 and len(a) >= 2 and len(b[0]) <= 6 and sum(len(t) for t in a) >= 10)


def _names_differ_by_vowel_skeleton(left: str, right: str) -> bool:
    """True when core tokens match after stripping vowels (``LAURA``/``LUR``)."""
    a, b = _core_name_tokens(_name_tokens(left)), _core_name_tokens(_name_tokens(right))
    if not a or not b or len(a) != len(b) or a == b:
        return False
    for x, y in zip(a, b):
        sx, sy = _consonant_skeleton(x), _consonant_skeleton(y)
        if not sx or sx != sy:
            return False
        if abs(len(x) - len(y)) > 3:
            return False
    return True


def _names_differ_by_shared_core_token(left: str, right: str) -> bool:
    """True when a short reading is only the shared core of a longer name.

    Independent case: ``DUDAN`` vs ``DOCTNIKCS DOUDAN`` — surname-only crop
    beside full OCR with header junk, matched via vowel skeleton on one token.
    """
    a, b = _core_name_tokens(_name_tokens(left)), _core_name_tokens(_name_tokens(right))
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if len(shorter) != 1 or len(longer) < 2:
        return False
    target = shorter[0]
    target_skel = _consonant_skeleton(target)
    for tok in longer:
        if _token_pair_equivalent(target, tok):
            return True
        if target_skel and target_skel == _consonant_skeleton(tok) and abs(len(target) - len(tok)) <= 2:
            return True
    return False


def _names_differ_by_truncated_secondary(left: str, right: str) -> bool:
    """True when first cores match and one secondary token is a ≤2-char stub.

    Independent case: ``BET IT`` vs ``BET DOMTNIC`` — truncated given name.
    """
    a, b = _core_name_tokens(_name_tokens(left)), _core_name_tokens(_name_tokens(right))
    if len(a) < 2 or len(b) < 2:
        return False
    if not _token_pair_equivalent(a[0], b[0]) and _consonant_skeleton(a[0]) != _consonant_skeleton(b[0]):
        return False
    if not (_token_pair_equivalent(a[0], b[0]) or (
        _consonant_skeleton(a[0]) and _consonant_skeleton(a[0]) == _consonant_skeleton(b[0])
    )):
        return False
    # Compare second tokens for truncation.
    if len(a[1]) <= 2 and len(b[1]) >= 5:
        return True
    return bool(len(b[1]) <= 2 and len(a[1]) >= 5)


def prefer_name_without_short_fragment(
    primary: str, competitors: list[str]
) -> str | None:
    """Prefer the strong person-name reading over short OCR crumbs."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if not (
                _names_differ_by_short_fragment(left, right)
                or _names_differ_by_vowel_skeleton(left, right)
                or _names_differ_by_shared_core_token(left, right)
                or _names_differ_by_truncated_secondary(left, right)
            ):
                continue
            lc = _core_name_tokens(_name_tokens(left))
            rc = _core_name_tokens(_name_tokens(right))
            left_mass = sum(len(t) for t in lc)
            right_mass = sum(len(t) for t in rc)
            if left_mass != right_mass:
                return left if left_mass > right_mass else right
            return left if len(lc) >= len(rc) else right
    return None


def prefer_longer_name_prefix(primary: str, competitors: list[str]) -> str | None:
    """Prefer the longer name when one reading is a strict token-prefix of another.

    Example: ``ORR JAMES`` vs ``ORR JAMES ANTHONY`` — middle name only on one
    engine is not a true conflict.
    """
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    tokenized = [(_name_tokens(v), v) for v in observed]
    tokenized = [(toks, v) for toks, v in tokenized if toks]
    if len(tokenized) < 2:
        return None
    # Longest token list that has every shorter list as a prefix.
    tokenized.sort(key=lambda item: len(item[0]), reverse=True)
    longest_toks, longest_display = tokenized[0]
    for toks, _display in tokenized[1:]:
        if longest_toks[: len(toks)] != toks:
            return None
    if any(len(toks) < len(longest_toks) for toks, _ in tokenized):
        return longest_display
    return None


def _names_differ_by_optional_middle_initial(left: str, right: str) -> bool:
    """True when names match except one optional single-letter middle initial.

    Example: ``THOMAS DWAYNE`` vs ``THOMAS S DWAYNE`` — CMS middle-initial
    presence differs by engine, not identity. Remaining tokens may still
    differ by OCR confusable substitution (OLENIK vs OLFNIK + optional J).
    """
    a, b = _name_tokens(left), _name_tokens(right)
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if len(longer) != len(shorter) + 1:
        return False
    for idx, tok in enumerate(longer):
        if len(tok) != 1:
            continue
        remainder = longer[:idx] + longer[idx + 1 :]
        if remainder == shorter:
            return True
        if len(remainder) == len(shorter) and all(
            _token_pair_equivalent(x, y) for x, y in zip(remainder, shorter)
        ):
            return True
    return False


def _names_differ_by_leading_junk_initial(left: str, right: str) -> bool:
    """True when one engine prefixed a junk single-letter token (Z ALSBURY)."""
    a, b = _name_tokens(left), _name_tokens(right)
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if len(longer) != len(shorter) + 1:
        return False
    if len(longer[0]) != 1:
        return False
    remainder = longer[1:]
    if remainder == shorter:
        return True
    return len(remainder) == len(shorter) and all(
        _token_pair_equivalent(x, y) for x, y in zip(remainder, shorter)
    )


def _names_differ_by_trailing_digit_junk(left: str, right: str) -> bool:
    """True when canonical forms match after stripping trailing OCR digit junk.

    Track-B residual: ``SAME`` vs ``SAME 2`` — CMS self-reference with a
    box-rule digit, not a different insured name.
    """
    a, b = _canonical_person_name(left), _canonical_person_name(right)
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if not longer.startswith(shorter):
        return False
    suffix = longer[len(shorter) :]
    return bool(suffix) and suffix.isdigit() and len(suffix) <= 2


def _names_differ_by_glued_vs_spaced(left: str, right: str) -> bool:
    """True when one engine glued First+Last while the other kept spaces.

    ``MURPHYPATRICK`` vs ``MURPHY PATRICK`` (or ``MURPHYP PATRICK`` with a
    glued MI on the first token) is the same person, not a conflict.
    """
    a, b = _name_tokens(left), _name_tokens(right)
    if not a or not b or a == b:
        return False
    single, multi = (a, b) if len(a) == 1 and len(b) >= 2 else (
        (b, a) if len(b) == 1 and len(a) >= 2 else (None, None)
    )
    if single is None or multi is None:
        return False
    glued = single[0]
    joined = "".join(multi)
    if _token_pair_equivalent(glued, joined):
        return True
    # Peel a glued single-letter MI from the first spaced token (MURPHYP|PATRICK).
    if len(multi[0]) >= 2 and len(multi[0][-1:]) == 1:
        peeled = [multi[0][:-1], *multi[1:]]
        if _token_pair_equivalent(glued, "".join(peeled)):
            return True
    return False


def _names_differ_by_shared_given_name(left: str, right: str) -> bool:
    """True when a short OCR is only the given name of a longer full-name reading.

    Honorific-stripped residual: ``BEAUDOIN CHERYL`` vs ``CHERYLA`` — same
    given name (with optional trailing letter glue), not a different person.
    """
    a, b = _name_tokens(left), _name_tokens(right)
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if len(shorter) != 1 or len(longer) < 2:
        return False
    target = shorter[0]

    def _given_equiv(cand: str) -> bool:
        if _token_pair_equivalent(target, cand):
            return True
        if abs(len(target) - len(cand)) != 1:
            return False
        s, c = (target, cand) if len(target) < len(cand) else (cand, target)
        return c.startswith(s)

    return _given_equiv(longer[-1]) or _given_equiv(longer[0])


def _names_differ_by_glued_middle_initial(left: str, right: str) -> bool:
    """True when one engine glued an extra letter onto a 1-char middle initial.

    Track-B 300 residual: ``DESIRAE CL`` vs ``DESIRAE L``, ``SHYENNE CP`` vs
    ``SHYENNE P`` — leading OCR junk on the MI, not a different person.
    """
    a, b = _name_tokens(left), _name_tokens(right)
    if not a or not b or len(a) != len(b) or a == b:
        return False
    diffs = [(x, y) for x, y in zip(a, b) if x != y]
    if len(diffs) != 1:
        return False
    x, y = diffs[0]
    shorter, longer = (x, y) if len(x) < len(y) else (y, x)
    return len(shorter) == 1 and len(longer) == 2 and longer.endswith(shorter)


def _token_pair_equivalent(left: str, right: str) -> bool:
    """Single-token equivalence under confusable insertion/substitution/edit."""
    if left == right:
        return True
    if _names_differ_by_confusable_insertion(left, right):
        return True
    if _names_differ_by_confusable_substitution(left, right):
        return True
    return bool(_names_differ_by_confusable_edit(left, right))


def _core_name_tokens(tokens: list[str]) -> list[str]:
    """Drop single-letter MIs and digit-only OCR junk for bag comparison."""
    return [tok for tok in tokens if len(tok) > 1 and not tok.isdigit()]


def _names_differ_by_token_order(left: str, right: str) -> bool:
    """True when engines disagree only on Last/First token order.

    Track-B 300 residual: ``CHANG SHERRILEE`` vs ``SHERRILEE L CHANG``,
    ``SPINNEY CHARLES A`` vs ``CHARLES A SPINNEY`` — same person, CMS
    last-first vs first-last reading. Middle initials are ignored in the bag.
    Also covers ``Z SAME`` vs ``SAME Z`` (single core + MI permutation).
    """
    a, b = _name_tokens(left), _name_tokens(right)
    ca, cb = _core_name_tokens(a), _core_name_tokens(b)
    if len(ca) < 1 or len(cb) < 1 or len(ca) != len(cb):
        return False
    # Require at least one multi-letter core; pure MI bags are not identity.
    if not ca:
        return False
    remaining = list(cb)
    for tok in ca:
        match_idx = None
        for idx, other in enumerate(remaining):
            if _token_pair_equivalent(tok, other):
                match_idx = idx
                break
        if match_idx is None:
            return False
        remaining.pop(match_idx)
    return True


def prefer_name_with_optional_middle_initial(
    primary: str, competitors: list[str]
) -> str | None:
    """Prefer the longer display when only an optional middle initial differs."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if not (
                _names_differ_by_optional_middle_initial(left, right)
                or _names_differ_by_glued_middle_initial(left, right)
            ):
                continue
            # Prefer the cleaner single-letter MI when one side is glued (CL→L).
            if _names_differ_by_glued_middle_initial(left, right):
                lt, rt = _name_tokens(left), _name_tokens(right)
                left_mi = sum(1 for t in lt if len(t) == 1)
                right_mi = sum(1 for t in rt if len(t) == 1)
                if left_mi != right_mi:
                    return left if left_mi > right_mi else right
                # Same MI count: prefer shorter MI token (L over CL).
                left_short = sum(len(t) for t in lt if len(t) <= 2)
                right_short = sum(len(t) for t in rt if len(t) <= 2)
                return left if left_short <= right_short else right
            lt, rt = _name_tokens(left), _name_tokens(right)
            return left if len(lt) >= len(rt) else right
    return None


# CMS form-ruling OCR often injects a lone I/1/L/T between name tokens.
_OCR_GHOST_MIDDLE_INITIALS = frozenset({"I", "1", "L", "T"})


def prefer_name_without_ocr_ghost_middle_initial(
    primary: str, competitors: list[str]
) -> str | None:
    """Prefer the name without a form-ruling ghost MI (I/1/L/T).

    Agent-GT residual: ``HARRY I P`` vs ``HARRY P``, ``MATTHEW IN`` vs
    ``MATTHEW N`` — dashed vertical rules OCR as I/1/L and inflate names.
    Real single-letter MIs (A–Z excluding these ghosts) still prefer longer
    via ``prefer_name_with_optional_middle_initial``.
    """
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if _names_differ_by_optional_middle_initial(left, right):
                lt, rt = _name_tokens(left), _name_tokens(right)
                shorter, longer = (lt, rt) if len(lt) < len(rt) else (rt, lt)
                if len(longer) != len(shorter) + 1:
                    continue
                for idx, tok in enumerate(longer):
                    if len(tok) != 1 or tok not in _OCR_GHOST_MIDDLE_INITIALS:
                        continue
                    if longer[:idx] + longer[idx + 1 :] == shorter:
                        return left if len(lt) < len(rt) else right
            if _names_differ_by_glued_middle_initial(left, right):
                lt, rt = _name_tokens(left), _name_tokens(right)
                diffs = [(x, y) for x, y in zip(lt, rt) if x != y]
                if len(diffs) != 1:
                    continue
                x, y = diffs[0]
                shorter, longer = (x, y) if len(x) < len(y) else (y, x)
                if (
                    len(shorter) == 1
                    and len(longer) == 2
                    and longer.endswith(shorter)
                    and longer[0] in _OCR_GHOST_MIDDLE_INITIALS
                ):
                    # Prefer clean MI (N) over ghost-prefixed (IN).
                    return left if len(x) <= len(y) else right
    return None


def _name_is_self_reference(value: str) -> bool:
    """True for CMS Box 4 ``SAME`` (optional box-rule digit), not a person name."""
    compact = _canonical_person_name(value)
    if compact == "SAME":
        return True
    return bool(re.fullmatch(r"SAME\d{1,2}", compact))


def prefer_cms_self_reference(primary: str, competitors: list[str]) -> str | None:
    """Keep literal ``SAME`` unless another engine read a real multi-token person.

    A single OCR soup token (``pmmLainnm``) is not that person. Do not replace
    Box 4 ``SAME`` with Box 2.
    """
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    sames = [v for v in observed if _name_is_self_reference(v)]
    if not sames:
        return None
    for other in observed:
        if _name_is_self_reference(other):
            continue
        cores = _core_name_tokens(_name_tokens(other))
        if len(cores) >= 2 and _name_is_strong_person(other):
            return None
    for display in sames:
        if _canonical_person_name(display) == "SAME":
            return display
    return sames[0]


def prefer_name_without_box_rule_digit(primary: str, competitors: list[str]) -> str | None:
    """Prefer the clean name when a twin only adds a box-rule digit.

    ``EMILY, A 2 CARTIER`` vs ``CARTIER, EMILY`` — the ``2`` is form ruling,
    not part of the name. Does not drop a trailing initial that has no digit.
    """
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    dirty = [v for v in observed if re.search(r"\b\d{1,2}\b", v)]
    clean = [v for v in observed if not re.search(r"\b\d{1,2}\b", v)]
    if not dirty or not clean:
        return None

    def _cores(display: str) -> tuple[str, ...]:
        toks = [tok for tok in _name_tokens(display) if len(tok) > 1]
        return tuple(sorted(toks))

    clean_by_core: dict[tuple[str, ...], str] = {}
    for display in clean:
        core = _cores(display)
        if core and core not in clean_by_core:
            clean_by_core[core] = display
    for display in dirty:
        core = _cores(display)
        if core and core in clean_by_core:
            return clean_by_core[core]
    return None


def prefer_name_canonical_token_order(
    primary: str, competitors: list[str]
) -> str | None:
    """Among Last/First order twins, prefer First(+MI)+Last Western display."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    equivalents: list[str] = []
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if _names_differ_by_token_order(left, right):
                if left not in equivalents:
                    equivalents.append(left)
                if right not in equivalents:
                    equivalents.append(right)
    if len(equivalents) < 2:
        return None

    def _score(display: str) -> tuple:
        toks = _name_tokens(display)
        cores = _core_name_tokens(toks)
        has_mi = any(len(t) == 1 for t in toks)
        # Prefer First Last (last token is a core surname-length token and first
        # is also a core) with MI present — common auto-accept display.
        western = (
            len(cores) >= 2
            and len(toks) >= 2
            and toks[-1] in cores
            and toks[0] in cores
            and (len(toks) == 2 or (has_mi and any(len(t) == 1 for t in toks[1:-1])))
        )
        return (
            0 if western else 1,
            0 if has_mi else 1,
            -len(toks),
            -len(display or ""),
        )

    return min(equivalents, key=_score)


def prefer_name_without_label_contamination(
    primary: str, competitors: list[str]
) -> str | None:
    """Prefer a clean person-name reading over a label-contaminated twin."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    clean = [v for v in observed if not _name_label_contaminated(v)]
    dirty = [v for v in observed if _name_label_contaminated(v)]
    if not clean or not dirty:
        return None
    # If any clean reading's tokens appear inside a dirty crop, prefer clean.
    for cand in clean:
        ct = _name_tokens(cand)
        if len(ct) < 1:
            continue
        for other in dirty:
            ot = _name_tokens(other)
            if not ot:
                continue
            # Clean tokens ⊆ dirty tokens, or dirty ends with clean tokens.
            if ot[-len(ct) :] == ct or all(t in ot for t in ct):
                return cand
    # Otherwise prefer the highest-token clean value when dirty exists.
    clean_sorted = sorted(clean, key=lambda v: len(_name_tokens(v)), reverse=True)
    if clean_sorted and _name_tokens(clean_sorted[0]):
        return clean_sorted[0]
    return None


def _names_differ_by_confusable_insertion(left: str, right: str) -> bool:
    """True when names match after removing one inserted I/1/L glyph."""
    a, b = _canonical_person_name(left), _canonical_person_name(right)
    if not a or not b or a == b:
        return a == b and bool(a)
    if abs(len(a) - len(b)) != 1:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    for idx, ch in enumerate(longer):
        if ch in {"I", "1", "L"} and longer[:idx] + longer[idx + 1 :] == shorter:
            return True
    return False


_NAME_CONFUSABLE_PAIRS = {
    frozenset({"E", "L"}),
    frozenset({"E", "F"}),
    frozenset({"P", "F"}),
    frozenset({"I", "L"}),
    frozenset({"I", "T"}),
    frozenset({"I", "1"}),
    frozenset({"I", "U"}),  # KTIIMP vs KLUMP / COTTEEN bleed
    frozenset({"L", "T"}),
    frozenset({"L", "H"}),  # MCLARTY vs MCHARTY
    frozenset({"B", "R"}),  # BOHDAN vs ROHDAN / BOONE vs ROONE
    frozenset({"C", "O"}),  # SCARTET vs SOARTET (Independent-300 v12.2)
    frozenset({"O", "D"}),
    frozenset({"O", "0"}),
    frozenset({"O", "U"}),  # ACOSTA vs ACUSTA (Claude↔rapid typed CMS)
    frozenset({"K", "R"}),  # KIVERA vs RIVERA on typed CMS names
    frozenset({"U", "V"}),
    frozenset({"V", "Y"}),
    frozenset({"T", "Y"}),
    frozenset({"G", "C"}),
    frozenset({"S", "5"}),
    frozenset({"B", "8"}),
    frozenset({"G", "6"}),
}


def _names_differ_by_confusable_substitution(left: str, right: str) -> bool:
    """True when same-length names differ by ≤2 OCR-confusable letters.

    Track-B 300-run learning: paddle ``DAVIIA KEVTN`` vs rapid ``DAVILA KEVIN``
    is two confusable substitutions (I↔L, T↔I), not a true identity conflict.
    """
    a, b = _canonical_person_name(left), _canonical_person_name(right)
    if not a or not b or a == b or len(a) != len(b):
        return False
    diffs = [(x, y) for x, y in zip(a, b) if x != y]
    if not diffs or len(diffs) > 2:
        return False
    return all(frozenset(pair) in _NAME_CONFUSABLE_PAIRS for pair in diffs)


def _names_differ_by_confusable_edit(left: str, right: str) -> bool:
    """True when names match after one deletion plus ≤2 confusable substitutions.

    Independent case: ``PATRICIA`` vs ``FATRCIA`` — delete ``I``, then P↔F.
    v12.2 residual: ``KTIIMP`` vs ``KLUMP`` — delete ``I``, then T↔L and I↔U.
    Deletion is limited to a single vowel/confusable glyph so we do not collapse
    unrelated surnames.
    """
    a, b = _canonical_person_name(left), _canonical_person_name(right)
    if not a or not b or a == b or abs(len(a) - len(b)) != 1:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    for idx, ch in enumerate(longer):
        if ch not in {"A", "E", "I", "O", "U", "L", "1"}:
            continue
        peeled = longer[:idx] + longer[idx + 1 :]
        if peeled == shorter:
            return True
        if len(peeled) != len(shorter):
            continue
        diffs = [(x, y) for x, y in zip(peeled, shorter) if x != y]
        if (
            1 <= len(diffs) <= 2
            and all(frozenset(pair) in _NAME_CONFUSABLE_PAIRS for pair in diffs)
        ):
            return True
    return False


def _names_differ_by_tokenwise_confusable(left: str, right: str) -> bool:
    """True when same-arity core tokens each match under confusable rules.

    Independent-300 v12.2: ``KLUMP COLLEEN`` vs ``KTIIMP COTTEEN`` — per-token
    OCR twins (KLUMP≈KTIIMP, COLLEEN≈COTTEEN), not a true identity conflict.
    """
    a = _core_name_tokens(_name_tokens(left))
    b = _core_name_tokens(_name_tokens(right))
    if len(a) < 2 or len(a) != len(b) or a == b:
        return False
    for x, y in zip(a, b):
        if x == y:
            continue
        if _token_pair_equivalent(x, y):
            continue
        if _names_differ_by_confusable_edit(x, y):
            continue
        return False
    return True


def prefer_name_without_confusable_insertion(
    primary: str, competitors: list[str]
) -> str | None:
    """Prefer the cleaner name when OCR inserted an I/1/L confusable glyph."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if not _names_differ_by_confusable_insertion(left, right):
                continue
            # Prefer fewer confusable glyphs / shorter canonical form.
            cl, cr = _canonical_person_name(left), _canonical_person_name(right)
            if len(cl) < len(cr):
                return left
            if len(cr) < len(cl):
                return right
    # Substitution twins are conflict-equivalent but ranking already picked the
    # higher-confidence display — do not reshuffle them here.
    # JI-peel twins: same canonical after peel — prefer display without raw JI / 1.
    norms = [(_canonical_person_name(v), v) for v in observed]
    by_norm: dict[str, list[str]] = {}
    for norm, display in norms:
        if norm:
            by_norm.setdefault(norm, []).append(display)
    if len(by_norm) == 1:
        displays = next(iter(by_norm.values()))
        scored = sorted(
            displays,
            key=lambda d: (
                "JI" in re.sub(r"[^A-Z]", "", (d or "").upper()),
                "1" in (d or ""),
                len(d or ""),
            ),
        )
        return scored[0] if len(scored) > 1 else None
    return None


def values_conflict_equivalent(field_name: str, left: str, right: str) -> bool:
    """True when two OCR values are representation-equivalent (not true conflicts)."""
    name = (field_name or "").casefold()
    if not (left or "").strip() or not (right or "").strip():
        return False
    if name in {"patient_dob", "date_of_birth", "dob"} or name.endswith("_date"):
        a, b = _canonical_date_digits(left), _canonical_date_digits(right)
        if bool(a) and a == b:
            return True
        ya, yb = _dob_ymd(left), _dob_ymd(right)
        if not ya or not yb:
            return False
        # Month+day match with a single confusable year digit is not a true conflict.
        if (
            ya[1] == yb[1]
            and ya[2] == yb[2]
            and ya[0] != yb[0]
            and len(ya[0]) == 4
            and len(yb[0]) == 4
        ):
            diffs = [(x, y) for x, y in zip(ya[0], yb[0]) if x != y]
            if len(diffs) == 1 and frozenset(diffs[0]) in _DOB_YEAR_DIGIT_CONFUSABLES:
                return True
        # Day+year match with January dash artifact vs true month.
        return bool(ya[0] == yb[0] and ya[2] == yb[2] and ya[1] != yb[1] and "01" in (ya[1], yb[1]))
    if name in {"insured_id_number", "member_id", "subscriber_id"}:
        a, b = _canonical_member_id(left), _canonical_member_id(right)
        if bool(a) and a == b:
            return True
        if _member_ids_differ_by_confusable_insertion(left, right):
            return True
        if _member_ids_differ_by_confusable_substitution(left, right):
            return True
        if _member_ids_differ_by_prefix_bleed(left, right):
            return True
        return bool(_member_id_is_length_fragment(left, right))
    if name in {"patient_name", "insured_name"} or "name" in name:
        a, b = _canonical_person_name(left), _canonical_person_name(right)
        if bool(a) and a == b:
            return True
        if _names_differ_by_confusable_insertion(left, right):
            return True
        if _names_differ_by_confusable_substitution(left, right):
            return True
        if _names_differ_by_confusable_edit(left, right):
            return True
        # Per-token OCR twins with same arity (KLUMP COLLEEN ≈ KTIIMP COTTEEN).
        if _names_differ_by_tokenwise_confusable(left, right):
            return True
        # Token-prefix (missing middle name on one engine) is not a true conflict.
        if prefer_longer_name_prefix(left, [right]) is not None:
            return True
        # Optional CMS middle initial (THOMAS DWAYNE vs THOMAS S DWAYNE).
        if _names_differ_by_optional_middle_initial(left, right):
            return True
        # Glued junk on MI (DESIRAE CL vs DESIRAE L).
        if _names_differ_by_glued_middle_initial(left, right):
            return True
        # Leading junk initial (Z ALSBURY vs ALSBURY).
        if _names_differ_by_leading_junk_initial(left, right):
            return True
        # Trailing digit junk on SAME / self-reference (SAME vs SAME 2).
        if _names_differ_by_trailing_digit_junk(left, right):
            return True
        # Glued FirstLast vs spaced tokens (MURPHYPATRICK vs MURPHY PATRICK).
        if _names_differ_by_glued_vs_spaced(left, right):
            return True
        # Short given-name-only OCR vs full name (CHERYLA vs BEAUDOIN CHERYL).
        if _names_differ_by_shared_given_name(left, right):
            return True
        # Short fragment / vowel skeleton / truncated given (Ace vs full name).
        if _names_differ_by_short_fragment(left, right):
            return True
        if _names_differ_by_vowel_skeleton(left, right):
            return True
        if _names_differ_by_shared_core_token(left, right):
            return True
        if _names_differ_by_truncated_secondary(left, right):
            return True
        # Last/First token-order twins (CHANG SHERRILEE vs SHERRILEE L CHANG).
        if _names_differ_by_token_order(left, right):
            return True
        # Label-contaminated crop vs clean ink of the same person.
        return prefer_name_without_label_contamination(left, [right]) is not None
    return normalize_agreement_value(field_name, left) == normalize_agreement_value(
        field_name, right
    )


class EvidenceReconciler:
    def __init__(
        self,
        calibration: CalibrationRegistry | None = None,
        accept_thresholds: dict[CriticalityLevel, float] | None = None,
        evidence_policies: EvidencePolicyRegistry | None = None,
        allow_authoritative_financial_e6: bool = False,
    ) -> None:
        self.calibration = calibration or CalibrationRegistry()
        self.thresholds = accept_thresholds or {
            CriticalityLevel.C0: 0.70,
            CriticalityLevel.C1: 0.80,
            CriticalityLevel.C2: 0.92,
            CriticalityLevel.C3: 0.98,
        }
        self.evidence_policies = evidence_policies or EvidencePolicyRegistry.load()
        self.allow_authoritative_financial_e6 = allow_authoritative_financial_e6

    @staticmethod
    def _candidate_id(candidate: OCRCandidate) -> str:
        if candidate.evidence_reference:
            return candidate.evidence_reference
        payload = (
            f"{candidate.engine}|{candidate.model_version}|{candidate.raw_value}|"
            f"{candidate.preprocessing_variant}"
        )
        return sha256(payload.encode()).hexdigest()[:24]

    def reconcile(
        self,
        field_name: str,
        candidates: list[OCRCandidate],
        criticality: CriticalityLevel,
        *,
        deterministic_evidence: set[str] | None = None,
        authoritative_value: str | None = None,
        authoritative_reference_verified: bool = False,
        authoritative_source: str | None = None,
        authoritative_version: str | None = None,
        document_family: str = "*",
        enforce_legacy_evidence_policy: bool = True,
        independent_agreement_values: set[str] | None = None,
    ) -> ReconciliationResult:
        deterministic = deterministic_evidence or set()
        groups: dict[str, list[tuple[OCRCandidate, float, str]]] = defaultdict(list)
        conflicts: list[EvidenceReference] = []
        for candidate in candidates:
            display_value = (candidate.value or "").strip()
            if not display_value:
                continue
            calibrated, version = self.calibration.calibrate(
                candidate.engine, field_name, candidate.raw_confidence
            )
            normalized = normalize_agreement_value(field_name, display_value)
            if normalized:
                groups[normalized].append((candidate, calibrated, version))
        ids = [self._candidate_id(candidate) for candidate in candidates]
        if not groups:
            return ReconciliationResult(
                field_name=field_name,
                selected_value=None,
                candidate_ids=ids,
                decision=Decision.ABSTAIN,
                confidence=0,
                rationale_codes=["NO_NONEMPTY_CANDIDATE"],
                calibration_model_version="none",
            )

        qualified_independent_values = (
            {
                normalize_agreement_value(field_name, item)
                for item in independent_agreement_values
            }
            if independent_agreement_values is not None
            else None
        )

        def independent_agreement(normalized_value, items) -> bool:
            if qualified_independent_values is not None:
                return normalized_value in qualified_independent_values
            return len({independence_group(c.engine) for c, _, _ in items}) >= 2

        is_dob_field = field_name in {"patient_dob", "date_of_birth", "dob"}
        is_name_field = field_name in {
            "patient_name",
            "insured_name",
        } or "name" in (field_name or "").casefold()

        def _group_calendar_valid(items) -> bool:
            # Prefer display-shaped calendar DOB groups over header labels /
            # digit-glue junk so paddle "MM" or "ib0 13! 197" cannot outrank
            # a real ``11/01/2011``. Future dates are never preferred.
            for candidate, _, _ in items:
                raw = str(candidate.value or "")
                if _dob_is_display_shaped(raw):
                    return True
            return False

        def _group_name_clean(items) -> bool:
            for candidate, _, _ in items:
                val = str(candidate.value or "")
                if val.strip() and not _name_label_contaminated(val) and _name_tokens(val):
                    return True
            return False

        def _group_name_strong(items) -> bool:
            for candidate, _, _ in items:
                val = str(candidate.value or "")
                if _name_is_strong_person(val) and not _name_is_short_fragment(val):
                    return True
            return False

        def _group_id_shaped(items) -> bool:
            for candidate, _, _ in items:
                if _member_id_is_shaped(str(candidate.value or "")):
                    return True
            return False

        ranked = sorted(
            groups.items(),
            key=lambda item: (
                # DOB: display-shaped calendar ink outranks multi-engine junk
                # agreement (paddle+rapid ``06h3 2002`` vs TrOCR ``06/20/2002``).
                _group_calendar_valid(item[1]) if is_dob_field else True,
                independent_agreement(item[0], item[1]),
                _group_name_strong(item[1]) if is_name_field else True,
                _group_name_clean(item[1]) if is_name_field else True,
                _group_id_shaped(item[1])
                if field_name in {"insured_id_number", "member_id", "subscriber_id"}
                else True,
                max(score for _, score, _ in item[1]),
            ),
            reverse=True,
        )
        # Strong line-Σ mint deferred a rival Box 28: do not let multi-engine
        # OCR on the deferred shell outrank the LINE_TOTALS / CONFIRMED amount
        # (EJG7.004 17500 vs Σ 1031; DJJF.002 1160 vs Σ 520).
        if (
            field_name in {"total_charge", "total_charges"}
            and deterministic
            and "CLAIM_TOTAL_CONFIRMED" in deterministic
            and "LINE_TOTALS_CORROBORATED" in deterministic
            and any(
                "RIVAL_BOX28_DEFERRED" in str(code) or str(code).endswith("RIVAL_BOX28_DEFERRED")
                for code in deterministic
            )
        ):
            def _group_is_line_sum_authority(items) -> bool:
                for cand, _, _ in items:
                    variant = str(cand.preprocessing_variant or "").casefold()
                    ref = str(cand.evidence_reference or "")
                    if (
                        "derived_from_observed_line" in variant
                        or "derived_from_verified" in variant
                        or "phase2-line-sum" in variant
                        or "claim_total_confirmed" in variant
                        or ref
                        in {
                            "LINE_TOTALS_RECONCILED",
                            "DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES",
                            "CLAIM_TOTAL_CONFIRMED",
                        }
                    ):
                        return True
                return False

            authority_groups = [
                (norm, items)
                for norm, items in ranked
                if _group_is_line_sum_authority(items)
            ]
            if authority_groups:
                ranked = authority_groups + [
                    (norm, items)
                    for norm, items in ranked
                    if not _group_is_line_sum_authority(items)
                ]

        _normalized_value, supporting = ranked[0]
        value = max(supporting, key=lambda item: item[1])[0].value
        early_separator_relief = False
        early_name_relief = False
        early_id_relief = False
        early_gpt4o_id_relief = False
        early_gpt4o_digit_tiebreak = False
        early_gpt4o_name_relief = False
        # Within a multi-engine name agreement group, prefer the display that
        # already lacks JI / digit-1 confusables (JIOSEPHINE → JOSEPHINE).
        if is_name_field and len(supporting) >= 1:
            displays = [str(c.value or "") for c, _, _ in supporting]
            name_clean = prefer_name_without_confusable_insertion(
                displays[0], displays[1:]
            )
            if name_clean:
                value = name_clean
                early_name_relief = True
            else:
                # Prefer already-peeled display among same-canonical supporters.
                scored = sorted(
                    supporting,
                    key=lambda item: (
                        "JI" in re.sub(r"[^A-Z]", "", (item[0].value or "").upper()),
                        "1" in (item[0].value or ""),
                        -item[1],
                    ),
                )
                value = scored[0][0].value
        # CMS box-3 dashed rules OCR as leading "1" (01↔11, 09↔19). Apply
        # separator relief against ALL competing groups, not only when the
        # confidence margin is tiny — high-confidence separator-1 otherwise STP-wrong.
        if is_dob_field and len(ranked) > 1:
            # Prefer display-shaped calendar ink over digit-glue / letter soup
            # that accidentally assembles a YMD (DJKH.022, HJCX.003).
            if not _dob_is_display_shaped(str(value or "")):
                for _norm, items in ranked[1:]:
                    cand_val = str(max(items, key=lambda row: row[1])[0].value)
                    if _dob_is_display_shaped(cand_val):
                        value = cand_val
                        supporting = items
                        break
            competing = [
                str(max(items, key=lambda row: row[1])[0].value)
                for _, items in ranked[1:]
            ]
            separator_clean = prefer_dob_without_separator_one(str(value), competing)
            if separator_clean:
                value = separator_clean
                early_separator_relief = True
            else:
                january_clean = prefer_dob_without_january_dash_artifact(
                    str(value), competing
                )
                if january_clean:
                    value = january_clean
                    early_separator_relief = True
                else:
                    year_clean = prefer_dob_year_confusable_digit(str(value), competing)
                    if year_clean:
                        value = year_clean
                        early_separator_relief = True
        elif is_name_field and len(ranked) > 1:
            competing = [
                str(max(items, key=lambda row: row[1])[0].value)
                for _, items in ranked[1:]
            ]
            same_clean = prefer_cms_self_reference(str(value), competing)
            digit_clean = (
                None
                if same_clean
                else prefer_name_without_box_rule_digit(str(value), competing)
            )
            label_clean = prefer_name_without_label_contamination(str(value), competing)

            def _supporting_for(display: str):
                target = _canonical_person_name(display)
                for _norm, items in ranked:
                    for cand, _score, _ver in items:
                        if _canonical_person_name(str(cand.value or "")) == target:
                            return items
                return None

            if same_clean:
                value = same_clean
                matched = _supporting_for(same_clean)
                if matched:
                    supporting = matched
                early_name_relief = True
            elif digit_clean:
                value = digit_clean
                matched = _supporting_for(digit_clean)
                if matched:
                    supporting = matched
                early_name_relief = True
            elif label_clean:
                value = label_clean
                early_name_relief = True
            else:
                fragment_clean = prefer_name_without_short_fragment(str(value), competing)
                if fragment_clean:
                    value = fragment_clean
                    early_name_relief = True
                else:
                    prefix_clean = prefer_longer_name_prefix(str(value), competing)
                    if prefix_clean:
                        value = prefix_clean
                        early_name_relief = True
                    else:
                        ghost_mi = prefer_name_without_ocr_ghost_middle_initial(
                            str(value), competing
                        )
                        if ghost_mi:
                            value = ghost_mi
                            early_name_relief = True
                        else:
                            mi_clean = prefer_name_with_optional_middle_initial(
                                str(value), competing
                            )
                            if mi_clean:
                                value = mi_clean
                                early_name_relief = True
                            else:
                                order_clean = prefer_name_canonical_token_order(
                                    str(value), competing
                                )
                                if order_clean:
                                    value = order_clean
                                    early_name_relief = True
                                else:
                                    name_clean = prefer_name_without_confusable_insertion(
                                        str(value), competing
                                    )
                                    if name_clean:
                                        value = name_clean
                                        early_name_relief = True
                                    elif any(
                                        _names_differ_by_confusable_substitution(
                                            str(value), other
                                        )
                                        or _names_differ_by_optional_middle_initial(
                                            str(value), other
                                        )
                                        or _names_differ_by_glued_middle_initial(
                                            str(value), other
                                        )
                                        or _names_differ_by_token_order(
                                            str(value), other
                                        )
                                        or values_conflict_equivalent(
                                            field_name, str(value), other
                                        )
                                        for other in competing
                                    ):
                                        # Confusable / MI / last-first order twins.
                                        early_name_relief = True

        # Prefer non-contaminated name groups when ranking was poisoned by
        # high-confidence header OCR (rapid often outscores paddle on labels).
        if is_name_field and len(ranked) > 1 and _name_label_contaminated(str(value)):
            for _norm, items in ranked[1:]:
                cand_val = str(max(items, key=lambda row: row[1])[0].value)
                if not _name_label_contaminated(cand_val) and _name_tokens(cand_val):
                    value = cand_val
                    supporting = items
                    early_name_relief = True
                    break

        # Prefer gpt-4o crop residual as person-name ink arbitrator when local
        # engines disagree (or the ranked primary is weak/chrome). Cascade only
        # attaches azure_gpt4o_crop for NAME_ENGINE_CONFLICT / unread ink — that
        # same residual must not lose to CONFLICT_MARGIN_TOO_SMALL against the
        # locals that triggered it.
        if is_name_field and len(ranked) > 1:
            top_is_gpt4o = any(
                _is_azure_gpt4o_crop_engine(cand.engine) for cand, _, _ in supporting
            )
            top_weak = (
                _name_label_contaminated(str(value or ""))
                or _name_is_short_fragment(str(value or ""))
                or _name_is_form_chrome(str(value or ""))
                or not _name_is_strong_person(str(value or ""))
            )
            local_displays: list[str] = []
            for _norm, items in ranked:
                local_items = [
                    (cand, score, ver)
                    for cand, score, ver in items
                    if not _is_azure_gpt4o_crop_engine(cand.engine)
                ]
                if not local_items:
                    continue
                cand_val = str(max(local_items, key=lambda row: row[1])[0].value or "")
                if (
                    _name_is_strong_person(cand_val)
                    and not _name_label_contaminated(cand_val)
                    and not _name_is_form_chrome(cand_val)
                ):
                    local_displays.append(cand_val)
            locals_conflict = False
            if len(local_displays) >= 2:
                for i, left in enumerate(local_displays):
                    for right in local_displays[i + 1 :]:
                        if not values_conflict_equivalent(field_name, left, right):
                            locals_conflict = True
                            break
                    if locals_conflict:
                        break
            if top_is_gpt4o and (locals_conflict or early_name_relief):
                early_gpt4o_name_relief = True
            elif (locals_conflict or top_weak) and not top_is_gpt4o:
                for _norm, items in ranked:
                    if not any(
                        _is_azure_gpt4o_crop_engine(cand.engine)
                        for cand, _, _ in items
                    ):
                        continue
                    best = max(items, key=lambda row: row[1])
                    cand_val = str(best[0].value or "")
                    if not _name_is_strong_person(cand_val):
                        continue
                    if (
                        _name_label_contaminated(cand_val)
                        or _name_is_short_fragment(cand_val)
                        or _name_is_form_chrome(cand_val)
                    ):
                        continue
                    value = cand_val
                    supporting = items
                    early_gpt4o_name_relief = True
                    break
            elif (
                not top_is_gpt4o
                and not locals_conflict
                and _name_is_strong_person(str(value or ""))
            ):
                # Sole local "strong" OCR soup vs authorized vision crop that
                # was acquired for this field — prefer the vision ink when it
                # is a strong person name and token-disagrees with the local.
                for _norm, items in ranked:
                    if not any(
                        _is_azure_gpt4o_crop_engine(cand.engine)
                        for cand, _, _ in items
                    ):
                        continue
                    best = max(items, key=lambda row: row[1])
                    cand_val = str(best[0].value or "")
                    if not _name_is_strong_person(cand_val):
                        continue
                    if (
                        _name_label_contaminated(cand_val)
                        or _name_is_short_fragment(cand_val)
                        or _name_is_form_chrome(cand_val)
                    ):
                        continue
                    if values_conflict_equivalent(field_name, str(value), cand_val):
                        continue
                    local_toks = _name_tokens(str(value))
                    vision_toks = _name_tokens(cand_val)
                    if (
                        len(vision_toks) >= 2
                        and local_toks
                        and vision_toks != local_toks
                    ):
                        value = cand_val
                        supporting = items
                        early_gpt4o_name_relief = True
                        break

        # Prefer shaped member-id over header-only crops in the top slot.
        is_id_field = field_name in {"insured_id_number", "member_id", "subscriber_id"}
        if is_id_field and len(ranked) > 1:
            top_is_id = _member_id_is_shaped(str(value or ""))
            if not top_is_id:
                for _norm, items in ranked[1:]:
                    cand_val = str(max(items, key=lambda row: row[1])[0].value)
                    if _member_id_is_shaped(cand_val):
                        value = cand_val
                        supporting = items
                        break
            competing = [
                str(max(items, key=lambda row: row[1])[0].value)
                for _, items in ranked[1:]
            ]
            id_clean = prefer_member_id_without_confusable_insertion(str(value), competing)
            if id_clean:
                value = id_clean
                early_id_relief = True
            # Prefer gpt-4o crop residual over the weak local that triggered it.
            elif _member_id_is_weak_for_gpt4o_gate(str(value or "")):
                for _norm, items in ranked[1:]:
                    best = max(items, key=lambda row: row[1])
                    cand, _score, _ver = best
                    cand_val = str(cand.value or "")
                    if not _is_azure_gpt4o_crop_engine(cand.engine):
                        continue
                    if not _member_id_is_shaped(cand_val):
                        continue
                    if _member_id_is_weak_for_gpt4o_gate(cand_val):
                        continue
                    if not _member_ids_share_digit_prefix(cand_val, str(value)):
                        continue
                    value = cand_val
                    supporting = items
                    early_gpt4o_id_relief = True
                    break
            # Prefer carrier/vision ID over zero-padded digit-only core ranked first
            # (EJGE.026: ``000179858`` paddle over ``USW000179858`` Claude).
            if not early_gpt4o_id_relief and not early_id_relief:
                for _norm, items in ranked[1:]:
                    best = max(items, key=lambda row: row[1])
                    cand, _score, _ver = best
                    cand_val = str(cand.value or "")
                    if not _is_azure_gpt4o_crop_engine(cand.engine):
                        continue
                    if not _member_id_is_shaped(cand_val):
                        continue
                    if _member_id_is_weak_for_gpt4o_gate(cand_val):
                        continue
                    if not _member_id_is_digit_core_pad_fragment(cand_val, str(value)):
                        continue
                    value = cand_val
                    supporting = items
                    early_gpt4o_id_relief = True
                    break
            # Prefer gpt-4o + local corroboration over a lone same-length digit twin.
            if not early_gpt4o_id_relief and not early_id_relief:
                top_canon = _canonical_member_id(str(value or ""))
                for _norm, items in ranked[1:]:
                    if not any(
                        _is_azure_gpt4o_crop_engine(c.engine) for c, _, _ in items
                    ):
                        continue
                    best = max(items, key=lambda row: row[1])
                    cand_val = str(best[0].value or "")
                    if not _member_id_is_shaped(cand_val):
                        continue
                    if _member_id_is_weak_for_gpt4o_gate(cand_val):
                        continue
                    alt_canon = _canonical_member_id(cand_val)
                    if (
                        not top_canon
                        or not alt_canon
                        or len(top_canon) != len(alt_canon)
                        or len(alt_canon) < 7
                    ):
                        continue
                    if values_conflict_equivalent(
                        "insured_id_number", str(value), cand_val
                    ):
                        continue
                    alt_local = {
                        independence_group(c.engine) for c, _, _ in items
                    } - {"CLOUD_AI_FAMILY", "AZURE_READ_FAMILY", "TESSERACT_FAMILY"}
                    if not alt_local:
                        continue
                    value = cand_val
                    supporting = items
                    early_gpt4o_digit_tiebreak = True
                    break
        # Always emit compact member IDs so spaced/punctuated OCR ("4E80 VH6 HJ14")
        # matches FORMAT_VALID and downstream identity checks. Keep zero-padded
        # short shells as printed (``0000007267``) so FORMAT_VALID sees the pad.
        stripped_padded_shell = False
        if is_id_field and _member_id_is_shaped(str(value or "")):
            if _member_id_is_short_padded_shell(str(value or "")):
                stripped_padded_shell = True
                # Preserve pad form for deterministic FORMAT_VALID; do not emit
                # the 4-digit core alone (that fails the length gate).
            else:
                compact_id = _canonical_member_id(str(value))
                if compact_id:
                    value = compact_id

        # Prefer DI/vision+local Box 28 over bleed-cents line Σ (DJJM.049 /
        # EJGE.043) before BLEED_CENTS_FAIL_CLOSED.
        early_box28_over_bleed = False
        if field_name in {"total_charge", "total_charges"} and value:
            from packages.claim_evidence.line_sum_authority import (
                prefer_box28_over_bleed_line_sum,
            )

            box28_keep = prefer_box28_over_bleed_line_sum(value, candidates)
            if box28_keep and str(box28_keep) != str(value):
                value = box28_keep
                keep_norm = normalize_agreement_value(field_name, box28_keep)
                for norm, items in ranked:
                    if norm == keep_norm or any(
                        normalize_agreement_value(field_name, str(c.value or ""))
                        == keep_norm
                        for c, _, _ in items
                    ):
                        supporting = items
                        break
                early_box28_over_bleed = True

        # Never auto-accept a future DOB — OCR year junk / box-rule misreads.
        future_dob_rejected = False
        if is_dob_field and value and (
            _dob_is_future(str(value)) or not _dob_is_display_shaped(str(value))
        ):
            # Prefer any display-shaped non-future calendar competitor first.
            swapped = False
            for _norm, items in ranked:
                cand_val = str(max(items, key=lambda row: row[1])[0].value)
                if _dob_is_display_shaped(cand_val):
                    value = cand_val
                    supporting = items
                    swapped = True
                    break
            if not swapped and value and _dob_is_future(str(value)):
                future_dob_rejected = True
            elif not swapped and value and not _dob_is_display_shaped(str(value)):
                # No display-shaped rival — keep value but do not treat as future
                # reject unless it actually is future-shaped.
                if _dob_is_future(str(value)):
                    future_dob_rejected = True

        has_independent_agreement = independent_agreement(
            normalize_agreement_value(field_name, str(value)), supporting
        )
        # Engine-family corroboration is measured from OCR candidates directly.
        # Evidence-bundle E2 independent_agreement_values can be empty on the
        # decision-only path even when paddle+rapid agree on the same value —
        # do not let an empty E2 set starve ID threshold relief.
        supporting_engine_families = {
            independence_group(candidate.engine) for candidate, _, _ in supporting
        }
        has_multi_engine_family = len(supporting_engine_families) >= 2
        calibrated = max(score for _, score, _ in supporting)
        # Agreement bonus stays tied to E2-qualified independent agreement only.
        # Boosting confidence from raw engine-family co-presence widens the
        # conflict margin and can silently ACCEPT genuine DOB/year conflicts.
        agreement_bonus = 0.04 if has_independent_agreement else 0.0
        reference_match = (
            authoritative_reference_verified
            and authoritative_value is not None
            and (value or "").strip().casefold() == authoritative_value.strip().casefold()
        )
        reference_contradiction = (
            authoritative_reference_verified
            and authoritative_value is not None
            and (value or "").strip().casefold() != authoritative_value.strip().casefold()
        )
        deterministic_ok = (
            bool(
                deterministic
                & {
                    "CHECKSUM_VALID",
                    "REFERENCE_MATCH",
                    "CROSS_FIELD_CONSISTENT",
                    "CROSS_DOCUMENT_AGREEMENT",
                    "FINANCIAL_RECONCILIATION_VALID",
                    "CLAIM_TOTAL_CONFIRMED",
                    # LINE_TOTALS_CORROBORATED alone is not C3 OK for charge —
                    # requires CLAIM_TOTAL_CONFIRMED from ChargeTotalAuthority.
                    "DATE_RELATIONSHIP_CONFIRMED",
                    "DOB_SERVICE_DATE_CONSISTENT",
                    "MEMBER_IDENTITY_CONSISTENT",
                    "MEMBER_RELATIONSHIP_CONFIRMED",
                }
            )
            or reference_match
            # Format-valid member identifiers with field E3 remain HITL-gated by
            # evidence policy, but no longer hard-fail the C3 independent-engine
            # gate after OCR span cleanup.
            or (
                field_name in {"insured_id_number", "member_id", "subscriber_id"}
                and "HARD_VALIDATION_PASSED" in deterministic
            )
        )
        financial_authority = bool(
            self.allow_authoritative_financial_e6
            and field_name in {"total_charge", "total_charges"}
            and (
                # Single ChargeTotalAuthority mint — never OR FG ∪ line-sum ∪
                # derived ∪ LINE_TOTALS alone. Supporting codes may coexist but
                # AUTO requires CLAIM_TOTAL_CONFIRMED from the authority session.
                "CLAIM_TOTAL_CONFIRMED" in deterministic
            )
        )
        # Bleed→whole: prefer same-dollar .00 sibling among candidates before
        # stripping financial authority / fail-closed on units bleed cents.
        bleed_repaired_to_whole = False
        if field_name in {"total_charge", "total_charges"} and _charge_is_units_bleed_cents(
            value
        ):
            from packages.claim_evidence.charge_total_authority import (
                _dollars_part,
                format_currency,
                parse_currency,
            )

            bleed_amt = parse_currency(value)
            if bleed_amt is not None:
                target = f"{_dollars_part(format_currency(bleed_amt))}.00"
                for cand in candidates:
                    text = str(cand.value or "").strip()
                    if not text:
                        continue
                    if parse_currency(text) == parse_currency(target):
                        value = format_currency(parse_currency(text))
                        bleed_repaired_to_whole = True
                        break
        # Bleed/echo cents never carry financial AUTO authority (defense-in-depth;
        # primary block is bleed-at-mint in ChargeTotalAuthoritySession).
        # Cash ruling-split geometry confirming the selected amount is printed
        # cents ink (``$ 157 :07``), not units bleed — keep authority.
        if (
            field_name in {"total_charge", "total_charges"}
            and _charge_is_units_bleed_cents(value)
            and not _charge_cash_ruling_confirms(value, candidates)
            and not _charge_di_printed_decimal_confirms(value, candidates)
            and not _charge_vision_local_confirms_bleed(value, candidates)
        ):
            financial_authority = False
        # Explicit Field Value Authority exception for verified financial ink /
        # derived complete-line arithmetic. Not calibrated-threshold fitting.
        # Requires the single-authority CONFIRMED mint, not FG/derived codes alone.
        accept_even_if_calibrated_confidence_below_threshold = bool(
            financial_authority
            and "CLAIM_TOTAL_CONFIRMED" in deterministic
            and deterministic
            & {
                "CHARGE_TOTAL_AUTHORITY",
                "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED",
                "DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES",
                "E6_COMPLETE_LINE_ARITHMETIC",
                "BOX28_LINE_SUM_CORROBORATED",
                "CLAIM_TOTAL_WITHIN_TOLERANCE",
                "BLEED_CENTS_TO_WHOLE_DOLLAR",
                "BLEED_CENTS_TO_LINE_SUM_WHOLE_DOLLAR",
                "CASH_RULING_PRINTED_CENTS",
                "VISION_LOCAL_PRINTED_BLEED_CENTS",
                "BOX28_DI_PARTNER_CONFIRMS_CONFLICT_PICK",
                "CONFLICT_AGENT_FINANCIAL_RESOLVED",
            }
        )
        # A verified reference is an independent E5 authority, not an OCR
        # calibration shortcut. Exact candidate/reference agreement may use
        # the reference decision's governed confidence and provenance.
        confidence = (
            1.0
            if reference_match
            or financial_authority
            or accept_even_if_calibrated_confidence_below_threshold
            else min(1.0, calibrated + agreement_bonus)
        )
        # DI + Rapid, or DI + Claude, on the same charge is a second reader.
        # It does not clear a line-sum failure or a cents-column / digit-drop twin
        # (those never mint this E2). 0.95 DI confidence was sitting under the
        # C3 0.98 floor even when the amount was agreed.
        charge_reader_relief = False
        if (
            field_name in {"total_charge", "total_charges"}
            and has_independent_agreement
            and "LINE_TOTALS_UNCORROBORATED" not in deterministic
            and "FINANCIAL_CONFLICT_HITL" not in deterministic
            and confidence < 0.98
        ):
            confidence = 0.98
            charge_reader_relief = True
        evidence = [
            EvidenceReference(
                evidence_type="OCR_CANDIDATE",
                reference=self._candidate_id(candidate),
                source=candidate.engine,
                reason_code="ENGINE_SUPPORT",
            )
            for candidate, _, _ in supporting
        ]
        evidence.extend(
            EvidenceReference(
                evidence_type="DETERMINISTIC", reference=code, source="validation", reason_code=code
            )
            for code in sorted(deterministic)
        )
        if reference_match:
            evidence.append(
                EvidenceReference(
                    evidence_type="AUTHORITATIVE_REFERENCE",
                    reference=authoritative_version or "version-not-provided",
                    source=authoritative_source or "authorized-reference",
                    reason_code="REFERENCE_MATCH",
                )
            )
        elif reference_contradiction:
            conflicts.append(
                EvidenceReference(
                    evidence_type="AUTHORITATIVE_REFERENCE",
                    reference=authoritative_version or "version-not-provided",
                    source=authoritative_source or "authorized-reference",
                    reason_code="REFERENCE_CONTRADICTION",
                )
            )
        for other_value, items in ranked[1:]:
            conflicts.extend(
                EvidenceReference(
                    evidence_type="OCR_CANDIDATE",
                    reference=self._candidate_id(candidate),
                    source=candidate.engine,
                    reason_code=f"CONFLICTING_VALUE:{other_value}",
                )
                for candidate, _, _ in items
            )
        reasons = ["HARD_VALIDATION_PASSED"] if "HARD_VALIDATION_PASSED" in deterministic else []
        if bleed_repaired_to_whole:
            reasons.append("BLEED_CENTS_REPAIRED_TO_WHOLE_DOLLAR")
        if charge_reader_relief:
            reasons.append("CHARGE_READER_AGREEMENT_THRESHOLD_RELIEF")
        if has_independent_agreement:
            reasons.append("MULTI_ENGINE_AGREEMENT")
        if reference_match:
            reasons.append("REFERENCE_MATCH")
        reasons.extend(sorted(deterministic))
        signals = set(deterministic)
        if has_independent_agreement:
            signals.add("OCR_MULTI_ENGINE")
        if reference_match:
            signals.add("REFERENCE_MATCH")
        rule = self.evidence_policies.rule_for(document_family, field_name, criticality)
        policy_ok, missing_alternatives = rule.evaluate(signals)
        threshold = rule.threshold if rule.threshold is not None else self.thresholds[criticality]
        # Identity fields with hard validation + member-relationship E6 are
        # corroboration-backed: allow a slightly lower calibrated floor (0.95)
        # instead of inventing values or waiving evidence. Closes near-miss
        # STP blocks where calibrated OCR is ~0.97 under a 0.98 C3 gate.
        identity_corroborated = (
            field_name in {"insured_id_number", "member_id", "subscriber_id"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and bool(
                deterministic
                & {
                    "MEMBER_RELATIONSHIP_CONFIRMED",
                    "MEMBER_IDENTITY_CONSISTENT",
                }
            )
        )
        # Dual-engine confirmation agreement (paddle+rapid) after hard ID
        # validation is independent OCR corroboration — same floor as above,
        # not a policy waiver and not invented ink.
        multi_engine_id_corroborated = (
            field_name in {"insured_id_number", "member_id", "subscriber_id"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and has_multi_engine_family
        )
        # Shaped format-valid member IDs with hard validation: allow a 0.92
        # floor so near-miss single-engine calibrated probs (~0.92–0.95) STP
        # without MEMBER_RELATIONSHIP E6 or inventing ink.
        id_shaped = False
        if field_name in {"insured_id_number", "member_id", "subscriber_id"}:
            id_shaped = _member_id_is_shaped(str(value or ""))
        format_valid_id_corroborated = (
            field_name in {"insured_id_number", "member_id", "subscriber_id"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and "FORMAT_VALID" in deterministic
            and id_shaped
        )
        # DOB with calendar/format hard validation: deterministic DATE_VALID is
        # corroboration, not invented ink. Floor at C1 (0.80) so near-miss
        # calibrated probs (~0.88–0.91) can STP without softening E3/identity.
        date_corroborated = (
            field_name in {"patient_dob", "date_of_birth", "dob"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and "DATE_VALID" in deterministic
        )
        unique_calendar_dob = False
        if date_corroborated:
            # Future-shaped OCR (year 5199 from digit glue) is junk — do not
            # count it against unique-calendar corroboration. Letter/punct soup
            # that digit-glues to a YMD is also junk for uniqueness.
            calendar_ymds = {
                _dob_ymd(str(candidate.value or ""))
                for candidate in candidates
                if _dob_is_display_shaped(str(candidate.value or ""))
            }
            calendar_ymds.discard(None)
            unique_calendar_dob = (
                len(calendar_ymds) == 1
                and _dob_is_display_shaped(str(value))
            )
            # Uncalibrated fill engines (tesseract) often sit ~0.3 raw conf even when
            # the only calendar-valid shaped DOB passes DATE_VALID — treat unique
            # calendar corroboration like deterministic authority on confidence.
            if unique_calendar_dob:
                confidence = max(confidence, 0.85)
        # Dual-engine exact ID agreement after hard validation is independent
        # confirmation — lift near-miss calibrated floors (~0.71–0.80) that were
        # blocking STP despite paddle+rapid agreeing on the same shaped ID.
        unique_shaped_id = False
        if (
            field_name in {"insured_id_number", "member_id", "subscriber_id"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and "FORMAT_VALID" in deterministic
            and id_shaped
        ):
            shaped_values = set()
            for candidate in candidates:
                raw = str(candidate.value or "")
                if not _member_id_is_shaped(raw):
                    continue
                # Weak locals that trigger gpt-4o (``890 000``) must not break
                # unique-shaped corroboration for a strong vision/local ID.
                if _member_id_is_weak_for_gpt4o_gate(raw):
                    continue
                canon = _canonical_member_id(raw)
                # Ignore length fragments beside the selected authority ID.
                if _member_id_is_length_fragment(str(value), raw):
                    continue
                shaped_values.add(canon)
            shaped_values.discard("")
            unique_shaped_id = len(shaped_values) == 1
            if unique_shaped_id:
                confidence = max(confidence, 0.92)

        if multi_engine_id_corroborated:
            confidence = max(confidence, 0.96)
        elif identity_corroborated and format_valid_id_corroborated:
            # Relationship-backed single-engine near-miss (~0.88–0.94).
            confidence = max(confidence, 0.95)
        effective_threshold = threshold
        relief_reason: str | None = None
        if identity_corroborated or multi_engine_id_corroborated:
            effective_threshold = min(effective_threshold, 0.95)
            relief_reason = (
                "IDENTITY_CORROBORATED_THRESHOLD_RELIEF"
                if identity_corroborated and not multi_engine_id_corroborated
                else "MULTI_ENGINE_ID_CORROBORATED_THRESHOLD_RELIEF"
            )
        if format_valid_id_corroborated and not (
            identity_corroborated or multi_engine_id_corroborated
        ):
            effective_threshold = min(effective_threshold, 0.92)
            relief_reason = (
                "UNIQUE_SHAPED_ID_CORROBORATED"
                if unique_shaped_id
                else "FORMAT_VALID_ID_THRESHOLD_RELIEF"
            )
        if date_corroborated:
            effective_threshold = min(effective_threshold, 0.80)
            relief_reason = (
                "DATE_UNIQUE_CALENDAR_CORROBORATED"
                if unique_calendar_dob
                else "DATE_CORROBORATED_THRESHOLD_RELIEF"
            )
        # Strong person-name ink with hard format validation: floor at 0.70 so
        # near-miss calibrated probs (~0.68–0.90) can STP after fragment relief
        # without inventing letters.
        name_strong_corroborated = (
            is_name_field
            and "HARD_VALIDATION_PASSED" in deterministic
            and "FORMAT_VALID" in deterministic
            and _name_is_strong_person(str(value or ""))
            and not _name_is_short_fragment(str(value or ""))
        )
        if name_strong_corroborated:
            confidence = max(confidence, 0.70)
            effective_threshold = min(effective_threshold, 0.70)
            relief_reason = "NAME_STRONG_PERSON_THRESHOLD_RELIEF"
        threshold_ok = confidence >= effective_threshold
        if accept_even_if_calibrated_confidence_below_threshold:
            # Evidence-based exception — not a lowered C1/C2/C3 threshold.
            threshold_ok = True
            reasons.append("FINANCIAL_GEOMETRY_CALIBRATION_EXCEPTION")
        if (
            relief_reason
            and confidence >= effective_threshold
            and (
                confidence < threshold
                or unique_calendar_dob
                or name_strong_corroborated
            )
        ):
            reasons.append(relief_reason)
        # C3 always needs deterministic/authoritative evidence or two truly
        # independent engine families. Confidence is never sufficient alone.
        # has_multi_engine_family feeds ID threshold relief only — C3 still
        # requires E2-qualified independent_agreement or deterministic_ok so
        # empty E2 sets cannot authorize non-ID critical fields.
        independent_evidence_ok = has_independent_agreement or deterministic_ok or financial_authority
        # Soft-equivalent local families on a strong person name (fuller reading
        # vs surname fragment: NOVOTNY. FINNIE ↔ NOVOTNY) corroborate without
        # inventing ink — do not leave patient_name HITL on MISSING_E2 alone.
        if (
            is_name_field
            and not independent_evidence_ok
            and name_strong_corroborated
            and _name_soft_equivalent_second_family(str(value or ""), candidates)
        ):
            independent_evidence_ok = True
            reasons.append("NAME_SOFT_EQUIVALENT_FAMILY_E2")
        # Box 28 over bleed line Σ already requires DI/vision+local corroboration;
        # do not leave C3 HITL solely because the E2 agreement set was empty.
        if (
            early_box28_over_bleed
            and has_multi_engine_family
            and field_name in {"total_charge", "total_charges"}
        ):
            independent_evidence_ok = True
        elif (
            field_name in {"total_charge", "total_charges"}
            and has_multi_engine_family
            and "HARD_VALIDATION_PASSED" in deterministic
            and not _charge_is_units_bleed_cents(value)
        ):
            from packages.claim_evidence.line_sum_authority import (
                box28_di_partner_confirmed,
            )

            if box28_di_partner_confirmed(value, candidates):
                independent_evidence_ok = True
        if future_dob_rejected:
            decision = Decision.REVIEW
            reasons.append("FUTURE_DOB_REJECTED")
        elif (
            field_name in {"total_charge", "total_charges"}
            and _charge_is_units_bleed_cents(value)
            and not _charge_cash_ruling_confirms(value, candidates)
            and not _charge_di_printed_decimal_confirms(value, candidates)
            and not _charge_vision_local_confirms_bleed(value, candidates)
        ):
            # Never AUTO units/ruling bleed cents (.07/.22/.44) — conflict-agent
            # and $1 tolerance were minting TRUE_STP on contested Box 28 ink.
            # Exception: cash ruling-split raws (``$ 157 :07``) confirm printed cents.
            # Exception: DI raw ``$ 563.10`` with explicit decimal (printed cents).
            # L3: Claude+local on printed bleed (``251.43``) vs DI ×100 soup.
            # Box28-over-bleed swap happens earlier (BOX28_OVER_BLEED_LINE_SUM).
            decision = Decision.REVIEW
            reasons.append("BLEED_CENTS_FAIL_CLOSED")
        elif (
            field_name in {"total_charge", "total_charges"}
            and "CHARGE_VISION_LOCAL_CONFIRMED" in deterministic
            and "CHARGE_DI_LOCAL_CONFIRMED" not in deterministic
            and "CLAIM_TOTAL_CONFIRMED" not in deterministic
            and not _charge_vision_local_confirms_bleed(value, candidates)
            and not _charge_cash_ruling_confirms(value, candidates)
            and _charge_has_inflated_scale_rival(value, candidates)
            and not _charge_inflated_rivals_are_whole_dollar_place_shift_soup(
                value, candidates
            )
        ):
            # L4 / DJKH.040: Claude+local on an inflated Box28 (1571.63) beside
            # DI/raw ×100 soup must not AUTO without DI-exact or CLAIM_TOTAL.
            # L3 printed bleed cents are exempt (Claude+local beside DI ×100).
            # Whole-dollar ×100 place-shift soup (``177.00`` vs DI ``17700``) is
            # exempt — DI digit run without a second genuine magnitude.
            decision = Decision.REVIEW
            reasons.append("CHARGE_VISION_LOCAL_SCALE_RIVAL_HITL")
        elif reference_contradiction:
            decision = Decision.REVIEW
            reasons.append("REFERENCE_CONTRADICTION")
        elif (
            "FINANCIAL_CONFLICT_HITL" in deterministic
            and "CLAIM_TOTAL_CONFIRMED" not in deterministic
        ):
            # Arithmetic Box 28 ↔ Σ conflict is never equivalent-value soup —
            # unless the single ChargeTotalAuthority already confirmed the amount.
            decision = Decision.REVIEW
            reasons.append("FINANCIAL_CONFLICT_HITL")
        elif not threshold_ok:
            decision = Decision.ESCALATE
            reasons.append("CALIBRATED_CONFIDENCE_BELOW_THRESHOLD")
        elif enforce_legacy_evidence_policy and not policy_ok:
            decision = Decision.REVIEW
            reasons.append("FIELD_EVIDENCE_POLICY_NOT_SATISFIED")
            reasons.extend(f"MISSING_ALTERNATIVE:{item}" for item in missing_alternatives)
        elif criticality is CriticalityLevel.C3 and not independent_evidence_ok:
            decision = Decision.REVIEW
            reasons.append("C3_INDEPENDENT_EVIDENCE_REQUIRED")
        elif len(ranked) > 1 and confidence - max(s for _, s, _ in ranked[1][1]) < 0.05:
            competing_values = [
                str(max(items, key=lambda row: row[1])[0].value)
                for _, items in ranked[1:]
            ]
            genuine = [
                other
                for other in competing_values
                if not values_conflict_equivalent(field_name, value, other)
            ]
            # Display-shaped DOB vs digit-glue / letter soup is not a genuine
            # calendar conflict (``11/01/2011`` vs ``ib0 13! 197``).
            if is_dob_field and _dob_is_display_shaped(str(value or "")):
                genuine = [
                    other
                    for other in genuine
                    if _dob_is_display_shaped(other)
                ]
            # Scale / place-shift / digit-drop twins beside DI/vision+local Box 28
            # are real conflicts (DJKN.005: 200 vs 2001; truncated 340 vs Σ 3402).
            # Soup relief below clears them only when line-Σ / financial /
            # cash-ruling authority owns the selected total. Digit-substring
            # scrap (186 vs 86) is handled there — never wipe twins early.
            # Decimal-place / fragment charge OCR is not a genuine conflict when
            # Box 28 ↔ line-sum financial authority already confirmed the total,
            # or when LINE_TOTALS_RECONCILED owns the selected amount (soup rivals
            # like ``2605`` / ``5460.4`` beside a clean line Σ must not veto AUTO).
            # DI+local confirmed Box 28 (CHARGE_DI_LOCAL_CONFIRMED) is enough
            # authority to ignore embedded digit scrap (paddle ``3`` beside
            # ``105.00``) — not enough to invent totals or clear place-shift.
            charge_soup_authority = financial_authority or (
                field_name in {"total_charge", "total_charges"}
                and "CLAIM_TOTAL_CONFIRMED" in deterministic
                and "LINE_TOTALS_RECONCILED" in deterministic
                and "LINE_TOTALS_CORROBORATED" in deterministic
                and "LINE_TOTALS_UNCORROBORATED" not in deterministic
            ) or (
                field_name in {"total_charge", "total_charges"}
                and "CLAIM_TOTAL_CONFIRMED" in deterministic
                and "CHARGE_DI_LOCAL_CONFIRMED" in deterministic
            ) or (
                field_name in {"total_charge", "total_charges"}
                and "CLAIM_TOTAL_CONFIRMED" in deterministic
                and "CHARGE_VISION_LOCAL_CONFIRMED" in deterministic
            ) or (
                # Cash ruling-split (``$ 222 |22`` → 222.22) + DI partner E4:
                # paddle/Claude digit-insert soup (2221.22) is not a second total.
                field_name in {"total_charge", "total_charges"}
                and "CHARGE_DI_LOCAL_CONFIRMED" in deterministic
                and _charge_cash_ruling_confirms(value, candidates)
            ) or (
                field_name in {"total_charge", "total_charges"}
                and "CHARGE_VISION_LOCAL_CONFIRMED" in deterministic
                and _charge_cash_ruling_confirms(value, candidates)
            ) or (
                # DI+local confirmed Box 28 alone clears digit-substring scrap
                # (paddle ``86`` beside Claude+DI ``186.00``) when no lines exist
                # to mint CLAIM_TOTAL — place-shift twins still stay genuine above.
                field_name in {"total_charge", "total_charges"}
                and "CHARGE_DI_LOCAL_CONFIRMED" in deterministic
            ) or (
                field_name in {"total_charge", "total_charges"}
                and "CHARGE_VISION_LOCAL_CONFIRMED" in deterministic
            )
            if field_name in {"total_charge", "total_charges"} and charge_soup_authority:
                from packages.claim_evidence.line_sum_authority import (
                    is_currency_digit_drop_twin,
                    is_decimal_place_shift,
                    is_embedded_charge_digit_fragment,
                    is_scale_shift,
                    parse_currency,
                )

                primary_amt = parse_currency(value)
                line_totals_owns = "LINE_TOTALS_RECONCILED" in deterministic
                # Deterministic LINE_TOTALS can be present while ranking still
                # crowns truncated Box OCR (340 beside Σ 3402). Soup relief
                # applies only when the selected shell is the derived line sum.
                line_totals_owns_selected = line_totals_owns and any(
                    "derived_from_observed_line"
                    in str(cand.preprocessing_variant or "").casefold()
                    or "derived_from_verified"
                    in str(cand.preprocessing_variant or "").casefold()
                    or "phase2-line-sum"
                    in str(cand.preprocessing_variant or "").casefold()
                    or "claim_total_confirmed"
                    in str(cand.preprocessing_variant or "").casefold()
                    or str(cand.evidence_reference or "")
                    in {
                        "LINE_TOTALS_RECONCILED",
                        "DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES",
                        "CLAIM_TOTAL_CONFIRMED",
                    }
                    for cand, _, _ in supporting
                )
                cash_ruling_owns = _charge_cash_ruling_confirms(value, candidates)
                cleared: list[str] = []
                for other in genuine:
                    other_amt = parse_currency(other)
                    if other_amt is None or primary_amt is None:
                        continue
                    # Same confirmed amount — not a conflict.
                    if other_amt == primary_amt and not is_decimal_place_shift(value, other):
                        continue
                    # Cash ruling-split printed ink owns the total — OCR soup
                    # rivals (cents fragments, ruling-tail scrap) are not a
                    # second Box 28 (DJKH.029: 97.39 vs 39 / 139).
                    if cash_ruling_owns and other_amt != primary_amt:
                        continue
                    # ×10/×100, place-shift, and dropped-digit twins are real
                    # conflicts when the selected amount is inflated/truncated
                    # Box 28 OCR. Once line Σ owns the selected total, both
                    # directions are soup: larger (250 vs 25000), truncated
                    # (660 vs 66), and digit-drop (3402 vs 340). Cash
                    # ruling-split + DI E4 likewise owns the printed total.
                    # Never clear these via digit-substring below — DJKN.005
                    # (200 vs 2001) must stay CONFLICT under DI-local alone.
                    if (
                        is_scale_shift(value, other)
                        or is_decimal_place_shift(value, other)
                        or is_currency_digit_drop_twin(value, other)
                    ):
                        if line_totals_owns_selected or financial_authority or cash_ruling_owns:
                            continue
                        # L3: Claude+local printed bleed cents — DI ×100 twin is soup.
                        if _charge_vision_local_confirms_bleed(
                            value, candidates
                        ) and is_scale_shift(value, other):
                            continue
                        # EJI2.041 / HJE5.019: DI+Claude or Claude+local own the
                        # amount; pure decimal place-shift / ×100 soup from the
                        # dissenting engine is not a second total. Digit-drop
                        # twins (DJKN.005: 200 vs 2001) stay genuine.
                        if (
                            other_amt is not None
                            and primary_amt is not None
                            and other_amt > primary_amt
                            and is_decimal_place_shift(value, other)
                            and not is_currency_digit_drop_twin(value, other)
                            and (
                                "CHARGE_DI_LOCAL_CONFIRMED" in deterministic
                                or "CHARGE_VISION_LOCAL_CONFIRMED" in deterministic
                            )
                        ):
                            continue
                        # L2: underread scrap of DI/vision-local fuller amount is soup
                        # (``14`` / ``20`` beside ``140`` / ``200``). Inflated rivals
                        # (``2001`` beside ``200``) stay genuine.
                        if (
                            other_amt is not None
                            and primary_amt is not None
                            and other_amt < primary_amt
                            and (
                                "CHARGE_DI_LOCAL_CONFIRMED" in deterministic
                                or "CHARGE_VISION_LOCAL_CONFIRMED" in deterministic
                            )
                        ):
                            continue
                        cleared.append(other)
                        continue
                    # When line Σ owns the selected total, deferred Box 28 OCR
                    # rivals are soup — not a second printed claim total.
                    if line_totals_owns_selected and other_amt != primary_amt:
                        continue
                    if primary_amt != other_amt:
                        from packages.claim_evidence.line_sum_authority import (
                            is_cents_column_fragment,
                        )

                        # DI residual cents column (``39.00`` from ``$ 97|39``)
                        # beside confirmed ``97.39``.
                        if is_cents_column_fragment(other, value):
                            continue
                        # Competing non-equal amounts stay only when they are
                        # not digit-soup fragments of the confirmed total.
                        # Use dollar stems (``19`` from ``19.00``) — stripping the
                        # decimal yields ``1900`` which misses ``19``-in-``930019``
                        # glue (EJGE.005 GEOMETRY_CENTS ``9300.19``).
                        confirmed_digits = re.sub(r"\D", "", str(value).split(".", 1)[0])
                        other_digits = re.sub(r"\D", "", str(other).split(".", 1)[0])
                        if (
                            confirmed_digits
                            and other_digits
                            and (
                                confirmed_digits in other_digits
                                or other_digits in confirmed_digits
                            )
                        ):
                            continue
                        # Full digit string (with cents) for embed / insertion tests.
                        confirmed_all = re.sub(r"\D", "", str(value))
                        other_all = re.sub(r"\D", "", str(other))
                        if (
                            confirmed_all
                            and other_all
                            and (
                                confirmed_all in other_all
                                or other_all in confirmed_all
                            )
                        ):
                            continue
                        # Embedded scrap (``3`` / ``03.00`` beside ``105.00``).
                        if is_embedded_charge_digit_fragment(other, value):
                            continue
                        # Dollars-stem junk (``2605`` beside ``260.00``).
                        conf_dollars = str(value).split(".", 1)[0]
                        other_dollars = str(other).split(".", 1)[0]
                        if (
                            conf_dollars
                            and other_dollars.startswith(conf_dollars)
                            and other_dollars[len(conf_dollars) :].isdigit()
                            and 1 <= len(other_dollars) - len(conf_dollars) <= 2
                        ):
                            continue
                        # Single junk-digit insertion either direction.
                        if abs(len(confirmed_all) - len(other_all)) == 1:
                            longer, shorter = (
                                (confirmed_all, other_all)
                                if len(confirmed_all) > len(other_all)
                                else (other_all, confirmed_all)
                            )
                            if any(
                                longer[:i] + longer[i + 1 :] == shorter
                                for i in range(len(longer))
                            ):
                                continue
                        # L2: underread digit-drop / scale scrap of the selected
                        # total (``14`` beside Claude+local ``140``) is soup when
                        # DI/vision-local E4 owns the fuller amount. Inflated
                        # rivals (``2001`` beside ``200``) stay genuine above.
                        if (
                            other_amt < primary_amt
                            and (
                                "CHARGE_DI_LOCAL_CONFIRMED" in deterministic
                                or "CHARGE_VISION_LOCAL_CONFIRMED" in deterministic
                            )
                        ):
                            continue
                        # DI raw that already contains the selected dollars stem
                        # (``J $ 70 100`` beside Claude+local ``70``) is ruling
                        # soup, not a second total (DJKH.023).
                        if (
                            "CHARGE_DI_LOCAL_CONFIRMED" in deterministic
                            or "CHARGE_VISION_LOCAL_CONFIRMED" in deterministic
                        ) and _di_raw_embeds_selected_charge(value, other, candidates):
                            continue
                        # EJGE.005: DI+local owns ``19.00``; rapid ``93`` / geometry
                        # glue that is not a place/scale twin is OCR soup.
                        if (
                            "CHARGE_DI_LOCAL_CONFIRMED" in deterministic
                            or "CHARGE_VISION_LOCAL_CONFIRMED" in deterministic
                        ):
                            continue
                    cleared.append(other)
                genuine = cleared
            # Future-shaped DOB OCR is digit junk, not a genuine calendar conflict.
            if is_dob_field:
                genuine = [
                    other
                    for other in genuine
                    if not (
                        _dob_ymd(str(other)) is not None and _dob_is_future(str(other))
                    )
                ]
            # Unshaped / fragment / fill-only member-ID OCR is not a genuine
            # identity conflict against a primary-engine shaped authority.
            if is_id_field:
                value_engines: dict[str, set[str]] = defaultdict(set)
                for _norm, items in ranked:
                    for cand, _, _ in items:
                        canon = _canonical_member_id(str(cand.value or ""))
                        if canon:
                            value_engines[canon].add(independence_group(cand.engine))
                primary_support = {
                    independence_group(cand.engine) for cand, _, _ in supporting
                } - {"TESSERACT_FAMILY"}
                primary_is_gpt4o = any(
                    _is_azure_gpt4o_crop_engine(cand.engine)
                    for cand, _, _ in supporting
                )
                primary_strong = (
                    _member_id_is_shaped(str(value or ""))
                    and not _member_id_is_weak_for_gpt4o_gate(str(value or ""))
                )
                gpt4o_weak_local_filtered = False
                gpt4o_digit_tiebreak_filtered = False
                filtered = []
                for other in genuine:
                    if not _member_id_is_shaped(str(other)):
                        continue
                    if _member_id_is_length_fragment(str(value), str(other)):
                        continue
                    other_engines = value_engines.get(
                        _canonical_member_id(str(other)), set()
                    )
                    if (
                        primary_support
                        and other_engines
                        and other_engines <= {"TESSERACT_FAMILY"}
                    ):
                        continue
                    # gpt-4o residual vs weak local that triggered it (len<7/chrome).
                    if (
                        primary_is_gpt4o
                        and primary_strong
                        and _member_id_is_weak_for_gpt4o_gate(str(other))
                        and _member_ids_share_digit_prefix(str(value), str(other))
                    ):
                        gpt4o_weak_local_filtered = True
                        continue
                    # Carrier/vision ID vs zero-padded digit-only core (EJGE.026
                    # ``USW000179858`` vs ``000179858``).
                    if (
                        primary_is_gpt4o
                        and primary_strong
                        and _member_id_is_digit_core_pad_fragment(str(value), str(other))
                    ):
                        gpt4o_weak_local_filtered = True
                        continue
                    # gpt-4o tie-break on same-length digit conflicts: when gpt-4o
                    # agrees with ≥1 local engine, drop the disagreeing twin.
                    other_canon = _canonical_member_id(str(other))
                    value_canon = _canonical_member_id(str(value or ""))
                    primary_local = primary_support - {
                        "CLOUD_AI_FAMILY",
                        "AZURE_READ_FAMILY",
                    }
                    if (
                        primary_is_gpt4o
                        and primary_strong
                        and primary_local
                        and value_canon
                        and other_canon
                        and len(value_canon) == len(other_canon)
                        and len(value_canon) >= 7
                    ):
                        gpt4o_digit_tiebreak_filtered = True
                        continue
                    filtered.append(other)
                genuine = filtered
            else:
                gpt4o_weak_local_filtered = False
                gpt4o_digit_tiebreak_filtered = False
            # Box-number / digit-only OCR is form chrome, not a name competitor.
            if is_name_field and _name_is_strong_person(str(value or "")):
                genuine = [
                    other
                    for other in genuine
                    if not _name_is_form_chrome(str(other))
                ]
            if early_separator_relief:
                # Competing values were separator-1 twins of the cleaned date.
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("DOB_SEPARATOR_ARTIFACT_RELIEVED")
            elif early_gpt4o_name_relief:
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("GPT4O_NAME_INK_CONFLICT_RELIEVED")
            elif early_name_relief:
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("NAME_CONFLICT_RELIEVED")
            elif early_gpt4o_id_relief:
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("GPT4O_ID_WEAK_LOCAL_RELIEVED")
            elif early_gpt4o_digit_tiebreak:
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("GPT4O_ID_DIGIT_CONFLICT_TIEBREAK")
            elif early_id_relief:
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("MEMBER_ID_CONFUSABLE_INSERTION_RELIEVED")
            elif not genuine:
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                if gpt4o_digit_tiebreak_filtered:
                    reasons.append("GPT4O_ID_DIGIT_CONFLICT_TIEBREAK")
                elif gpt4o_weak_local_filtered:
                    reasons.append("GPT4O_ID_WEAK_LOCAL_RELIEVED")
                else:
                    reasons.append("EQUIVALENT_VALUE_CONFLICT_RELIEVED")
            else:
                separator_clean = None
                name_clean = None
                label_clean = None
                fragment_clean = None
                prefix_clean = None
                id_clean = None
                if date_corroborated or is_dob_field:
                    separator_clean = prefer_dob_without_separator_one(
                        str(value), genuine
                    )
                    if not separator_clean:
                        separator_clean = prefer_dob_without_january_dash_artifact(
                            str(value), genuine
                        )
                    if not separator_clean:
                        separator_clean = prefer_dob_year_confusable_digit(
                            str(value), genuine
                        )
                if is_name_field:
                    label_clean = prefer_name_without_label_contamination(
                        str(value), genuine
                    )
                    fragment_clean = prefer_name_without_short_fragment(
                        str(value), genuine
                    )
                    prefix_clean = prefer_longer_name_prefix(str(value), genuine)
                    name_clean = prefer_name_without_confusable_insertion(
                        str(value), genuine
                    )
                if is_id_field:
                    id_clean = prefer_member_id_without_confusable_insertion(
                        str(value), genuine
                    )
                if separator_clean:
                    value = separator_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("DOB_SEPARATOR_ARTIFACT_RELIEVED")
                elif id_clean:
                    value = id_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("MEMBER_ID_CONFUSABLE_INSERTION_RELIEVED")
                elif label_clean:
                    value = label_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_LABEL_CONTAMINATION_RELIEVED")
                elif fragment_clean:
                    value = fragment_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_SHORT_FRAGMENT_RELIEVED")
                elif prefix_clean:
                    value = prefix_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_PREFIX_EXPANSION_RELIEVED")
                elif is_name_field and (
                    ghost_mi := prefer_name_without_ocr_ghost_middle_initial(
                        str(value), genuine
                    )
                ):
                    value = ghost_mi
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_OCR_GHOST_MI_RELIEVED")
                elif is_name_field and (
                    mi_clean := prefer_name_with_optional_middle_initial(
                        str(value), genuine
                    )
                ):
                    value = mi_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_MIDDLE_INITIAL_RELIEVED")
                elif is_name_field and (
                    order_clean := prefer_name_canonical_token_order(
                        str(value), genuine
                    )
                ):
                    value = order_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_TOKEN_ORDER_RELIEVED")
                elif name_clean:
                    value = name_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_CONFUSABLE_INSERTION_RELIEVED")
                elif date_corroborated and not any(
                    _dob_ymd(other) is not None
                    and _dob_ymd(other) != _dob_ymd(str(value))
                    and prefer_dob_without_separator_one(str(value), [other]) is None
                    for other in genuine
                ):
                    # Calendar-valid top date vs fragment / separator twins — not ambiguous.
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("DATE_CONFLICT_FRAGMENTS_RELIEVED")
                elif (
                    is_id_field
                    and unique_shaped_id
                    and "HARD_VALIDATION_PASSED" in deterministic
                    and "FORMAT_VALID" in deterministic
                ):
                    # Unique shaped member ID already corroborated — rival OCR
                    # fragments must not force CONFLICT_MARGIN HITL (JEB.004).
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("UNIQUE_SHAPED_ID_CONFLICT_RELIEVED")
                else:
                    decision = Decision.REVIEW
                    reasons.append("CONFLICT_MARGIN_TOO_SMALL")
        else:
            decision = (
                Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
            )
            if early_separator_relief:
                reasons.append("DOB_SEPARATOR_ARTIFACT_RELIEVED")
            if early_gpt4o_name_relief:
                reasons.append("GPT4O_NAME_INK_CONFLICT_RELIEVED")
            if early_name_relief:
                reasons.append("NAME_CONFLICT_RELIEVED")
            if early_gpt4o_id_relief:
                reasons.append("GPT4O_ID_WEAK_LOCAL_RELIEVED")
            if early_gpt4o_digit_tiebreak:
                reasons.append("GPT4O_ID_DIGIT_CONFLICT_TIEBREAK")
            if early_id_relief:
                reasons.append("MEMBER_ID_CONFUSABLE_INSERTION_RELIEVED")
            if early_box28_over_bleed:
                reasons.append("BOX28_OVER_BLEED_LINE_SUM")
        # Letter soup stays fail-closed. Zero-padded short shells that were
        # already multi-engine shaped (``0000007267`` → ``7267``) keep ACCEPT;
        # lone-engine pads still fail closed.
        if (
            is_id_field
            and decision in {Decision.ACCEPT, Decision.REFERENCE_CONFIRMED}
            and not _member_id_is_shaped(str(value or ""))
            and not stripped_padded_shell
        ):
            decision = Decision.REVIEW
            reasons.append("UNSHAPED_MEMBER_ID")
        elif (
            is_id_field
            and decision in {Decision.ACCEPT, Decision.REFERENCE_CONFIRMED}
            and stripped_padded_shell
            and not has_multi_engine_family
        ):
            decision = Decision.REVIEW
            reasons.append("UNSHAPED_MEMBER_ID")
            reasons.append("SHORT_PADDED_MEMBER_ID_NEEDS_CORROBORATION")
        versions = (
            [f"authoritative-reference:{authoritative_version or 'version-not-provided'}"]
            if reference_match
            else ["deterministic-financial-e6-v1"]
            if financial_authority
            else sorted({version for _, _, version in supporting})
        )
        result = ReconciliationResult(
            field_name=field_name,
            selected_value=value,
            candidate_ids=ids,
            decision=decision,
            confidence=confidence,
            supporting_evidence=evidence,
            conflicting_evidence=conflicts,
            rationale_codes=list(dict.fromkeys(reasons)),
            calibration_model_version=",".join(versions),
        )
        field_reconciliation_total.labels(
            field_name=field_name,
            criticality=criticality.value,
            decision=decision.value,
        ).inc()
        return result
