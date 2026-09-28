"""When box-28 OCR is empty, invalid, or strongly contradicts observed lines,
prefer LINE_TOTALS_RECONCILED from service-line ink (never invent amounts).

AUTO on line-sum is fail-closed. GPT-4o never independently promotes a critical
charge field. Eligible paths:

  - every charge line has independent gpt-4o + usable local consensus;
  - multi-line (≥2) exact dual-engine (paddle+rapid) agreement;
  - service-line sum corroborated by independently extracted box-28 / DI
    (``amounts_corroborate`` — exact monetary equality).

Single-line paddle+rapid alone remains insufficient. Never invent Box 28 from Σ.

Shell / form-noise locals are not corroboration. Shared crop, parent evidence,
or independence_group lineage means candidates are not independent → HITL.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_CHARGE_FIELDS = ("total_charge", "total_charges", "charges", "charge_amount")
_INDEPENDENT_ENGINES = frozenset({"paddleocr", "rapidocr", "azure_document_intelligence_read"})
_LOCAL_ENGINES = frozenset({"paddleocr", "rapidocr"})
_GPT4O_FAMILY = "azure_gpt4o_crop"
# CMS-1500 box-28 digit-soup / form-ruling OCR (208408, 420840) is not a total.
_MAX_PLAUSIBLE_CLAIM_TOTAL = Decimal("99999.99")


def parse_currency(value: object) -> Decimal | None:
    raw = "" if value is None else str(value).strip()
    if not raw:
        return None
    # OCR often emits space/colon as the dollars|cents separator, or a
    # thousands space (``4 972``). Repair before stripping non-digits.
    text = raw.removeprefix("$").strip()
    if "," in text:
        if not re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?", text):
            return None
        text = text.replace(",", "")
    m = re.fullmatch(r"(\d{1,6})[\s:.](\d{2})", text)
    if m:
        text = f"{m.group(1)}.{m.group(2)}"
    else:
        m = re.fullmatch(r"(\d{1,3})\s(\d{3})", text)
        if m:
            text = f"{m.group(1)}{m.group(2)}.00"
        else:
            m = re.fullmatch(r"(\d{1,3})\s(\d{3})[\s:.](\d{2})", text)
            if m:
                text = f"{m.group(1)}{m.group(2)}.{m.group(3)}"
    # Parsing cannot repair character identity or concatenate unrelated tokens.
    # Such repairs belong to the recognizer with explicit source provenance.
    if not re.fullmatch(r"-?\d+(?:\.\d{1,2})?", text):
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def format_currency(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01")), "f")


def _hydrate_line_charge_from_candidates(line: dict) -> Decimal | None:
    """Fill charges/charge_amount from a unique candidate amount when keys null."""
    for key in _CHARGE_FIELDS:
        parsed = parse_currency(line.get(key))
        if parsed is not None and parsed >= 0:
            return parsed
    cand_vals: list[Decimal] = []
    for cand in line.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        shaped = parse_currency(cand.get("value") or cand.get("raw_value"))
        if shaped is not None and shaped >= 0:
            cand_vals.append(shaped)
    parsed = None
    if len(set(cand_vals)) == 1:
        parsed = cand_vals[0]
    elif line.get("raw_charges") is not None:
        parsed = parse_currency(line.get("raw_charges"))
    if parsed is None or parsed < 0:
        return None
    text = format_currency(parsed)
    line["charges"] = text
    line["charge_amount"] = text
    if line.get("raw_charges") in (None, ""):
        line["raw_charges"] = text
    return parsed


def hydrate_service_line_charges(service_lines: list[dict] | None) -> list[dict]:
    """In-place hydrate null charge keys from unique candidate ink."""
    out: list[dict] = []
    for line in service_lines or []:
        if isinstance(line, dict):
            _hydrate_line_charge_from_candidates(line)
            out.append(line)
    return out


def observed_line_charges(service_lines: list[dict] | None) -> list[Decimal]:
    charges: list[Decimal] = []
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        parsed = _hydrate_line_charge_from_candidates(line)
        if parsed is not None and parsed >= 0:
            charges.append(parsed)
    return charges


def is_suspicious_tiny_total(amount: Decimal) -> bool:
    """Match field-cascade CURRENCY_SUSPICIOUS_TINY (single digit before cents)."""
    text = format_currency(amount)
    return bool(re.fullmatch(r"[0-9]\.\d{2}", text))


def _currency_digit_string(amount: object) -> str:
    text = str(amount or "").strip().lstrip("$").replace(",", "")
    if not text:
        return ""
    if "." in text:
        text = text.split(".", 1)[0]
    return re.sub(r"\D", "", text)


def is_implausible_charge_total(amount: object) -> bool:
    """True for form-ruling digit soup / impossible CMS-1500 claim totals."""
    parsed = parse_currency(amount)
    if parsed is None:
        return False
    if parsed > _MAX_PLAUSIBLE_CLAIM_TOTAL:
        return True
    # Six+ digit dollars without cents separators are almost always ROI bleed.
    digits = _currency_digit_string(amount)
    return len(digits) >= 6 and parsed >= Decimal(100000)


def is_cents_column_fragment(fragment: object, fuller: object) -> bool:
    """True when ``fragment`` is only the cents column of ``fuller``.

    Azure DI residual ``39.00`` from raw ``$ 97|39`` beside line-sum / Claude
    ``97.39`` is not a second Box 28 total. Whole-dollar fullers (``.00``) never
    match — that keeps real near-miss totals (40.00 vs 97.00) as conflicts.
    """
    frag = parse_currency(fragment)
    full = parse_currency(fuller)
    if frag is None or full is None or frag <= 0 or full <= frag:
        return False
    cents = int((full * 100) % 100)
    if cents == 0:
        return False
    return frag == Decimal(cents)


def is_embedded_charge_digit_fragment(fragment: object, fuller: object) -> bool:
    """True when ``fragment`` is trivial single-digit OCR scrap beside ``fuller``.

    Paddle ``3`` / ``03.00`` beside DI+Claude ``105.00`` is ROI scrap, not a
    second Box 28 total. Place-shift / digit-drop twins are excluded so
    ``200`` vs ``2001`` stays a real conflict.
    """
    frag = parse_currency(fragment)
    full = parse_currency(fuller)
    if frag is None or full is None or frag <= 0 or full <= frag:
        return False
    if is_decimal_place_shift(fragment, fuller) or is_scale_shift(fragment, fuller):
        return False
    if is_currency_digit_drop_twin(fragment, fuller):
        return False
    frag_d = (_currency_digit_string(fragment) or "").lstrip("0") or "0"
    full_d = (_currency_digit_string(fuller) or "").lstrip("0") or "0"
    # One significant digit vs a multi-digit claim total (≥$100).
    return len(frag_d) == 1 and len(full_d) >= 3 and full >= Decimal(100)


def is_implausible_corroborator(value: object, line_total: object) -> bool:
    """Ignore box-28 junk that would force BOX28_OR_DI_CONFLICT vs real line-sum."""
    if is_implausible_charge_total(value):
        return True
    amount = parse_currency(value)
    total = parse_currency(line_total)
    if amount is None or total is None or total <= 0:
        return False
    # DI cents-column split of the line total is not a rival charge.
    if is_cents_column_fragment(value, line_total):
        return True
    # Near ×10 / ×100 place-shift rivals (1571.07 vs 157.00) must CONFLICT —
    # never ignore them as ratio junk or SINGLE_LINE_GPT4O_LOCAL false-accepts.
    for factor in (Decimal(10), Decimal(100)):
        if abs(amount - total * factor) <= Decimal("2.00"):
            return False
        if abs(total - amount * factor) <= Decimal("2.00"):
            return False
    # >3× or <1/3 the observed line-sum and off by >$50 → form noise / truncated cell.
    ratio_hi = total * Decimal(3)
    ratio_lo = total / Decimal(3)
    if amount > ratio_hi and abs(amount - total) > Decimal(50):
        return True
    return bool(amount < ratio_lo and abs(amount - total) > Decimal(50))


def selected_digit_drop_fuller_line_total(
    service_lines: list[dict] | None,
) -> str | None:
    """Return Σ when every charge line is SELECTED via DIGIT_DROP_FULLER_LOCAL.

    DJKN.004/007: Rapid GEOMETRY_CENTS ``2001`` beats Claude ``200`` on the line
    cell. That fuller Σ is the claim total when Box 28 only shows the truncated
    twin — not a second competing amount.
    """
    saw = False
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        if not any(parse_currency(line.get(k)) is not None for k in _CHARGE_FIELDS):
            continue
        selection = line.get("line_charge_selection") or {}
        if selection.get("disposition") != "SELECTED_LOCAL_CHARGE":
            return None
        if selection.get("reason") not in {
            "DIGIT_DROP_FULLER_LOCAL",
            "MULTI_LINE_GEOMETRY_DIGIT_DROP",
        }:
            return None
        saw = True
    if not saw:
        return None
    return line_sum_total(service_lines)


def box28_digit_drop_underread_of_fuller_line(
    box28_value: object, service_lines: list[dict] | None
) -> bool:
    """True when Box 28 is a shorter digit-drop twin of DIGIT_DROP_FULLER Σ.

    DJKN.005 GT ``2001`` vs DI/Claude Box 28 ``200``: the printed Box 28 under-read
    must defer to the fuller selected line, not AUTO the truncated twin.
    """
    fuller = selected_digit_drop_fuller_line_total(service_lines)
    if fuller is None:
        return False
    box = parse_currency(box28_value)
    full = parse_currency(fuller)
    if box is None or full is None or box >= full:
        return False
    return is_currency_digit_drop_twin(box28_value, fuller)


def _is_extension_of_digit_drop_underread_stem(value: object, fuller: object) -> bool:
    """True when ``value`` extends a 1–2 digit under-read stem of ``fuller``.

    DJKN.004: after Box 28 ``200`` is deferred, paddle whitelist ``2004`` remains
    as a corroborator. It is a ×10 / digit-drop extension of stem ``200``, not a
    rival of DIGIT_DROP_FULLER Σ ``2001``.
    """
    full_amt = parse_currency(fuller)
    val_amt = parse_currency(value)
    if full_amt is None or val_amt is None or val_amt == full_amt:
        return False
    full_digits = _currency_digit_string(fuller)
    if len(full_digits) < 3:
        return False
    for dropped in (1, 2):
        if len(full_digits) <= dropped:
            continue
        stem_digits = full_digits[:-dropped]
        if not stem_digits:
            continue
        stem = format_currency(Decimal(stem_digits))
        if not is_currency_digit_drop_twin(stem, fuller):
            continue
        if is_currency_digit_drop_twin(value, stem) or is_scale_shift(value, stem):
            return True
    return False


def should_defer_box28_to_line_sum(
    box28_value: object,
    service_lines: list[dict] | None,
    *,
    relative_contradiction: Decimal = Decimal("0.50"),
    min_lines: int = 2,
    candidates: list | None = None,
) -> bool:
    """Return True when box-28 should be cleared so LINE_TOTALS_RECONCILED owns E6."""
    from packages.claim_evidence.charge_total_authority import is_units_bleed_cents

    charges = observed_line_charges(service_lines)
    if not charges:
        return False
    box = parse_currency(box28_value)
    if box is None:
        return True
    if is_suspicious_tiny_total(box) or is_implausible_charge_total(box):
        return True
    # Never defer DI/vision+local Box 28 to a units-bleed line Σ.
    observed = sum(charges, Decimal(0))
    line_txt = format_currency(observed) if observed > 0 else None
    if (
        candidates
        and line_txt
        and not is_units_bleed_cents(box28_value)
        and is_units_bleed_cents(line_txt)
        and box28_di_partner_confirmed(box28_value, candidates)
    ):
        return False
    # Truncated equal-line OCR (3×200 vs Box 28 1200) is not a contradiction —
    # keep Box 28 so incomplete-grid authority can STP (EJGE.006/007/008).
    if incomplete_uniform_line_grid_explains_box28(box28_value, service_lines):
        return False
    # DI+local 2-line equal prefix (EJG7.016 2×150→600).
    if di_backed_incomplete_grid_explains_box28(box28_value, service_lines, candidates):
        return False
    # Digit-drop Box 28 under-read of DIGIT_DROP_FULLER_LOCAL Σ (DJKN.004/007).
    if box28_digit_drop_underread_of_fuller_line(box28_value, service_lines):
        return True
    if observed <= 0:
        return False
    difference = abs(box - observed)
    tolerance = max(Decimal("1.00"), observed * relative_contradiction)
    # Multi-line: defer on strong contradiction (existing rule).
    if len(charges) >= min_lines:
        return difference > tolerance
    # Single observed line: defer only when box-28 is wildly off the line
    # amount (Track-B residual: box-28 ``22.00`` vs line ``305.00``). Plausible
    # near-miss box-28 (e.g. 400 vs 305) stays with OCR — do not invent.
    return difference > tolerance


def line_sum_total(service_lines: list[dict] | None) -> str | None:
    charges = observed_line_charges(service_lines)
    if not charges:
        return None
    return format_currency(sum(charges, Decimal(0)))


def is_currency_digit_drop_twin(left: object, right: object) -> bool:
    """True when one reading is a truncated digit-prefix of the other (1–2 digits)."""
    a, b = _currency_digit_string(left), _currency_digit_string(right)
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if not longer.startswith(shorter):
        return False
    if not (1 <= (len(longer) - len(shorter)) <= 2):
        return False
    extra = longer[len(shorter) :]
    return not (extra and set(extra) <= {"0"})


def amounts_within_tolerance(
    left: object,
    right: object,
    *,
    absolute: Decimal = Decimal("1.00"),
    relative: Decimal = Decimal("0.05"),
) -> bool:
    a, b = parse_currency(left), parse_currency(right)
    if a is None or b is None:
        return False
    diff = abs(a - b)
    target = max(abs(a), abs(b), Decimal(1))
    return diff <= max(absolute, target * relative)


def _decimal_place_conflict(left: object, right: object) -> bool:
    """True when one amount is the other shifted by exactly two decimal places.

    ``49.72`` and ``4972.00`` are the same digits with a different cents column.
    That is not a dropped leading digit and must not corroborate.
    """
    a, b = parse_currency(left), parse_currency(right)
    if a is None or b is None or a == b:
        return False
    return a * 100 == b or b * 100 == a


def is_decimal_place_shift(left: object, right: object) -> bool:
    """True when one amount is the other shifted by exactly two decimal places.

    ``49.72`` and ``4972.00`` are the same digits with a different cents column.
    That is not a dropped leading digit and must not corroborate.
    """
    return _decimal_place_conflict(left, right)


# Open-source charge readers. Cloud DI and Claude/GPT are residual, never sole
# monetary authority (redesign stack: local OCR primary).
_OPEN_SOURCE_CHARGE_ENGINES = frozenset(
    {"paddleocr", "rapidocr", "tesseract", "tesseract_digits"}
)


def _candidate_engine_and_value(cand: object) -> tuple[str, object]:
    if not isinstance(cand, dict):
        return "", None
    shell = cand.get("ocr_candidate") if isinstance(cand.get("ocr_candidate"), dict) else cand
    engine = str(shell.get("engine") or shell.get("engine_name") or "").casefold()
    value = shell.get("value") or shell.get("raw_value")
    return engine, value


def open_source_charge_amounts(candidates: list | None) -> list:
    """Currency amounts read by Paddle, Rapid, or Tesseract — not Claude/DI."""
    found = []
    for cand in candidates or []:
        engine, value = _candidate_engine_and_value(cand)
        if engine not in _OPEN_SOURCE_CHARGE_ENGINES:
            continue
        if parse_currency(value) is None:
            continue
        found.append(value)
    return found


def _di_agrees_on_charge_amount(chosen: object, candidates: list | None) -> bool:
    """True when Azure Document Intelligence already read ``chosen``.

    DI crop residuals often keep trailing scrap in ``value`` (``23.00``) while
    ``raw_value`` still carries the printed total (``TOTAL CHARGE 1200; 00 23``).
    Shape the raw text the same way residual OCR does before comparing.
    """
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        shell = cand.get("ocr_candidate") if isinstance(cand.get("ocr_candidate"), dict) else cand
        engine = str(shell.get("engine") or shell.get("engine_name") or "").casefold()
        if "document_intelligence" not in engine and "azure_di" not in engine:
            continue
        if amounts_corroborate(chosen, shell.get("value") or shell.get("raw_value")):
            return True
        raw = shell.get("raw_value")
        if raw and raw != shell.get("value"):
            try:
                from packages.extraction_recovery.charge_azure_di_residual import (
                    _shape_charge_text,
                )

                shaped, ok = _shape_charge_text("total_charge", str(raw))
            except Exception:  # noqa: BLE001
                shaped, ok = None, False
            if ok and shaped and amounts_corroborate(chosen, shaped):
                return True
    return False


def _is_charge_digit_whitelist_prep(cand: object) -> bool:
    """True when the candidate came from charge digit-whitelist preprocessing."""
    if not isinstance(cand, dict):
        return False
    shell = cand.get("ocr_candidate") if isinstance(cand.get("ocr_candidate"), dict) else cand
    prep = str(
        shell.get("preprocessing_variant")
        or shell.get("preprocessing_path")
        or shell.get("preprocessing_profile")
        or ""
    ).casefold()
    return "charge_digit_whitelist" in prep


def _local_amount_only_from_digit_whitelist(
    amount: object, candidates: list | None
) -> bool:
    """True when every open-source read of ``amount`` is digit-whitelist soup.

    EJG7.003: paddle ``4825`` via ``charge_digit_whitelist_fast:full`` beside
    DI ``1825`` is not an independent local total — whitelist ink alone.
    """
    saw = False
    for cand in candidates or []:
        engine, value = _candidate_engine_and_value(cand)
        if engine not in _OPEN_SOURCE_CHARGE_ENGINES:
            continue
        if not amounts_corroborate(amount, value):
            continue
        saw = True
        if not _is_charge_digit_whitelist_prep(cand):
            return False
    return saw


def _di_vs_digit_whitelist_noise_only(
    chosen: object, candidates: list | None, local: list
) -> bool:
    """DI confirms ``chosen``; open-source rivals are non-twin whitelist soup.

    Lands EJG7.003 (DI+Claude ``1825`` vs paddle whitelist ``4825``). Must not
    unlock digit-drop twins (DJKN.005 ``200`` vs ``2001``, DJKN.007 ``200`` vs
    ``2004``) or ×10/×100 scale rivals — those stay unauthorized without a grid.
    """
    if not local or not _di_agrees_on_charge_amount(chosen, candidates):
        return False
    for amount in local:
        if amounts_corroborate(chosen, amount):
            continue
        if is_scale_shift(chosen, amount) or is_currency_digit_drop_twin(chosen, amount):
            return False
        if not _local_amount_only_from_digit_whitelist(amount, candidates):
            return False
    return True


def _line_geometry_cents_amounts(service_lines: list | None) -> list:
    """Open-source GEOMETRY_CENTS amounts observed on service-line cells."""
    found: list = []
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        for cand in line.get("candidates") or []:
            if not isinstance(cand, dict):
                continue
            prep = str(
                cand.get("preprocessing_variant")
                or cand.get("evidence_reference")
                or ""
            )
            if "GEOMETRY_CENTS" not in prep:
                continue
            engine, value = _candidate_engine_and_value(cand)
            if engine not in _OPEN_SOURCE_CHARGE_ENGINES:
                continue
            if parse_currency(value) is not None:
                found.append(value)
        for attempt in line.get("attempts") or []:
            if not isinstance(attempt, dict):
                continue
            if "GEOMETRY_CENTS" not in str(attempt.get("reason") or ""):
                continue
            engine = str(attempt.get("engine") or "").casefold()
            if engine not in _OPEN_SOURCE_CHARGE_ENGINES and not any(
                token in engine for token in ("paddle", "rapid", "tesseract")
            ):
                continue
            obs = attempt.get("observation") or {}
            shaped = (
                obs.get("shaped")
                or obs.get("canonical_monetary_value")
                or obs.get("value")
            )
            if parse_currency(shaped) is not None:
                found.append(shaped)
    return found


def _is_dollars_ruling_truncation(short: object, fuller: object) -> bool:
    """True when ``short`` is a dollars-ruling truncation of ``fuller`` (129 vs 1291.15)."""
    try:
        from packages.claim_evidence.line_charge_selector import _is_dollar_truncation
    except Exception:  # noqa: BLE001
        return False
    short_amt = parse_currency(short)
    fuller_amt = parse_currency(fuller)
    if short_amt is None or fuller_amt is None:
        return False
    return _is_dollar_truncation(format_currency(short_amt), format_currency(fuller_amt))


def _geometry_cents_line_supports_box28(
    chosen: object, candidates: list | None, service_lines: list | None
) -> bool:
    """True when line GEOMETRY_CENTS matches ``chosen`` and Box 28 locals truncate.

    DJKH.037: Rapid GEOMETRY_CENTS ``1291.15`` + Claude Box 28 ``1291.15`` beside
    dual-local dollars ``129.00``. Geometry cents is open-source authority; the
    dollars-ruling stem is truncation, not a rival total.
    """
    if not any(
        amounts_corroborate(chosen, amount)
        for amount in _line_geometry_cents_amounts(service_lines)
    ):
        return False
    local = open_source_charge_amounts(candidates)
    if not local:
        return True
    for amount in local:
        if amounts_corroborate(chosen, amount):
            continue
        if _is_dollars_ruling_truncation(amount, chosen):
            continue
        # ROI scrap beside the geometry fuller (115 vs 1291.15) is not a rival.
        if is_implausible_corroborator(amount, chosen):
            continue
        if is_scale_shift(chosen, amount) or is_currency_digit_drop_twin(chosen, amount):
            return False
        if _local_amount_only_from_digit_whitelist(amount, candidates):
            continue
        return False
    return True


def llm_charge_pick_has_open_source_authority(
    chosen: object,
    candidates: list | None,
    service_lines: list | None = None,
) -> bool:
    """True when open-source OCR supports ``chosen`` (exact or grid-backed stem).

    Claude/DI may arbitrate among locals. They must not mint a total the open-source
    readers did not see, and they must not pick a side of an ambiguous ×100 / dropped-digit pair.

    EJGE.009: Rapid ``12000`` beside DI+Claude ``1200`` is allowed only when an
    incomplete uniform line grid also explains Box 28 (3×$200 → $1200). Bare
    DI+Claude ``200`` beside paddle ``2001`` (DJKN.005) stays unauthorized —
    the local fuller read is often the true total.

    EJG7.003: DI ``1825`` beside paddle digit-whitelist ``4825`` (not a twin) is
    authorized — whitelist soup is not an independent local rival.

    DJKH.037: line GEOMETRY_CENTS ``1291.15`` supports Claude Box 28 when local
    dollars reads are ruling truncations of that fuller amount.
    """
    if parse_currency(chosen) is None:
        return False
    if agent_amount_is_inflated_scale(chosen, candidates):
        # DJKH.037: GEOMETRY_CENTS line ``1291.15`` is open-source authority for
        # the fuller stem; dollars-ruling ``129`` must not veto as inflated soup.
        # DJKN.005: paddle ``2001`` vs DI/Claude ``200`` — unique OS digit-drop
        # fuller is authorized even though 2001/200 ≈ ×10 trips inflated-scale.
        # DJKN.009: geometry ``600`` vs whitelist ``60`` — whitelist ×10 short only.
        if not (
            _geometry_cents_line_supports_box28(chosen, candidates, service_lines)
            or _chosen_is_open_source_digit_drop_fuller(chosen, candidates)
            or _inflated_only_vs_whitelist_shorts(chosen, candidates)
        ):
            return False
    # Open-source digit soup that implies >6 equal CMS rows is not authority
    # (EJGE.006 paddle 4200 vs 3×$200). Prefer the grid-backed alternate.
    if chosen_exceeds_cms_uniform_line_grid(chosen, service_lines):
        return False
    local = open_source_charge_amounts(candidates)
    if any(amounts_corroborate(chosen, amount) for amount in local):
        for amount in local:
            if amounts_corroborate(chosen, amount):
                continue
            if is_scale_shift(chosen, amount) or is_currency_digit_drop_twin(chosen, amount):
                # Whitelist soup ×10/digit shorts are not independent rivals
                # (DJKN.009 paddle ``60`` beside geometry ``600``).
                if _local_amount_only_from_digit_whitelist(amount, candidates):
                    continue
                return False
        return True
    # No exact local hit — DI vs non-twin digit-whitelist soup (EJG7.003).
    if _di_vs_digit_whitelist_noise_only(chosen, candidates, local):
        return True
    # Line GEOMETRY_CENTS matches chosen; box locals are dollars truncations.
    if _geometry_cents_line_supports_box28(chosen, candidates, service_lines):
        return True
    # DI-confirmed inflated stem only when the truncated equal-amount service
    # grid independently explains Box 28.
    if not local or not _di_agrees_on_charge_amount(chosen, candidates):
        return False
    if not incomplete_uniform_line_grid_explains_box28(chosen, service_lines):
        return False
    chosen_amt = parse_currency(chosen)
    assert chosen_amt is not None
    for amount in local:
        amt = parse_currency(amount)
        if amt is None:
            return False
        if amt > chosen_amt and is_scale_shift(chosen, amount):
            continue
        # Paddle digit-whitelist soup beyond the 6-row CMS grid (4200 vs 3×200)
        # is not a rival of the grid-explained Box 28 (EJGE.006).
        if amt > chosen_amt and chosen_exceeds_cms_uniform_line_grid(amount, service_lines):
            continue
        return False
    return True


def prefer_open_source_digit_drop_fuller_box28(
    chosen: object, candidates: list | None
) -> str | None:
    """When Box 28 under-reads a unique open-source fuller twin, return that fuller.

    DJKN.005: DI/Claude ``200`` beside paddle ``2001`` — prefer ``2001`` (GT).
    DJKN.001: paddle whitelist also reads ``200`` — short read is corroborated;
    return None so printed ``200`` stays (GT).
    """
    chosen_amt = parse_currency(chosen)
    if chosen_amt is None:
        return None
    local = open_source_charge_amounts(candidates)
    if not local:
        return None
    # Open-source already corroborates the short read — do not override
    # (DJKN.001 paddle 200 + DI 200).
    if any(amounts_corroborate(chosen, amount) for amount in local):
        return None
    fullers: list[str] = []
    for amount in local:
        amt = parse_currency(amount)
        if amt is None or amt <= chosen_amt:
            continue
        if is_currency_digit_drop_twin(chosen, amount):
            fullers.append(format_currency(amt))
    unique = sorted(set(fullers))
    if len(unique) != 1:
        return None
    return unique[0]


def prefer_di_partner_fuller_over_local_underread(
    chosen: object, candidates: list | None
) -> str | None:
    """When chosen is a ×10/×100 underread of DI+partner ink, return the fuller.

    EJI2.036: paddle/rapid ``15.00`` beside DI+Claude ``150.00``.
    HJBI.005: local ``34.00`` beside DI+Claude ``3400.00``.
    Cash ruling-split DI raws are reshaped before agreement (``$ 97 |39`` → 97.39).
    """
    chosen_amt = parse_currency(chosen)
    if chosen_amt is None or not candidates:
        return None
    by_norm: dict[str, set[str]] = {}
    for cand in candidates:
        if isinstance(cand, dict):
            shell = (
                cand.get("ocr_candidate")
                if isinstance(cand.get("ocr_candidate"), dict)
                else cand
            )
            engine = str(shell.get("engine") or "")
            value = str(shell.get("value") or "")
            raw = str(shell.get("raw_value") or "")
        else:
            engine = str(getattr(cand, "engine", "") or "")
            value = str(getattr(cand, "value", "") or "")
            raw = str(getattr(cand, "raw_value", "") or "")
        if not value.strip() and not raw.strip():
            continue
        charge_value = value
        if "$" in raw and re.search(r"[:|/]", raw):
            try:
                from packages.claim_evidence.line_charge_selector import (
                    _ruling_split_amount,
                )

                ruled = _ruling_split_amount(raw)
                if ruled:
                    charge_value = ruled
            except Exception:  # noqa: BLE001
                pass
        amt = parse_currency(charge_value)
        if amt is None:
            continue
        eng = engine.casefold()
        family = (
            "di"
            if "document_intelligence" in eng or "azure_di" in eng or "azure_read" in eng
            else "vision"
            if "claude" in eng or "gpt4o" in eng or "anthropic" in eng
            else "local"
            if any(x in eng for x in ("paddle", "rapid", "tesseract"))
            else None
        )
        if family is None:
            continue
        key = format_currency(amt)
        by_norm.setdefault(key, set()).add(family)
    fullers: list[str] = []
    for amount, families in by_norm.items():
        amt = parse_currency(amount)
        if amt is None or amt <= chosen_amt:
            continue
        if "di" not in families:
            continue
        if not (families & {"vision", "local"}):
            continue
        if is_scale_shift(chosen, amount) or is_decimal_place_shift(chosen, amount):
            fullers.append(amount)
    unique = sorted(set(fullers))
    if len(unique) != 1:
        return None
    return unique[0]


def box28_di_partner_confirmed(amount: object, candidates: list | None) -> bool:
    """True when DI + (vision or local) — or vision + local — read ``amount``.

    DI may return a ×10/×100 twin of the partner (``523800`` vs ``5238``); that
    still counts as DI family support for the partner amount. Used to keep
    printed Box 28 over bleed-cents line Σ without another cloud call.
    """
    target = parse_currency(amount)
    if target is None or not candidates:
        return False
    target_txt = format_currency(target)
    families: set[str] = set()
    for cand in candidates:
        if isinstance(cand, dict):
            shell = (
                cand.get("ocr_candidate")
                if isinstance(cand.get("ocr_candidate"), dict)
                else cand
            )
            engine = str(shell.get("engine") or "")
            value = str(shell.get("value") or "")
            raw = str(shell.get("raw_value") or "")
        else:
            engine = str(getattr(cand, "engine", "") or "")
            value = str(getattr(cand, "value", "") or "")
            raw = str(getattr(cand, "raw_value", "") or "")
        charge_value = value
        di_glue_of_target = False
        try:
            from packages.claim_evidence.line_charge_selector import (
                _ruling_split_amount,
                is_ruling_split_digit_glue,
            )

            ruled = _ruling_split_amount(raw)
            if ruled:
                charge_value = ruled
            di_glue_of_target = is_ruling_split_digit_glue(
                target_txt, value
            ) or is_ruling_split_digit_glue(target_txt, raw)
            if di_glue_of_target:
                # DI/paddle glued ``523156`` corroborates ruled local ``523.56``.
                charge_value = target_txt
        except Exception:  # noqa: BLE001
            di_glue_of_target = False
        amt = parse_currency(charge_value)
        if amt is None:
            continue
        amt_txt = format_currency(amt)
        eng = engine.casefold()
        if "document_intelligence" in eng or "azure_di" in eng or "azure_read" in eng:
            if amt_txt == target_txt or is_scale_shift(target_txt, amt_txt) or di_glue_of_target:
                families.add("di")
        elif "claude" in eng or "gpt4o" in eng or "anthropic" in eng:
            if amt_txt == target_txt:
                families.add("vision")
        elif any(x in eng for x in ("paddle", "rapid", "tesseract")):
            if amt_txt == target_txt:
                families.add("local")
    if "di" in families and (families & {"vision", "local"}):
        return True
    return "vision" in families and "local" in families


def prefer_box28_over_bleed_line_sum(
    chosen: object, candidates: list | None
) -> str | None:
    """When chosen is bleed-cents line Σ, prefer DI/vision+local Box 28 ink.

    DJJM.049: derived ``342.01`` beside Claude+paddle ``5238.00``.
    EJGE.043: derived ``250.10`` beside DI+Claude ``25000.00``.
    """
    from packages.claim_evidence.charge_total_authority import is_units_bleed_cents

    if not is_units_bleed_cents(chosen) or not candidates:
        return None
    # Collect non-bleed amounts corroborated by DI+partner or vision+local.
    amounts: dict[str, int] = {}
    for cand in candidates:
        if isinstance(cand, dict):
            shell = (
                cand.get("ocr_candidate")
                if isinstance(cand.get("ocr_candidate"), dict)
                else cand
            )
            value = str(shell.get("value") or "")
        else:
            value = str(getattr(cand, "value", "") or "")
        amt = parse_currency(value)
        if amt is None:
            continue
        txt = format_currency(amt)
        if is_units_bleed_cents(txt):
            continue
        if box28_di_partner_confirmed(txt, candidates):
            amounts[txt] = amounts.get(txt, 0) + 1
    if len(amounts) != 1:
        return None
    return next(iter(amounts))


def _chosen_is_open_source_digit_drop_fuller(
    chosen: object, candidates: list | None
) -> bool:
    """True when ``chosen`` is the unique OS fuller prefer_* would pick from a short.

    Lets ``llm_charge_pick_has_open_source_authority`` accept paddle ``2001`` on
    DJKN.005 even though DI/Claude ``200`` makes ``agent_amount_is_inflated_scale``
    trip (ratio ≈ ×10). Requires exact open-source corroboration of the fuller
    and rejects conflict-agent soup where Claude/DI already minted the fuller
    (paddle ``200400`` → ``2004`` beside Claude ``2004``).
    """
    chosen_amt = parse_currency(chosen)
    if chosen_amt is None:
        return False
    chosen_fmt = format_currency(chosen_amt)
    local = open_source_charge_amounts(candidates)
    if not any(amounts_corroborate(chosen, amount) for amount in local):
        return False
    # Closed-source already reading the fuller = conflict-agent inflation, not
    # an open-source-only digit-drop recovery.
    for cand in candidates or []:
        engine, value = _candidate_engine_and_value(cand)
        if not engine or engine in _OPEN_SOURCE_CHARGE_ENGINES:
            continue
        if amounts_corroborate(chosen, value):
            return False
    seen: set[str] = set()
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        shell = (
            cand.get("ocr_candidate")
            if isinstance(cand.get("ocr_candidate"), dict)
            else cand
        )
        short = shell.get("value") or shell.get("raw_value")
        short_amt = parse_currency(short)
        if short_amt is None or short_amt >= chosen_amt:
            continue
        key = format_currency(short_amt)
        if key in seen:
            continue
        seen.add(key)
        if prefer_open_source_digit_drop_fuller_box28(short, candidates) == chosen_fmt:
            return True
    return False


def prefer_incomplete_grid_box28(
    chosen: object,
    candidates: list | None,
    service_lines: list | None,
) -> str | None:
    """When agent pick exceeds the CMS uniform grid, return the grid-backed total.

    EJGE.006: conflict-agent+paddle ``4200`` implies 21 rows; DI raw / Claude
    resolve ``1200`` is explained by 3×$200. Prefer that amount for E6.
    """
    if not chosen_exceeds_cms_uniform_line_grid(chosen, service_lines):
        return None
    explained: list[str] = []
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        shell = cand.get("ocr_candidate") if isinstance(cand.get("ocr_candidate"), dict) else cand
        engine = str(shell.get("engine") or shell.get("engine_name") or "").casefold()
        raw = shell.get("raw_value")
        value = shell.get("value") or raw
        # Shape DI residuals so trailing scrap does not hide the printed total.
        if "document_intelligence" in engine or "azure_di" in engine:
            try:
                from packages.extraction_recovery.charge_azure_di_residual import (
                    _shape_charge_text,
                )

                shaped, ok = _shape_charge_text("total_charge", str(raw or value or ""))
            except Exception:  # noqa: BLE001
                shaped, ok = None, False
            if ok and shaped:
                value = shaped
        amount = parse_currency(value)
        if amount is None:
            continue
        if not incomplete_uniform_line_grid_explains_box28(value, service_lines):
            continue
        if not _di_agrees_on_charge_amount(value, candidates):
            continue
        explained.append(format_currency(amount))
    unique = sorted(set(explained))
    if len(unique) != 1:
        return None
    alt = unique[0]
    if not llm_charge_pick_has_open_source_authority(alt, candidates, service_lines):
        return None
    if charge_conflicts_with_plausible_line_sum(alt, service_lines, candidates):
        return None
    return alt


def di_backed_incomplete_grid_explains_box28(
    chosen: object,
    service_lines: list | None,
    candidates: list | None,
) -> bool:
    """True when ≥2 equal selected lines prefix Box 28 and DI+local agree.

    EJG7.016: only 2 of 4 equal ``$150`` rows OCR'd while DI+paddle Box 28
    read ``$600``. Requiring ≥3 equal lines would leave a DI-local total HITL
    despite open-source agreement. Still caps implied rows at 6.
    """
    if not incomplete_uniform_line_grid_explains_box28(
        chosen, service_lines, min_observed=2
    ):
        return False
    if not _di_agrees_on_charge_amount(chosen, candidates):
        return False
    local = open_source_charge_amounts(candidates)
    return any(amounts_corroborate(chosen, amount) for amount in local)


def agent_amount_is_inflated_scale(chosen: object, candidates: list | None) -> bool:
    """True when ``chosen`` is the larger ×10/×100 twin of another read.

    Conflict-agent ``2004.00`` must not override a ranked ``200.00`` just because
    a digit-whitelist paddle read also shaped ``200400`` as ``2004.00``. The
    smaller amount stays eligible; the inflated side stays a conflict.
    """
    chosen_amt = parse_currency(chosen)
    if chosen_amt is None:
        return False
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        amount = parse_currency(cand.get("value") or cand.get("raw_value"))
        if amount is None or amount >= chosen_amt:
            continue
        if is_scale_shift(chosen_amt, amount):
            return True
    return False


def incomplete_uniform_line_grid_explains_box28(
    chosen: object, service_lines: list | None, *, min_observed: int = 3
) -> bool:
    """True when equal selected line amounts are a proper prefix of Box 28.

    CMS-1500 pages often OCR only the first 3 of 6 equal ``$200`` rows while
    Box 28 correctly reads ``$1200`` (EJGE.007/008). That partial Σ is not a
    rival claim total — conflict-agent BOX28 must not be blocked by it.
    Requires ``min_observed`` equal selected lines (default ≥3) and caps
    implied rows at 6. DI+open-source callers may pass ``min_observed=2``
    (EJG7.016).
    """
    chosen_amt = parse_currency(chosen)
    if chosen_amt is None or chosen_amt <= 0:
        return False
    units: list[Decimal] = []
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        selection = line.get("line_charge_selection") or {}
        disposition = str(selection.get("disposition") or "")
        # Prefer selector amounts; fall back to observed charge fields.
        amount = None
        if disposition.startswith("SELECTED"):
            amount = parse_currency(selection.get("amount"))
        if amount is None:
            for key in _CHARGE_FIELDS:
                amount = parse_currency(line.get(key))
                if amount is not None:
                    break
        if amount is None or amount <= 0:
            continue
        units.append(amount)
    if len(units) < 2:
        return False
    unit = units[0]
    if any(value != unit for value in units):
        return False
    quotient = chosen_amt / unit
    if quotient != quotient.to_integral_value():
        return False
    implied_rows = int(quotient)
    observed_rows = len(units)
    # Need a clear truncated multi-row strip. Cap at the printed 6-line CMS grid.
    if observed_rows < max(2, int(min_observed)):
        return False
    return observed_rows < implied_rows <= 6


def chosen_exceeds_cms_uniform_line_grid(
    chosen: object, service_lines: list | None
) -> bool:
    """True when equal selected lines imply ``chosen`` needs more than 6 CMS rows.

    EJGE.006: 3×$200 with agent/paddle ``4200`` implies 21 rows — beyond the
    printed CMS-1500 service grid. That inflated shell must stay HITL even when
    open-source OCR also shaped the same digits.
    """
    chosen_amt = parse_currency(chosen)
    if chosen_amt is None or chosen_amt <= 0:
        return False
    units: list[Decimal] = []
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        selection = line.get("line_charge_selection") or {}
        disposition = str(selection.get("disposition") or "")
        amount = None
        if disposition.startswith("SELECTED"):
            amount = parse_currency(selection.get("amount"))
        if amount is None:
            for key in _CHARGE_FIELDS:
                amount = parse_currency(line.get(key))
                if amount is not None:
                    break
        if amount is None or amount <= 0:
            continue
        units.append(amount)
    if len(units) < 3:
        return False
    unit = units[0]
    if unit <= 0 or any(value != unit for value in units):
        return False
    quotient = chosen_amt / unit
    if quotient != quotient.to_integral_value():
        return False
    return int(quotient) > 6


def charge_conflicts_with_plausible_line_sum(
    chosen: object,
    service_lines: list | None,
    candidates: list | None = None,
) -> bool:
    """True when observed line Σ is a real different total, not cents noise or junk."""
    # DJKN.009: AMBIGUOUS ``1600`` tagged ONLY_BLEED_OR_SOUP / BARE_DIGIT_SOUP is
    # not a rival of geometry whole-dollar Box 28 ``600``.
    if _service_line_sum_is_bleed_soup_only(service_lines):
        return False
    total = line_sum_total(service_lines)
    if total is None or parse_currency(chosen) is None:
        return False
    if is_implausible_charge_total(total):
        return False
    if amounts_corroborate(chosen, total) or amounts_same_stem_cents_twin(chosen, total):
        return False
    # Truncated equal-amount service grid (3×200 vs Box 28 1200) is not a rival.
    if incomplete_uniform_line_grid_explains_box28(chosen, service_lines):
        return False
    # DI+open-source Box 28 with a 2-line equal prefix (EJG7.016 2×150→600).
    if di_backed_incomplete_grid_explains_box28(chosen, service_lines, candidates):
        return False
    # L4: exact DI+partner Box 28 vs a single under-read line is not a rival
    # claim total (EJG7.005 agent/DI ``400`` vs line ``120``).
    try:
        from packages.claim_evidence.charge_total_authority import (
            _exact_di_partner_charge_agreement,
        )
    except Exception:  # noqa: BLE001
        _exact_di_partner_charge_agreement = None  # type: ignore[assignment]
    if (
        _exact_di_partner_charge_agreement is not None
        and _exact_di_partner_charge_agreement(chosen, candidates)
    ):
        agreed, observed = dual_engine_line_fraction(service_lines)
        if observed <= 1:
            return False
    return True


def _service_line_sum_is_bleed_soup_only(service_lines: list | None) -> bool:
    """True when every charged line is AMBIGUOUS bleed/soup (not a real Σ)."""
    saw = False
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        if parse_currency(line.get("charges") or line.get("charge_amount")) is None:
            continue
        saw = True
        selection = line.get("line_charge_selection") or {}
        disposition = str(selection.get("disposition") or "")
        reason = str(selection.get("reason") or "")
        if disposition != "AMBIGUOUS_LINE_CHARGE":
            return False
        if not any(
            token in reason
            for token in (
                "ONLY_BLEED_OR_SOUP",
                "BARE_DIGIT_SOUP",
                "NO_DUAL_LOCAL_AGREEMENT",
            )
        ):
            # Check rejected tags for BARE_DIGIT_SOUP amount that became charges.
            rejected = selection.get("rejected") or []
            soupish = any(
                "BARE_DIGIT_SOUP" in str((row or {}).get("reason") or "")
                or "ONLY_BLEED_OR_SOUP" in str((row or {}).get("reason") or "")
                for row in rejected
                if isinstance(row, dict)
            )
            if not soupish and "ONLY_BLEED_OR_SOUP" not in reason:
                return False
    return saw


def box28_geometry_underread_whole_dollar(
    field_payload: dict | None,
) -> str | None:
    """Recover whole-dollar Box 28 from a mis-partitioned GEOMETRY_CENTS_UNDERREAD.

    DJKN.009: rapid raw ``600`` shaped as ``6.00`` (1 dollar glyph + 2 cents) while
    paddle whitelist ``6000``→``60`` is a ×10 short of the true ``600.00``.
    """
    if not isinstance(field_payload, dict):
        return None
    payload = field_payload
    if isinstance(payload.get("ocr"), dict):
        payload = payload["ocr"]
    for attempt in payload.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        reason = str(attempt.get("reason") or "")
        if "GEOMETRY_CENTS" not in reason or "UNDERREAD" not in reason:
            continue
        obs = attempt.get("observation")
        if not isinstance(obs, dict):
            continue
        raw_digits = re.sub(r"\D", "", str(obs.get("raw_digit_sequence") or obs.get("text") or ""))
        if not (3 <= len(raw_digits) <= 6):
            continue
        shaped = obs.get("canonical_monetary_value") or obs.get("shaped")
        shaped_amt = parse_currency(shaped)
        # Mis-partition: single leading dollar digit + cents zeros (600 → 6.00).
        dollar_glyphs = obs.get("dollar_glyphs") or []
        cents_glyphs = obs.get("cents_glyphs") or []
        mispartitioned = (
            len(dollar_glyphs) == 1
            and len(cents_glyphs) >= 1
            and shaped_amt is not None
            and shaped_amt < Decimal(10)
        )
        if not mispartitioned:
            continue
        whole = parse_currency(raw_digits)
        if whole is None or whole < Decimal(10):
            continue
        return format_currency(whole)
    return None


def _inflated_only_vs_whitelist_shorts(
    chosen: object, candidates: list | None
) -> bool:
    """True when chosen has exact OS hit and every ×10/×100 short rival is whitelist-only.

    DJKN.009: geometry ``600`` beside paddle whitelist ``60`` (from ``6000``).
    """
    local = open_source_charge_amounts(candidates)
    if not any(amounts_corroborate(chosen, amount) for amount in local):
        return False
    chosen_amt = parse_currency(chosen)
    if chosen_amt is None:
        return False
    saw_short = False
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        amount = parse_currency(cand.get("value") or cand.get("raw_value"))
        if amount is None or amount >= chosen_amt:
            continue
        if not is_scale_shift(chosen, amount):
            continue
        saw_short = True
        if not _local_amount_only_from_digit_whitelist(amount, candidates):
            return False
    return saw_short


def is_scale_shift(left: object, right: object) -> bool:
    """True when one amount is about ×10 or ×100 the other (cents column or a dropped scale)."""
    if is_decimal_place_shift(left, right):
        return True
    a, b = parse_currency(left), parse_currency(right)
    if a is None or b is None or a == 0 or b == 0:
        return False
    hi, lo = (a, b) if a > b else (b, a)
    ratio = hi / lo
    return abs(ratio - Decimal(10)) <= Decimal("0.25") or abs(ratio - Decimal(100)) <= Decimal("2")


def amounts_corroborate(left: object, right: object) -> bool:
    """Corroboration requires exact monetary equality, not plausible repair."""
    a, b = parse_currency(left), parse_currency(right)
    return a is not None and b is not None and a == b


def amounts_same_stem_cents_twin(left: object, right: object) -> bool:
    """True when amounts share dollars and differ by ≤ $1.00 (OCR twin noise)."""
    a, b = parse_currency(left), parse_currency(right)
    if a is None or b is None or a == b:
        return False
    la, lb = format_currency(a), format_currency(b)
    if la.split(".", 1)[0] != lb.split(".", 1)[0]:
        return False
    return abs(a - b) <= Decimal("1.00")


def amounts_corroborate_or_cents_twin(left: object, right: object) -> bool:
    """Exact corroboration, or same-stem ≤ $1 OCR twin (157.00 vs 157.07)."""
    return amounts_corroborate(left, right) or amounts_same_stem_cents_twin(left, right)


def vision_local_decimal_column(total: object, corroborators: list[object]) -> bool:
    """True when box-28 / DI is only the ×100 unplaced twin of a placed line sum.

    ``49.72`` with a vision+local consensus and a Document Intelligence read of
    ``4972`` is the cents column, not a second total. Truncations of that same
    digit string (``972``, ``72``) are not rivals. A different plausible amount
    still conflicts. Digit-drop (``13`` vs ``131``) is not this rule.
    """
    parsed = parse_currency(total)
    if parsed is None or parsed <= 0:
        return False
    shifted = None
    for value in corroborators:
        other = parse_currency(value)
        if other is None or other <= parsed:
            continue
        if other == parsed * 100:
            shifted = other
            break
    if shifted is None:
        return False
    shift_digits = _currency_digit_string(shifted)
    for value in corroborators:
        other = parse_currency(value)
        if other is None or other == shifted or amounts_corroborate(total, value):
            continue
        digits = _currency_digit_string(other)
        if digits and shift_digits and digits in shift_digits:
            continue
        if is_implausible_corroborator(value, total):
            continue
        return False
    return True


def is_vision_crop_engine(engine: object) -> bool:
    """True for Azure gpt-4o / Anthropic Claude crop residuals (same evidence family)."""
    name = str(engine or "").strip().casefold()
    return any(
        token in name
        for token in ("gpt4o", "gpt-4o", "claude", "anthropic")
    )


def line_has_vision_and_local_on_selected(
    service_lines: list[dict] | None,
    total: object,
) -> bool:
    """True when the selected line amount is on both a vision crop and one local."""
    target = parse_currency(total)
    if target is None:
        return False
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        selected = None
        for key in _CHARGE_FIELDS:
            selected = parse_currency(line.get(key))
            if selected is not None:
                break
        if selected != target:
            continue
        saw_vision = False
        saw_local = False
        for cand in line.get("candidates") or []:
            if not isinstance(cand, dict):
                continue
            if parse_currency(cand.get("value")) != target:
                continue
            engine = cand.get("engine")
            if is_vision_crop_engine(engine):
                saw_vision = True
            elif _engine_family(engine) in {"rapidocr", "paddleocr"}:
                saw_local = True
        if saw_vision and saw_local:
            return True
    return False


def _engine_family(engine: object) -> str:
    name = str(engine or "").strip().casefold()
    # Vision crop residuals (gpt-4o / Claude) are not independent OCR engines for
    # LINE_TOTALS dual-engine AUTO (local+vision agreeing on the same wrong amount).
    if is_vision_crop_engine(name):
        return _GPT4O_FAMILY
    if "azure" in name or "document_intelligence" in name:
        return "azure_document_intelligence_read"
    if "rapid" in name:
        return "rapidocr"
    if "paddle" in name:
        return "paddleocr"
    if "tesseract" in name:
        return "tesseract"
    return name


def candidate_independence_key(cand: object) -> tuple:
    """Explicit evidence lineage for independence checks.

    Captures producing_engine, source crop, preprocessing path, candidate value,
    confidence, parent_evidence_id, and independence_group when present.
    """
    if not isinstance(cand, dict):
        return ()
    engine = cand.get("producing_engine") or cand.get("engine") or ""
    crop = cand.get("source_crop_id") or cand.get("source_crop") or ""
    prep = cand.get("preprocessing_path") or cand.get("preprocessing_variant") or ""
    value = cand.get("value") if cand.get("value") is not None else cand.get("candidate_value")
    conf = (
        cand.get("confidence")
        if cand.get("confidence") is not None
        else cand.get("calibrated_confidence")
        if cand.get("calibrated_confidence") is not None
        else cand.get("raw_confidence")
    )
    parent = cand.get("parent_evidence_id") or ""
    group = cand.get("independence_group") or ""
    return (
        str(engine).strip(),
        str(crop).strip(),
        str(prep).strip(),
        str(value if value is not None else "").strip(),
        str(conf if conf is not None else "").strip(),
        str(parent).strip(),
        str(group).strip(),
    )


def candidates_are_independent(a: object, b: object) -> bool:
    """False when candidates share crop, parent, or independence_group lineage.

    Same source crop, same upstream OCR output lineage (parent_evidence_id),
    or the same non-empty independence_group must not count as independent
    corroboration for critical charge AUTO.
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    parent_a = str(a.get("parent_evidence_id") or "").strip()
    parent_b = str(b.get("parent_evidence_id") or "").strip()
    if parent_a and parent_b and parent_a == parent_b:
        return False
    # Local derived from the gpt-4o evidence id itself.
    gpt_id = str(b.get("evidence_id") or "").strip()
    if parent_a and gpt_id and parent_a == gpt_id:
        return False
    local_id = str(a.get("evidence_id") or "").strip()
    if parent_b and local_id and parent_b == local_id:
        return False
    group_a = str(a.get("independence_group") or "").strip()
    group_b = str(b.get("independence_group") or "").strip()
    if group_a and group_b and group_a == group_b:
        return False
    crop_a = str(a.get("source_crop_id") or a.get("source_crop") or "").strip()
    crop_b = str(b.get("source_crop_id") or b.get("source_crop") or "").strip()
    return not (crop_a and crop_b and crop_a == crop_b)


def _candidate_amount(cand: dict) -> Decimal | None:
    text = cand.get("value")
    if text is None or not str(text).strip():
        return None
    parsed = parse_currency(text)
    if parsed is None or is_implausible_charge_total(parsed):
        return None
    return parsed


def _candidate_amounts_by_family(
    candidates: list[dict] | None,
    *,
    families: frozenset[str] | None = None,
) -> dict[str, Decimal]:
    """Map engine family → first currency-shaped amount.

    Uses shaped ``value`` only — never raw OCR soup (``9AA`` → 9) which poisoned
    gpt-4o+local consensus when an earlier empty paddle shell preceded a good read.
    """
    allowed = families
    by_engine: dict[str, Decimal] = {}
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        family = _engine_family(cand.get("engine") or cand.get("producing_engine"))
        if allowed is not None and family not in allowed:
            continue
        if family in by_engine:
            continue
        parsed = _candidate_amount(cand)
        if parsed is None:
            continue
        by_engine[family] = parsed
    return by_engine


def _shaped_candidate_amounts(candidates: list[dict] | None) -> dict[str, Decimal]:
    """Map independent engine family → first currency-shaped amount."""
    return _candidate_amounts_by_family(candidates, families=_INDEPENDENT_ENGINES)


def _first_candidate_for_family(
    candidates: list[dict] | None,
    family: str,
) -> dict | None:
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        if _engine_family(cand.get("engine") or cand.get("producing_engine")) != family:
            continue
        if _candidate_amount(cand) is None:
            continue
        return cand
    return None


def _selected_provenance_engine(line: dict) -> str:
    """Best-effort producing engine for the selected line charge.

    Explicit provenance wins. Fallback prefers a non-gpt-4o candidate that
    matches the selected amount so candidate order cannot falsely attribute
    an independently produced local value to gpt-4o.
    """
    for key in ("producing_engine", "engine", "selected_engine", "provenance_engine"):
        raw = line.get(key)
        if raw:
            return str(raw)
    prov = line.get("provenance")
    if isinstance(prov, dict):
        for key in ("producing_engine", "engine", "source_engine"):
            raw = prov.get(key)
            if raw:
                return str(raw)
    target = parse_currency(line.get("charges") or line.get("charge_amount"))
    if target is None:
        return ""
    target_txt = format_currency(target)
    gpt_match = ""
    for cand in line.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        parsed = _candidate_amount(cand)
        if parsed is None:
            continue
        if not _exact_or_dollar_agree(target_txt, format_currency(parsed)):
            continue
        engine = str(cand.get("producing_engine") or cand.get("engine") or "")
        if _engine_family(engine) != _GPT4O_FAMILY:
            return engine
        if not gpt_match:
            gpt_match = engine
    return gpt_match


def _exact_or_dollar_agree(left: object, right: object) -> bool:
    """Strict AUTO agreement: exact or within $1 — never digit-drop twins."""
    return amounts_within_tolerance(
        left,
        right,
        absolute=Decimal("1.00"),
        relative=Decimal(0),
    )


def line_has_dual_engine_agreement(line: dict) -> bool:
    """True when ≥2 independent engines agree on the same currency amount.

    Exact / $1 tolerance only — digit-drop twins are NOT dual-engine agreement
    for LINE_TOTALS AUTO (13↔131 class false accepts on hard-15).

    Local paddle+rapid agreement with the *selected* charge is authoritative
    even when a vision crop residual carries place-shift soup of the same stem
    (281.00 dual-local vs Claude/gpt-4o 2800.00). Vision peers must not veto
    dual-local corroboration of the selector output.
    """
    if not isinstance(line, dict):
        return False
    target = parse_currency(line.get("charges") or line.get("charge_amount"))
    candidates = [c for c in (line.get("candidates") or []) if isinstance(c, dict)]
    if target is not None:
        target_txt = format_currency(target)
        local_families: set[str] = set()
        for cand in candidates:
            fam = _engine_family(cand.get("engine") or cand.get("producing_engine"))
            if fam not in _LOCAL_ENGINES:
                continue
            amt = _candidate_amount(cand)
            if amt is None:
                continue
            if _exact_or_dollar_agree(target_txt, format_currency(amt)):
                local_families.add(fam)
        if len(local_families) >= 2:
            return True
    amounts = _shaped_candidate_amounts(candidates)
    if len(amounts) < 2:
        return False
    values = list(amounts.values())
    primary = values[0]
    if not all(
        _exact_or_dollar_agree(format_currency(primary), format_currency(other))
        for other in values[1:]
    ):
        return False
    # Engines must agree with the selected charge, not only with each other
    # (20.00/20.00 must not AUTO a selected 200.00).
    if target is None:
        return True
    return _exact_or_dollar_agree(format_currency(target), format_currency(primary))


def _sole_line_vision_scale_twin_of_dual_local(line: dict) -> bool:
    """True when dual-local selected amount has a Claude/gpt ×10/×100 twin.

    M0471JEB.008: paddle+rapid ``130.00``, Claude ``1300`` (lost decimal) with
    empty Box 28 — vision confirms the digit stem without superseding local.
    """
    if not isinstance(line, dict) or not line_has_dual_engine_agreement(line):
        return False
    target = parse_currency(line.get("charges") or line.get("charge_amount"))
    if target is None:
        return False
    target_txt = format_currency(target)
    for cand in line.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        eng = str(cand.get("engine") or "").casefold()
        if not (
            "gpt4o" in eng
            or "gpt-4o" in eng
            or "claude" in eng
            or "anthropic" in eng
        ):
            continue
        other = parse_currency(cand.get("value") or cand.get("raw_value"))
        if other is None:
            continue
        if is_scale_shift(target_txt, format_currency(other)):
            return True
    return False


def line_has_gpt4o_local_consensus(line: dict) -> bool:
    """gpt-4o + ≥1 independent usable local agree with the selected charge.

    Agreement uses exact / $1 only (``relative=0``) — digit-drop twins do NOT
    promote via this path. Blank shells and form-noise locals are not usable
    corroboration; missing usable locals → False (no gpt-4o-only fallback).

    Candidates that share ``parent_evidence_id``, non-empty ``independence_group``,
    or ``source_crop_id`` with the gpt-4o reading are not independent. If the
    selected value's provenance is gpt-4o family and no independent local
    agrees, fail closed.
    """
    if not isinstance(line, dict):
        return False
    if line.get("cents_unresolved"):
        return False
    target = parse_currency(line.get("charges") or line.get("charge_amount"))
    if target is None or is_implausible_charge_total(target):
        return False
    target_txt = format_currency(target)
    candidates = [c for c in (line.get("candidates") or []) if isinstance(c, dict)]

    gpt_cand = _first_candidate_for_family(candidates, _GPT4O_FAMILY)
    if gpt_cand is None:
        return False
    gpt_amt = _candidate_amount(gpt_cand)
    if gpt_amt is None:
        return False
    gpt_txt = format_currency(gpt_amt)
    if not _exact_or_dollar_agree(target_txt, gpt_txt):
        return False

    # Dollars-ruling geometry: a clipped zero or units-bleed sibling confirms
    # the vision stem. Same-crop engines are not a second evidence family;
    # the ruling split is the separate geometric check. Digit-drop twins
    # without a dollars_ruling candidate stay fail-closed (13 vs 131).
    try:
        from packages.ocr_portfolio.monetary_recognizer import (
            ruling_geometry_supports_charge,
        )

        if ruling_geometry_supports_charge(candidates, target_txt):
            return True
    except Exception:  # noqa: BLE001
        pass

    # gpt-4o-attributed selection is fine when a usable independent local
    # confirms the same amount (local confirmation path).

    usable_by_family: dict[str, list[str]] = {}

    def _pos_like(value: object) -> bool:
        try:
            from packages.geometry_authority import is_pos_like_currency

            return bool(is_pos_like_currency(value))
        except Exception:  # noqa: BLE001
            return False

    for cand in candidates:
        fam = _engine_family(cand.get("engine") or cand.get("producing_engine"))
        if fam not in _LOCAL_ENGINES:
            continue
        local_amt = _candidate_amount(cand)
        if local_amt is None:
            continue
        local_txt = format_currency(local_amt)
        # POS codes (11) and implausible tails are not votes against a vision read.
        if _pos_like(local_txt) and not _pos_like(gpt_txt):
            # A POS-shaped dollar stem that is the same amount within $1
            # (34.00 beside ruled 34.25) is not a place-of-service code.
            if not _exact_or_dollar_agree(local_txt, gpt_txt) and not _exact_or_dollar_agree(
                local_txt, target_txt
            ):
                continue
        if is_implausible_corroborator(local_txt, gpt_txt):
            continue
        if is_suspicious_tiny_total(local_amt) and not is_suspicious_tiny_total(gpt_amt):
            continue
        if not candidates_are_independent(cand, gpt_cand):
            continue
        usable_by_family.setdefault(fam, []).append(local_txt)

    if not usable_by_family:
        return False

    for _fam, texts in usable_by_family.items():
        if not any(
            _exact_or_dollar_agree(target_txt, text) and _exact_or_dollar_agree(gpt_txt, text)
            for text in texts
        ):
            return False
    return True


# Back-compat alias used in earlier docs/tests.
line_has_gpt4o_triple_consensus = line_has_gpt4o_local_consensus


def dual_engine_line_fraction(service_lines: list[dict] | None) -> tuple[int, int]:
    """Return (agreed_lines, observed_charge_lines)."""
    agreed = 0
    observed = 0
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        has_charge = any(parse_currency(line.get(k)) is not None for k in _CHARGE_FIELDS)
        if not has_charge:
            continue
        observed += 1
        if line_has_dual_engine_agreement(line):
            agreed += 1
    return agreed, observed


def gpt4o_local_line_fraction(service_lines: list[dict] | None) -> tuple[int, int]:
    """Return (gpt4o+local consensus lines, observed charge lines)."""
    agreed = 0
    observed = 0
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        has_charge = any(parse_currency(line.get(k)) is not None for k in _CHARGE_FIELDS)
        if not has_charge:
            continue
        observed += 1
        if line_has_gpt4o_local_consensus(line):
            agreed += 1
    return agreed, observed


def line_sum_auto_eligible(
    service_lines: list[dict] | None,
    *,
    box28_value: object = None,
    corroborating_values: list[object] | None = None,
) -> tuple[bool, str]:
    """Gate LINE_TOTALS E6 AUTO (fail-closed).

    Eligible when (charge tech stack):
      - every charge line has independent gpt-4o + usable local consensus
        (exact / $1; selected value not gpt-4o-only), or
      - plausible currency-shaped box-28 / DI corroborates the line sum, or
      - multi-line (≥2) and every line has exact dual-engine agreement.

    gpt-4o+local is checked *before* box-28 conflict so weak digits-first box-28
    (222 vs line 200) cannot veto a strong line consensus. Junk box-28 soup is
    ignored. Single-line paddle+rapid alone remains insufficient (hard-15 FA).
    GPT-4o never independently promotes critical charges.
    Never invents Box 28 from Σ — this only gates line-sum E6 when Box 28 is
    empty/absent or independently corroborates.
    """
    hydrate_service_line_charges(service_lines)
    total = line_sum_total(service_lines)
    if total is None:
        return False, "NO_LINE_CHARGES"

    # POS bleed: a lone POS-like amount (11.00) must never AUTO as claim total.
    try:
        from packages.geometry_authority import is_pos_like_currency

        if is_pos_like_currency(total):
            box = parse_currency(box28_value)
            extra = [
                parse_currency(v)
                for v in (corroborating_values or [])
                if parse_currency(v) is not None
            ]
            if box is None and not extra:
                return False, "POS_LIKE_LINE_SUM_REJECTED"
            # Even with corroborators, POS-like totals need non-POS corroboration.
            if box is not None and is_pos_like_currency(format_currency(box)):
                return False, "POS_LIKE_LINE_SUM_REJECTED"
    except Exception:  # noqa: BLE001
        pass

    lines = [ln for ln in (service_lines or []) if isinstance(ln, dict)]
    charge_lines = [
        ln
        for ln in lines
        if any(parse_currency(ln.get(k)) is not None for k in _CHARGE_FIELDS)
    ]

    # Strong line consensus before weak box-28 conflict.
    gpt_agreed, gpt_observed = gpt4o_local_line_fraction(charge_lines)
    if gpt_observed >= 1 and gpt_agreed >= gpt_observed:
        corroborators_pre = []
        for value in [box28_value, *(corroborating_values or [])]:
            parsed = parse_currency(value)
            if parsed is None or is_suspicious_tiny_total(parsed):
                continue
            # Do not ratio-ignore currency-shaped Box 28 here. Near place-shifts
            # like 2004 vs 200 / 1571 vs 157 must CONFLICT, not unlock STP.
            if is_implausible_charge_total(value):
                continue
            corroborators_pre.append(value)
        if corroborators_pre and not any(
            amounts_corroborate_or_cents_twin(total, value) for value in corroborators_pre
        ):
            # Vision + local already agree on the cents-placed amount. An exact
            # ×100 Document Intelligence / box read is the same digits without
            # the column, not a second total.
            if vision_local_decimal_column(total, corroborators_pre):
                return True, "DECIMAL_COLUMN_VISION_LOCAL"
            # Scale twin (×10/×100) of a multi-line gpt/local Σ — same ink class.
            if gpt_observed >= 2 and any(
                is_scale_shift(total, value) or is_decimal_place_shift(total, value)
                for value in corroborators_pre
            ):
                return True, "SCALE_TWIN_BOX28_DEFERRED"
            # Plausible currency-shaped box-28 / DI disagrees → HITL.
            return False, "BOX28_OR_DI_CONFLICT"
        if gpt_observed == 1:
            return True, "SINGLE_LINE_GPT4O_LOCAL"
        return True, "MULTI_LINE_GPT4O_LOCAL"

    corroborators = []
    for value in [box28_value, *(corroborating_values or [])]:
        parsed = parse_currency(value)
        if parsed is None or is_suspicious_tiny_total(parsed):
            continue
        if is_implausible_corroborator(value, total):
            continue
        corroborators.append(value)
    if corroborators:
        if any(amounts_corroborate_or_cents_twin(total, value) for value in corroborators):
            return True, "BOX28_OR_DI_CORROBORATED"
        # Truncated equal-line OCR vs fuller Box 28 (3×200 vs 1200) — Box 28
        # is authority, not a conflicting second total.
        if any(
            incomplete_uniform_line_grid_explains_box28(value, service_lines)
            for value in corroborators
        ) or (
            box28_value is not None
            and incomplete_uniform_line_grid_explains_box28(box28_value, service_lines)
        ):
            return True, "INCOMPLETE_UNIFORM_GRID_BOX28"
        if line_has_vision_and_local_on_selected(
            service_lines, total
        ) and vision_local_decimal_column(total, corroborators):
            return True, "DECIMAL_COLUMN_VISION_LOCAL"
        # Multi-line dual / mixed local with Box 28 ×10/×100 of Σ (EJGE.041
        # 250 vs 25000) — decimal-column / scale soup, not a second total.
        agreed_pre, observed_pre = dual_engine_line_fraction(service_lines)
        gpt_agreed_pre, gpt_observed_pre = gpt4o_local_line_fraction(service_lines)
        mixed_ok = _multi_line_mixed_local_vision(service_lines)
        if (
            observed_pre >= 2
            and (
                agreed_pre >= 1
                or mixed_ok
                or gpt_agreed_pre >= 1
            )
            and (
                vision_local_decimal_column(total, corroborators)
                or any(
                    is_scale_shift(total, value) or is_decimal_place_shift(total, value)
                    for value in corroborators
                )
            )
        ):
            return True, "SCALE_TWIN_BOX28_DEFERRED"
        # DIGIT_DROP_FULLER_LOCAL Σ with Box 28 under-read (+ stem extensions).
        # DJKN.004/007: line 2001 vs Box 28 200; paddle whitelist 2004 is a
        # ×10/digit-drop extension of the truncated Box 28 stem, not of 2001.
        if selected_digit_drop_fuller_line_total(service_lines) == total:
            underread_box = (
                box28_value
                if box28_digit_drop_underread_of_fuller_line(box28_value, service_lines)
                else None
            )
            if underread_box is None:
                for value in corroborators:
                    amt = parse_currency(value)
                    total_amt = parse_currency(total)
                    if (
                        amt is not None
                        and total_amt is not None
                        and amt < total_amt
                        and is_currency_digit_drop_twin(value, total)
                    ):
                        underread_box = value
                        break
            blockers = []
            for value in corroborators:
                if amounts_corroborate_or_cents_twin(total, value):
                    continue
                amt = parse_currency(value)
                total_amt = parse_currency(total)
                if (
                    amt is not None
                    and total_amt is not None
                    and amt < total_amt
                    and is_currency_digit_drop_twin(value, total)
                ):
                    continue
                # Extensions of the truncated Box 28 stem (200 → 2004), including
                # when Box 28 was already deferred away and only 2004 remains.
                if underread_box is not None and (
                    is_currency_digit_drop_twin(value, underread_box)
                    or is_scale_shift(value, underread_box)
                ):
                    continue
                if _is_extension_of_digit_drop_underread_stem(value, total):
                    continue
                blockers.append(value)
            if (underread_box is not None or any(
                _is_extension_of_digit_drop_underread_stem(v, total) for v in corroborators
            )) and not blockers:
                return True, "DIGIT_DROP_BOX28_UNDERREAD"
            if underread_box is not None and not blockers:
                return True, "DIGIT_DROP_BOX28_UNDERREAD"
        # Plausible currency-shaped box-28 / DI disagrees → HITL, not false STP.
        return False, "BOX28_OR_DI_CONFLICT"

    agreed, observed = dual_engine_line_fraction(service_lines)
    if observed == 0:
        return False, "NO_LINE_CHARGES"
    if observed == 1:
        # Single-line DIGIT_DROP_FULLER with no Box 28 corroborators: still needs
        # an under-read Box 28 twin or DI — bare single local stays closed.
        if selected_digit_drop_fuller_line_total(service_lines) == total:
            return False, "SINGLE_LINE_DIGIT_DROP_NEEDS_BOX28_UNDERREAD"
        # Dual-local + Claude lost-decimal twin (130 vs 1300) with empty Box 28
        # — same digit stem, not a second total (M0471JEB.008).
        if agreed >= 1 and parse_currency(box28_value) is None:
            sole = next(
                (
                    ln
                    for ln in (service_lines or [])
                    if isinstance(ln, dict)
                    and any(parse_currency(ln.get(k)) is not None for k in _CHARGE_FIELDS)
                ),
                None,
            )
            if sole is not None and _sole_line_vision_scale_twin_of_dual_local(sole):
                return True, "SINGLE_LINE_DUAL_LOCAL_VISION_SCALE_TWIN"
        # Single-line paddle+rapid alone is insufficient without Box 28 / gpt-4o.
        if agreed >= 1:
            return False, "SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28"
        return False, "SINGLE_LINE_REQUIRES_DI"
    if agreed >= observed >= 2:
        return True, "DUAL_ENGINE_LINE_AGREEMENT"
    # Blind-50 multi-line STP (1851+1551=3402) regressed when a shorter vision
    # crop vetoed each fuller local read. Digit-drop resolution is not the
    # single-line 13↔131 false-accept: that path already returned above.
    if observed >= 2 and _multi_line_digit_drop_resolved(service_lines):
        return True, "MULTI_LINE_DIGIT_DROP_FULLER_LOCAL"
    # Mixed corroboration: every charge line has dual-local OR gpt-4o+local
    # (EJGE.041 150 gpt+rapid + 100 paddle+rapid → Σ 250 vs Box 28 25000).
    if observed >= 2 and _multi_line_mixed_local_vision(service_lines):
        return True, "MULTI_LINE_MIXED_LOCAL_VISION"
    return False, "MULTI_LINE_UNCORROBORATED"


def _multi_line_mixed_local_vision(service_lines: list[dict] | None) -> bool:
    """True when every charge line has dual-local or gpt-4o+local on the selected amount.

    Also accepts SELECTED_LOCAL_CHARGE rows whose ``supporting_engines`` already
    record ≥2 families (selector trusted gpt-4o/paddle/rapid) even when a
    pruned candidate list no longer shows every peer (EJGE.046).
    """
    saw = 0
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        if not any(parse_currency(line.get(k)) is not None for k in _CHARGE_FIELDS):
            continue
        saw += 1
        if line_has_dual_engine_agreement(line) or line_has_gpt4o_local_consensus(line):
            continue
        selection = line.get("line_charge_selection") or {}
        if selection.get("disposition") == "SELECTED_LOCAL_CHARGE":
            engines = {
                str(e or "").casefold()
                for e in (selection.get("supporting_engines") or [])
                if e
            }
            has_local = any("paddle" in e or "rapid" in e for e in engines)
            if has_local and len(engines) >= 2:
                continue
        return False
    return saw >= 2


def _multi_line_digit_drop_resolved(service_lines: list[dict] | None) -> bool:
    """True when every charge line kept the fuller local read over a short vision rival."""
    saw_drop = False
    for line in service_lines or []:
        if not isinstance(line, dict):
            continue
        if not any(parse_currency(line.get(k)) is not None for k in _CHARGE_FIELDS):
            continue
        selection = line.get("line_charge_selection") or {}
        if selection.get("disposition") != "SELECTED_LOCAL_CHARGE":
            return False
        if selection.get("reason") in {
            "DIGIT_DROP_FULLER_LOCAL",
            "MULTI_LINE_GEOMETRY_DIGIT_DROP",
        }:
            saw_drop = True
            continue
        if not line_has_dual_engine_agreement(line):
            return False
    return saw_drop
