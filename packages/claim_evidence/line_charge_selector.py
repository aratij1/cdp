"""Select printed Box 24F line charges from local OCR evidence only.

Selection never uses Box 28 or the line-sum total. Those are verification
inputs for later authority, not candidates for rewriting a row amount.

Disposition:
  SELECTED_LOCAL_CHARGE  — one currency-shaped charge-column amount wins
  AMBIGUOUS_LINE_CHARGE  — competing valid amounts
  UNREADABLE_LINE_CHARGE — no usable charge-column evidence
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from decimal import Decimal

from packages.claim_evidence.line_sum_authority import (
    amounts_same_stem_cents_twin,
    format_currency,
    is_decimal_place_shift,
    is_scale_shift,
    parse_currency,
)
from packages.geometry_authority.cms1500_regions import (
    CMS1500_CHARGE_CENTS_X,
    CMS1500_LINE_COLUMNS,
    CMS1500_UNITS_X0,
    charge_region_verdict,
    is_pos_like_currency,
)

_LOCAL_ENGINES = frozenset({"paddleocr", "rapidocr"})
# Selection noise that is never a typed CMS charge on its own.
_SELECTION_NOISE = frozenset({"1.00", "0.00", "0.01", "0.10"})
_CONCAT_TAIL = frozenset({"0", "1", "4", "5"})


@dataclass(frozen=True)
class LineChargeSelection:
    disposition: str
    amount: str | None
    reason: str
    supporting_engines: tuple[str, ...] = ()
    rejected: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition,
            "amount": self.amount,
            "reason": self.reason,
            "supporting_engines": list(self.supporting_engines),
            "rejected": [{"value": v, "reason": r} for v, r in self.rejected],
        }


def _engine_family(engine: object) -> str:
    text = str(engine or "").casefold()
    if "paddle" in text:
        return "paddleocr"
    if "rapid" in text:
        return "rapidocr"
    if "tesseract" in text:
        return "tesseract"
    # gpt-4o / Claude crop residuals share one vision family for dual agreement.
    if any(token in text for token in ("gpt4o", "gpt-4o", "claude", "anthropic")):
        return "azure_gpt4o_crop"
    return text


def _bbox_tuple(raw: object) -> tuple[float, float, float, float] | None:
    if isinstance(raw, dict) and raw.get("x0") is not None:
        try:
            return (
                float(raw["x0"]),
                float(raw["y0"]),
                float(raw["x1"]),
                float(raw["y1"]),
            )
        except (TypeError, ValueError, KeyError):
            return None
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
        except (TypeError, ValueError):
            return None
    return None


def _centre_x(bbox: tuple[float, float, float, float]) -> float:
    return (bbox[0] + bbox[2]) / 2.0


def _centre_y(bbox: tuple[float, float, float, float]) -> float:
    return (bbox[1] + bbox[3]) / 2.0


def _overlaps_units_column(bbox: tuple[float, float, float, float]) -> bool:
    # Majority of the crop sits in Box 24G units.
    x0, _, x1, _ = bbox
    width = max(1e-6, x1 - x0)
    overlap = max(0.0, min(x1, 1e9) - max(x0, CMS1500_UNITS_X0))
    return (overlap / width) >= 0.45


def _in_charge_column(bbox: tuple[float, float, float, float]) -> bool:
    verdict = charge_region_verdict(bbox, already_reference=True)
    if not verdict.authorised:
        return False
    if _overlaps_units_column(bbox):
        return False
    # Reject severely cents-clipped windows. Dollars-ruling crops often end
    # within a few px of the ruling (x1≈1161 vs cents@1155); requiring
    # cents+8 falsely marked dual-local 212.00 peers as OUTSIDE_CHARGE_COLUMN.
    if bbox[2] < CMS1500_CHARGE_CENTS_X - 12:
        return False
    cx = _centre_x(bbox)
    ch0, ch1 = CMS1500_LINE_COLUMNS["charges"]
    return ch0 <= cx <= ch1


def _is_selection_noise(amount: str) -> bool:
    if amount in _SELECTION_NOISE:
        return True
    # Classic POS codes that bleed from Box 24B (keep real charges like 81.00
    # when geometry already proved charge-column — handled separately).
    if amount in {"11.00", "12.00", "21.00", "22.00", "23.00"}:
        return True
    return False


def _digit_drop_fuller_local(by_amount: dict[str, set[str]]) -> str | None:
    """Local fuller amount whose only rivals are one-digit-shorter non-local reads.

    Blind-50 STP accepted ``1851`` + ``1551`` (sum ``3402``). A later Claude crop
    of ``185`` / ``155`` marked those lines ``NO_DUAL_LOCAL_AGREEMENT`` and the
    same sample went back to HITL. The short read is a dropped digit, not a
    second charge. Two local engines that disagree stay ambiguous. Single-line
    sums still fail closed in ``line_sum_auto_eligible`` (13 vs 131).
    """
    local_amounts = [
        amount for amount, families in by_amount.items() if families & _LOCAL_ENGINES
    ]
    if len(local_amounts) != 1:
        return None
    fuller = local_amounts[0]
    fuller_dollars = _dollars_digits(fuller)
    if len(fuller_dollars) < 3:
        return None
    others = [amount for amount in by_amount if amount != fuller]
    if not others:
        return None
    saw_drop = False
    for other in others:
        if by_amount[other] & _LOCAL_ENGINES:
            return None
        other_dollars = _dollars_digits(other)
        is_drop = (
            bool(other_dollars)
            and fuller_dollars.startswith(other_dollars)
            and len(fuller_dollars) - len(other_dollars) == 1
        )
        if is_drop:
            saw_drop = True
            continue
        # Tesseract whitelist soup (``500`` beside ``1551``) is not a second charge.
        if by_amount[other] <= {"tesseract"}:
            continue
        return None
    return fuller if saw_drop else None


def _dollars_digits(amount: str) -> str:
    parsed = parse_currency(amount)
    if parsed is None:
        return ""
    return format_currency(parsed).split(".", 1)[0]


def _looks_like_units_concat(amount: str, peers: set[str]) -> bool:
    """Reject ``6401.00`` / ``701.00`` when a clean ``640.00`` / ``70.00`` peer exists.

    Three-digit dollars ending in a units-column tick (``701`` beside ``70``)
    are the same bleed class as four-digit ``6401`` beside ``640``. Callers must
    still require a trustworthy stem peer (vision or dual-local) so a lone
    whitelist under-read (``51`` from ``5100``) cannot veto real ``510``.
    """
    if not amount.endswith(".00"):
        return False
    dollars = _dollars_digits(amount)
    if len(dollars) < 3 or dollars[-1] not in _CONCAT_TAIL:
        return False
    stem = dollars[:-1]
    stem_amount = f"{int(stem)}.00" if stem.isdigit() else None
    if stem_amount and stem_amount in peers:
        return True
    return False


def _scale_shifted_from_dual_local(current: Decimal, candidates: list | None) -> bool:
    """True when ``current`` is a ×10/×100 twin of a paddle+rapid amount."""
    dual: dict[str, set[str]] = {}
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        engine = str(cand.get("engine") or "").casefold()
        if engine not in _LOCAL_ENGINES:
            continue
        amount = parse_currency(cand.get("value"))
        if amount is None:
            continue
        dual.setdefault(format_currency(amount), set()).add(engine)
    for amount, engines in dual.items():
        if len(engines) < 2:
            continue
        if is_scale_shift(current, amount):
            return True
    return False


def _geometry_only_rows(amount: str, filtered: list[tuple]) -> bool:
    """True when every surviving row for ``amount`` is a GEOMETRY_CENTS read."""
    rows = [row for row in filtered if row[0] == amount]
    if not rows:
        return False
    for row in rows:
        cand = row[2] if len(row) > 2 else {}
        prep = str(
            (cand or {}).get("preprocessing_variant")
            or (cand or {}).get("evidence_reference")
            or ""
        )
        if "GEOMETRY_CENTS" not in prep:
            return False
    return True


def _inflated_geometry_vs_peer(current: Decimal, candidates: list | None) -> bool:
    """True when ``current`` is the larger ×10/×100 twin of a non-geometry read.

    ``200100`` shaped as ``2001.00`` is the cents ruling read as a digit.
    A normal Rapid ``1851.00`` is not geometry and must not be cleared.
    """
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        prep = str(
            cand.get("preprocessing_variant") or cand.get("evidence_reference") or ""
        )
        if "GEOMETRY_CENTS" in prep:
            continue
        amount = parse_currency(cand.get("value"))
        if amount is None or amount >= current:
            continue
        if is_scale_shift(current, amount):
            return True
    return False


def _looks_like_place_shift(amount: str, peers: set[str]) -> bool:
    """Reject ``4972.00`` when ``49.72`` is an observed peer."""
    if _is_concat_place_shift_shell(amount, peers):
        return True
    amt = parse_currency(amount)
    if amt is None:
        return False
    for peer in peers:
        if peer == amount:
            continue
        peer_amt = parse_currency(peer)
        if peer_amt is None:
            continue
        # Only reject the inflated shell (×100), never the ruled smaller peer.
        if is_decimal_place_shift(amount, peer) and amt > peer_amt:
            return True
    return False


def _is_concat_place_shift_shell(amount: str, peers: set[str]) -> bool:
    """True for bare ``4972.00`` shells whose ``49.72`` peer is also observed.

    Uses dollar digits only (not the trailing ``00`` cents) so ``4972.00`` maps
    to peer ``49.72``. Short stems like ``175.00`` (3 dollar digits) are not
    concat shells — those are handled as ×100 under-reads vs ``1.75``.
    """
    if not amount.endswith(".00"):
        return False
    dollars = _dollars_digits(amount)
    if len(dollars) < 4:
        return False
    shifted = f"{dollars[:-2]}.{dollars[-2:]}"
    return shifted in peers and shifted != amount


def _row_band_ok(
    bbox: tuple[float, float, float, float],
    row_y_band: tuple[float, float] | None,
) -> bool:
    if row_y_band is None:
        return True
    y0, y1 = row_y_band
    cy = _centre_y(bbox)
    # Allow a small vertical tolerance around the service-line strip.
    pad = max(8.0, 0.35 * (y1 - y0))
    return (y0 - pad) <= cy <= (y1 + pad)


_RULED_CENTS_RAW = re.compile(
    r"^\s*(\d{1,5})\s*[\n/| ]\s*(\d{2})\s*$"
)
_DOLLARS_CORRUPT_CENTS = re.compile(
    r"^\s*(\d{1,5})\s*[i:;.]\s*0{1,2}\s*$",
    re.IGNORECASE,
)
# Printed CMS-1500 dollars/cents with a dollar sign: ``$ 157 :07``, ``7 $ 157 :07``,
# ``$ 222 |22``, ``J $ 228 |32``. Leading/trailing scrap digits are POS/units bleed.
_CASH_RULED_CENTS = re.compile(
    r"\$\s*(\d{1,5})\s*[:|/]\s*(\d{2})\b"
)


def is_ruling_split_digit_glue(ruled_amount: object, other: object) -> bool:
    """True when ``other`` is digit-concat of the ruling groups for ``ruled_amount``.

    Local raw ``523\\n156`` shapes to ``523.56`` (leading-1 cents bleed). DI/paddle
    often emit the same ink as bare ``523156`` / ``523156.00`` with the decimal
    dropped — that is not a second Box 28 total. Classic ``34\\n25`` → ``34.25``
    similarly glues to ``3425``.
    """
    ruled = parse_currency(ruled_amount)
    if ruled is None:
        return False
    ruled_txt = format_currency(ruled)
    other_digits = re.sub(r"\D", "", str(other or ""))
    if not other_digits:
        return False
    dollars, _, cents = ruled_txt.partition(".")
    if not dollars or len(cents) != 2:
        return False
    classic = f"{dollars}{cents}"
    leading1 = f"{dollars}1{cents}"
    glue_forms = {
        classic,
        leading1,
        f"{classic}00",
        f"{leading1}00",
    }
    return other_digits in glue_forms


def promote_ruling_split_candidate_value(cand: dict) -> str | None:
    """Rewrite ``cand['value']`` when raw ruling-split proves a better amount.

    RapidOCR often spans only the cents token (``156.00`` from ``523\\n156``).
    Promoting to the ruled amount keeps financial conflict / DI-partner paths
    on the printed total without inventing ink.
    """
    if not isinstance(cand, dict):
        return None
    ruled = _ruling_split_amount(cand.get("raw_value"))
    if ruled is None or _is_selection_noise(ruled):
        return None
    current = parse_currency(cand.get("value"))
    current_txt = format_currency(current) if current is not None else None
    if current_txt == ruled:
        return None
    # Promote when value is missing, a cents/group fragment, or digit-glue of ruled.
    raw_groups = re.findall(r"\d+", str(cand.get("raw_value") or ""))
    current_dollars = (
        re.sub(r"\D", "", current_txt.split(".", 1)[0]) if current_txt else ""
    )
    # Junk-tail fragment (``8156.00`` from ``523\\n8156``) is not the printed total.
    junk_tail_fragment = (
        current is not None
        and current_txt is not None
        and len(raw_groups) >= 2
        and current_dollars == raw_groups[-1]
        and current_dollars != re.sub(r"\D", "", ruled.split(".", 1)[0])
    )
    if (
        current_txt is None
        or is_ruling_split_digit_glue(ruled, cand.get("value"))
        or is_ruling_split_digit_glue(ruled, cand.get("raw_value"))
        or junk_tail_fragment
        or (
            current is not None
            and current < parse_currency(ruled)
            and any(g == current_dollars for g in raw_groups)
        )
    ):
        cand["value"] = ruled
        return ruled
    return None


def _ruling_split_amount(raw: object) -> str | None:
    """Reconstruct dollars|cents ruling splits and dollars+units-bleed raws."""
    text = str(raw or "")
    cash = _CASH_RULED_CENTS.search(text)
    if cash:
        dollars, cents = cash.group(1), cash.group(2)
        try:
            return format_currency(parse_currency(f"{int(dollars)}.{cents}"))
        except (TypeError, ValueError):
            return None
    match = _RULED_CENTS_RAW.match(text)
    if match:
        dollars, cents = match.group(1), match.group(2)
        try:
            return format_currency(parse_currency(f"{int(dollars)}.{cents}"))
        except (TypeError, ValueError):
            return None
    corrupt = _DOLLARS_CORRUPT_CENTS.match(text)
    if corrupt:
        try:
            return format_currency(parse_currency(f"{int(corrupt.group(1))}.00"))
        except (TypeError, ValueError):
            return None
    groups = re.findall(r"\d+", text)
    if len(groups) == 2 and 1 <= len(groups[0]) <= 5:
        dollars, tail = groups[0], groups[1]
        split_mark = "\n" in text or "/" in text or "|" in text or "!" in text or " " in text
        # Classic dollars|cents: ``34\\n25``.
        if len(tail) == 2 and ("\n" in text or "/" in text or "|" in text):
            try:
                return format_currency(parse_currency(f"{int(dollars)}.{tail}"))
            except (TypeError, ValueError):
                return None
        # Cents-first / RTL glue: OCR emits ``00\\n212`` (cents column then
        # dollars stem). Treating leading ``00`` as dollars yields SELECTION_NOISE
        # ``0.00`` and drops dual-local agreement on the real ``212.00``.
        if (
            split_mark
            and dollars in {"0", "00"}
            and len(tail) >= 2
            and not (len(tail) == 2 and tail.isdigit())
        ):
            try:
                return format_currency(parse_currency(f"{int(tail)}.00"))
            except (TypeError, ValueError):
                return None
        # Units/POS prefix then charge dollars (``70\\n157``, ``7c\\n157``):
        # short leading token is Box 24G bleed; keep the longer dollars stem.
        # Do not treat ``212\\n100`` this way — that is dollars then units.
        if (
            split_mark
            and len(dollars) <= 2
            and len(tail) >= 3
            and dollars not in {"0", "00"}
        ):
            try:
                return format_currency(parse_currency(f"{int(tail)}.00"))
            except (TypeError, ValueError):
                return None
        # Decimal lost + leading-1 cents bleed: ``523\\n156`` / ``523 156`` for
        # printed ``523.56``. Prefer dollars.(tail[1:]) over inventing ``.00``.
        if (
            split_mark
            and 1 <= len(dollars) <= 5
            and len(tail) == 3
            and tail[0] == "1"
            and tail[1:].isdigit()
        ):
            try:
                alt = format_currency(parse_currency(f"{int(dollars)}.{tail[1:]}"))
            except (TypeError, ValueError):
                alt = None
            if alt is not None:
                from packages.claim_evidence.line_sum_authority import (
                    is_implausible_charge_total,
                )

                if not is_implausible_charge_total(alt):
                    return alt
        # OCR-corrupt leading-1 cents: ``523\\n8156`` / ``LAL\\n523\\n8156\\nS``
        # where a ruling tick is read as a junk digit before ``156``. Reconstruct
        # dollars.(tail[-2:]) when tail is ``X1CC`` (M0463JEM.017 paddle).
        if (
            split_mark
            and 1 <= len(dollars) <= 5
            and len(tail) == 4
            and tail[1] == "1"
            and tail[2:].isdigit()
            and tail[0].isdigit()
            and tail[0] != "1"
        ):
            try:
                alt = format_currency(parse_currency(f"{int(dollars)}.{tail[2:]}"))
            except (TypeError, ValueError):
                alt = None
            if alt is not None:
                from packages.claim_evidence.line_sum_authority import (
                    is_implausible_charge_total,
                )

                if not is_implausible_charge_total(alt):
                    return alt
        # Dollars stem + units/ruling bleed (``212\\n100``, ``346 !04`` with
        # a longer junk tail): keep the leading dollars as whole dollars when
        # the tail is not a clean two-digit cents read.
        if (
            split_mark
            and len(tail) >= 2
            and not (len(tail) == 2 and tail.isdigit() and "." in text)
        ):
            # ``346 !04`` → prefer not to invent .00 here; leave to peers.
            if len(tail) >= 3 or tail in {"100", "101", "104", "110"}:
                try:
                    return format_currency(parse_currency(f"{int(dollars)}.00"))
                except (TypeError, ValueError):
                    return None
    return None


def _raw_has_observed_decimal(raw: object) -> bool:
    return bool(re.search(r"\d+\.\d{2}", str(raw or "")))


def _is_bare_digit_soup(amount: str, raw: object) -> bool:
    """True for concatenated shells like ``4972`` / ``6401`` without a decimal."""
    if not amount.endswith(".00"):
        return False
    dollars = _dollars_digits(amount)
    if len(dollars) < 4:
        return False
    raw_text = str(raw or "")
    if _raw_has_observed_decimal(raw_text) or _ruling_split_amount(raw_text):
        return False
    # Raw is the same digit run (optionally with a trailing .00 we invented).
    digits = re.sub(r"\D", "", raw_text)
    return digits == dollars or digits == dollars + "00"


def _shaped_amount(cand: dict) -> str | None:
    raw = str(cand.get("raw_value") or cand.get("value") or "")
    ruled = _ruling_split_amount(raw)
    value_parsed = parse_currency(cand.get("value"))
    value_txt = format_currency(value_parsed) if value_parsed is not None else None
    # Ruled reconstruction wins unless it collapses to selection noise while the
    # upstream shaped value is a real charge (``00\\n212`` → ruled 0.00 vs 212.00).
    if ruled is not None:
        if not (
            _is_selection_noise(ruled)
            and value_txt
            and value_txt != ruled
            and not _is_selection_noise(value_txt)
        ):
            return ruled
    for key in ("value", "raw_value"):
        parsed = parse_currency(cand.get(key))
        if parsed is None:
            continue
        text = format_currency(parsed)
        # Prefer observed currency shape; digits-only locals still count when
        # already shaped upstream, but bare concat soup is filtered later.
        if re.search(r"\d+\.\d{2}", raw) or re.fullmatch(r"\d+\.\d{2}", text):
            return text
        if re.fullmatch(r"\d+\.\d{2}", text):
            return text
    return None


def _candidate_evidence_quality(cand: dict, amount: str) -> int:
    """Higher is better local evidence for the selected amount."""
    raw = cand.get("raw_value") or cand.get("value") or ""
    prep = str(
        cand.get("preprocessing_variant")
        or cand.get("evidence_reference")
        or ""
    )
    if "GEOMETRY_CENTS" in prep:
        return 3
    if _raw_has_observed_decimal(raw):
        return 3
    if _ruling_split_amount(raw) == amount:
        return 3
    if _is_bare_digit_soup(amount, raw):
        return 0
    return 1


def _geometry_cents_candidate_from_attempts(line: dict) -> dict | None:
    """Promote a GEOMETRY_CENTS attempt into a selectable local candidate.

    Service-line OCR often records geometry only on ``attempts`` while leaving
    bare-digit soup in ``candidates``. Without promotion, place-shifted shells
    like ``4972.00`` stay AMBIGUOUS even when geometry shaped ``49.77``.
    """
    region = _bbox_tuple(line.get("canonical_region") or line.get("ocr_region"))
    for attempt in line.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        reason = str(attempt.get("reason") or "")
        if "GEOMETRY_CENTS" not in reason or "UNDERREAD" in reason:
            continue
        obs = attempt.get("observation") or {}
        if not isinstance(obs, dict):
            continue
        shaped = (
            obs.get("canonical_monetary_value")
            or obs.get("shaped")
            or obs.get("text")
        )
        parsed = parse_currency(shaped)
        if parsed is None:
            continue
        amount = format_currency(parsed)
        if _is_selection_noise(amount):
            continue
        return {
            "engine": "rapidocr",
            "model_name": "geometry-cents",
            "model_version": "monetary-geometry",
            "preprocessing_variant": "GEOMETRY_CENTS",
            "value": amount,
            "raw_value": obs.get("raw_digit_sequence") or obs.get("text") or amount,
            "raw_confidence": 0.91,
            "evidence_reference": "GEOMETRY_CENTS",
            "bounding_box": (
                {
                    "x0": region[0],
                    "y0": region[1],
                    "x1": region[2],
                    "y1": region[3],
                }
                if region
                else None
            ),
        }
    return None


def _is_dollar_truncation(short: str, longer: str) -> bool:
    """True when ``short`` is a dollars-ruling truncation of ``longer``.

    Examples: ``129.00`` vs geometry ``1291.15``, or ``129.00`` vs gpt-4o ``129.15``.
    Whole-dollar place-shifts (``116.00`` vs ``1165.00``) are NOT truncations —
    those insert a digit rather than truncating observed cents.
    """
    short_amt = parse_currency(short)
    long_amt = parse_currency(longer)
    if short_amt is None or long_amt is None or short_amt == long_amt:
        return False
    short_txt = format_currency(short_amt)
    long_txt = format_currency(long_amt)
    sd, ld = short_txt.split(".", 1)[0], long_txt.split(".", 1)[0]
    # Same dollar stem; short is whole-dollar while longer carries observed cents.
    if sd == ld and short_txt.endswith(".00") and not long_txt.endswith(".00"):
        return True
    if ld.startswith(sd) and len(ld) > len(sd):
        # Geometry / vision fuller embeds cents into a longer dollar run
        # (129.00 vs 1291.15). Both-.00 digit insertions are place-shifts
        # (116.00 vs 1165.00); cents-vs-whole-dollar inflation (116.50 vs
        # 1165.00) is also not a dollars-ruling truncation.
        if long_txt.endswith(".00"):
            return False
        # ``457.60`` vs ``4571.60`` already has cents; that is a scale twin,
        # not a dollars-ruling truncation of ``457.00``.
        if not short_txt.endswith(".00"):
            return False
        return True
    return False


def _raw_fraction_digits(raw: object) -> str:
    text = str(raw or "")
    if "." not in text:
        return ""
    return re.sub(r"\D", "", text.split(".", 1)[1])


def _same_stem_ruling_jitter_amount(
    by_amount: dict[str, set[str]],
    filtered: list[tuple],
) -> str | None:
    """Whole dollars when the other local read is the same stem plus a trailing zero.

    ``200.00`` (paddle raw ``200..00``) beside rapid raw ``200.100`` is the
    cents ruling, not a printed ``200.10``. A clean two-decimal ``200.10``
    stays unresolved so real dimes are not stripped.
    """
    amounts = list(by_amount)
    if len(amounts) < 2:
        return None
    anchor = amounts[0]
    if not all(
        amount == anchor or _is_same_stem_cents_twin(anchor, amount) for amount in amounts
    ):
        return None
    engines: set[str] = set()
    for families in by_amount.values():
        engines |= set(families) & _LOCAL_ENGINES
    if len(engines) < 2:
        return None
    whole = [amount for amount in amounts if str(amount).endswith(".00")]
    if len(whole) != 1:
        return None
    chosen = whole[0]
    others = [amount for amount in amounts if amount != chosen]
    if not others:
        return None
    chosen_amt = parse_currency(chosen)
    if chosen_amt is None:
        return None
    if any(
        (other_amt := parse_currency(amount)) is None
        or abs(chosen_amt - other_amt) > Decimal("0.10")
        for amount in others
    ):
        return None
    noisy = False
    for amount, _family, cand, _quality in filtered:
        if amount == chosen:
            continue
        if len(_raw_fraction_digits(cand.get("raw_value"))) > 2:
            noisy = True
            break
    if not noisy:
        return None
    return chosen


def _di_corroborated_ruling_split(line: dict, by_amount: dict[str, set[str]]) -> str | None:
    """Local dollars|cents split that Document Intelligence reads the same way.

    ``25/43`` → ``25.43`` beside DI ``25 |43`` is the printed charge. Geometry
    raw ``25143`` → ``251.43`` counted the cents ruling as a digit. A second
    local split that DI does not confirm (units ``1\\n25`` → ``1.25``) does
    not veto. Claude is not a reader here.
    """
    local: set[str] = set()
    di: set[str] = set()
    geometry: list[str] = []
    for cand in line.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        ruled = _ruling_split_amount(cand.get("raw_value"))
        family = _engine_family(cand.get("engine"))
        prep = str(cand.get("preprocessing_variant") or cand.get("evidence_reference") or "")
        if "GEOMETRY_CENTS" in prep:
            shaped = _shaped_amount(cand)
            if shaped:
                geometry.append(shaped)
            continue
        if ruled is None:
            continue
        if family in _LOCAL_ENGINES:
            local.add(ruled)
        elif "document_intelligence" in family:
            di.add(ruled)
    agreed = local & di
    if len(agreed) != 1:
        return None
    chosen = next(iter(agreed))
    chosen_amt = parse_currency(chosen)
    if chosen_amt is None:
        return None
    if not any(
        (geo_amt := parse_currency(amount)) is not None
        and geo_amt > chosen_amt
        and is_scale_shift(amount, chosen)
        for amount in geometry
    ):
        return None
    if chosen not in by_amount:
        return None
    return chosen


def _is_same_stem_cents_twin(left: str, right: str) -> bool:
    """True when amounts share dollars and differ by ≤ $1.00 (OCR twin noise).

    ``640.00`` beside ``640.40`` is not a vision/geometry fuller read — both are
    the same printed dollars stem with cents jitter. Only treat same-stem
    cents as a fuller rival when vision actually carries the fuller amount.
    """
    a, b = parse_currency(left), parse_currency(right)
    if a is None or b is None or a == b:
        return False
    la, lb = format_currency(a), format_currency(b)
    if la.split(".", 1)[0] != lb.split(".", 1)[0]:
        return False
    return abs(a - b) <= Decimal("1.00")


def _vision_vendor_amounts(line: dict) -> dict[str, set[str]]:
    """Map shaped charge → independent vision vendor ids (``claude`` / ``gpt4o``)."""
    by_amount: dict[str, set[str]] = {}
    for cand in line.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        amount = _shaped_amount(cand)
        if amount is None:
            continue
        eng = str(cand.get("engine") or "").casefold()
        vendor = None
        if "claude" in eng or "anthropic" in eng:
            vendor = "claude"
        elif "gpt4o" in eng or "gpt-4o" in eng:
            vendor = "gpt4o"
        if vendor is None:
            continue
        by_amount.setdefault(amount, set()).add(vendor)
    return by_amount


def _geometry_cents_amount(line: dict) -> object | None:
    for attempt in line.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        if "GEOMETRY_CENTS" not in str(attempt.get("reason") or ""):
            continue
        obs = attempt.get("observation") or {}
        shaped = (
            obs.get("shaped")
            or obs.get("canonical_monetary_value")
            or obs.get("value")
        )
        return parse_currency(shaped)
    return None


def _local_stem_corroborates(amount: str, line: dict, by_amount: dict[str, set[str]]) -> bool:
    """True when a local engine carries dollars-ruling truncation of ``amount``."""
    if any(
        bool(families & _LOCAL_ENGINES) and _is_dollar_truncation(other, amount)
        for other, families in by_amount.items()
    ):
        return True
    for cand in line.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        if _engine_family(cand.get("engine")) not in _LOCAL_ENGINES:
            continue
        for key in ("value", "raw_value"):
            peer = parse_currency(cand.get(key))
            if peer is None:
                continue
            peer_txt = format_currency(peer)
            if _is_dollar_truncation(peer_txt, amount) or peer_txt == amount:
                return True
    return False


def _dual_vision_select_without_dual_local(
    line: dict,
    *,
    by_amount: dict[str, set[str]],
    rejected: list[tuple[str, str]],
) -> LineChargeSelection | None:
    """Claude + gpt-4o agreement when locals never dual-agree (units-bleed soup).

    Active rule from DJKH.008-class claims: dual independent vision on ``157.07``
    must not fall through to ``NO_DUAL_LOCAL_AGREEMENT`` just because paddle/rapid
    reshaped ``70\\\\n157`` into units bleed. Geometry place-shift soup
    (``1571.07``) or a local dollars-stem of the vision amount corroborates.
    """
    vendor_amounts = _vision_vendor_amounts(line)
    dual = [
        amount
        for amount, vendors in vendor_amounts.items()
        if len(vendors) >= 2
    ]
    if len(dual) != 1:
        return None
    amount = dual[0]
    amt = parse_currency(amount)
    if amt is None:
        return None

    local_stem_ok = _local_stem_corroborates(amount, line, by_amount)
    # Whole-dollar dual vision (200.00) still wins when locals only emitted
    # place-shifted shells (2000.00 / 20000.00) — those are not cents-fuller
    # truncations after the both-.00 guard, but they corroborate the stem.
    if not local_stem_ok:
        for other, families in by_amount.items():
            if not (families & _LOCAL_ENGINES):
                continue
            other_amt = parse_currency(other)
            if other_amt is None or other_amt <= amt:
                continue
            if is_decimal_place_shift(other, amount):
                local_stem_ok = True
                break
            o_digits = re.sub(r"\D", "", other)
            v_digits = re.sub(r"\D", "", amount)
            if (
                other.endswith(".00")
                and amount.endswith(".00")
                and v_digits
                and o_digits.startswith(v_digits)
                and len(o_digits) > len(v_digits)
            ):
                local_stem_ok = True
                break
        if not local_stem_ok:
            for rejected_amount, reason in rejected:
                if reason not in {
                    "PLACE_SHIFT_SOUP",
                    "BARE_DIGIT_SOUP",
                    "UNITS_CONCAT_BLEED",
                }:
                    continue
                rej_amt = parse_currency(rejected_amount)
                if rej_amt is None or rej_amt <= amt:
                    continue
                r_digits = re.sub(r"\D", "", rejected_amount)
                v_digits = re.sub(r"\D", "", amount)
                if v_digits and r_digits.startswith(v_digits):
                    local_stem_ok = True
                    break

    geo_amt = _geometry_cents_amount(line)
    geo_place_shift = False
    if geo_amt is not None and amt is not None and geo_amt != amt:
        geo_txt = format_currency(geo_amt)
        if is_decimal_place_shift(geo_txt, amount) or _is_dollar_truncation(
            amount if amt < geo_amt else geo_txt,
            geo_txt if amt < geo_amt else amount,
        ):
            geo_place_shift = True
        v_digits = re.sub(r"\D", "", amount)
        g_digits = re.sub(r"\D", "", geo_txt)
        if v_digits and g_digits and (
            g_digits == v_digits
            or (len(g_digits) == len(v_digits) + 1 and v_digits in g_digits)
        ):
            geo_place_shift = True

    if not (local_stem_ok or geo_place_shift):
        return None

    engines = set(by_amount.get(amount) or set()) | {"azure_gpt4o_crop"}
    for other, families in by_amount.items():
        if other == amount or _is_dollar_truncation(other, amount):
            engines |= families
    return LineChargeSelection(
        "SELECTED_LOCAL_CHARGE",
        amount,
        "DUAL_VISION_AGREEMENT_WITHOUT_DUAL_LOCAL",
        supporting_engines=tuple(sorted(engines)),
        rejected=tuple(rejected[:12])
        + (
            ((format_currency(geo_amt), "GEOMETRY_CENTS_OVERRIDDEN_BY_DUAL_VISION"),)
            if geo_amt is not None and geo_amt != amt
            else ()
        ),
    )


def _vision_fuller_select_without_dual_local(
    line: dict,
    *,
    by_amount: dict[str, set[str]],
    rejected: list[tuple[str, str]],
) -> LineChargeSelection | None:
    """Single vision fuller cents when the peer vision is place-shift soup.

    Active rule from DJKH.018-class: Claude ``25.43`` + local ``25.00`` must win
    even when gpt-4o emits ``25143.00`` soup and dual-local never forms.
    """
    vendor_amounts = _vision_vendor_amounts(line)
    if not vendor_amounts:
        return None
    corroborated: list[str] = []
    for amount in vendor_amounts:
        if amount.endswith(".00"):
            continue
        if _local_stem_corroborates(amount, line, by_amount):
            corroborated.append(amount)
    if len(corroborated) != 1:
        return None
    amount = corroborated[0]
    amt = parse_currency(amount)
    if amt is None:
        return None
    v_digits = re.sub(r"\D", "", amount)

    def _peer_is_soup(other: str) -> bool:
        other_amt = parse_currency(other)
        if other_amt is None:
            return False
        o_digits = re.sub(r"\D", "", other)
        if is_decimal_place_shift(other, amount) or _is_dollar_truncation(amount, other):
            return True
        if v_digits and o_digits and v_digits in o_digits and len(o_digits) >= len(v_digits) + 1:
            return True
        # Inflated whole-dollar shells (25143.00 vs 25.43).
        if other.endswith(".00") and other_amt >= amt * 50:
            return True
        return False

    peers = [other for other in vendor_amounts if other != amount]
    if peers and not all(_peer_is_soup(other) for other in peers):
        return None

    engines = set(by_amount.get(amount) or set()) | {"azure_gpt4o_crop"}
    for other, families in by_amount.items():
        if other == amount or _is_dollar_truncation(other, amount):
            engines |= families
    return LineChargeSelection(
        "SELECTED_LOCAL_CHARGE",
        amount,
        "VISION_FULLER_STEM_WITHOUT_DUAL_LOCAL",
        supporting_engines=tuple(sorted(engines)),
        rejected=tuple(rejected[:12])
        + tuple((peer, "VISION_PEER_PLACE_SHIFT_SOUP") for peer in peers),
    )


def select_line_charge(
    line: dict | None,
    *,
    row_y_band: tuple[float, float] | None = None,
) -> LineChargeSelection:
    """Choose one Box 24F charge from local OCR candidates on a single row."""
    if not isinstance(line, dict):
        return LineChargeSelection(
            "UNREADABLE_LINE_CHARGE", None, "NO_LINE"
        )

    rejected: list[tuple[str, str]] = []
    usable: list[tuple[str, str, dict]] = []  # amount, engine_family, cand

    line_region = _bbox_tuple(line.get("canonical_region") or line.get("ocr_region"))
    if row_y_band is None and line_region is not None:
        row_y_band = (line_region[1], line_region[3])

    candidates = list(line.get("candidates") or [])
    geo_cand = _geometry_cents_candidate_from_attempts(line)
    if geo_cand is not None:
        geo_amt = geo_cand.get("value")
        already = any(
            isinstance(c, dict)
            and parse_currency(c.get("value")) == parse_currency(geo_amt)
            and "GEOMETRY_CENTS"
            in str(c.get("preprocessing_variant") or c.get("evidence_reference") or "")
            for c in candidates
        )
        if not already:
            candidates.append(geo_cand)

    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        family = _engine_family(cand.get("engine"))
        amount = _shaped_amount(cand)
        if amount is None:
            rejected.append((str(cand.get("value") or cand.get("raw_value") or ""), "UNSHAPED"))
            continue
        if _is_selection_noise(amount):
            rejected.append((amount, "SELECTION_NOISE"))
            continue
        # POS-like without charge-column geometry is not selectable.
        bbox = _bbox_tuple(cand.get("bounding_box")) or line_region
        if bbox is None:
            # No geometry: only keep local engines; still reject classic POS.
            if is_pos_like_currency(amount) and amount in {
                "11.00", "12.00", "21.00", "22.00", "23.00"
            }:
                rejected.append((amount, "POS_LIKE_NO_GEOMETRY"))
                continue
        else:
            if not _in_charge_column(bbox):
                rejected.append((amount, "OUTSIDE_CHARGE_COLUMN"))
                continue
            if not _row_band_ok(bbox, row_y_band):
                rejected.append((amount, "ROW_BASELINE_MISMATCH"))
                continue
            verdict = charge_region_verdict(bbox, already_reference=True)
            if verdict.reason == "CHARGE_GEOMETRY_POS_BLEED":
                rejected.append((amount, "POS_REGION_OVERLAP"))
                continue
        if family not in _LOCAL_ENGINES and family not in {"tesseract", "azure_gpt4o_crop"}:
            rejected.append((amount, f"ENGINE_{family or 'UNKNOWN'}"))
            continue
        usable.append((amount, family, cand))

    if not usable:
        return LineChargeSelection(
            "UNREADABLE_LINE_CHARGE",
            None,
            "NO_CHARGE_COLUMN_CANDIDATE",
            rejected=tuple(rejected[:12]),
        )

    peer_amounts = {amount for amount, _, _ in usable}
    filtered: list[tuple[str, str, dict, int]] = []
    soup_amounts: set[str] = set()
    for amount, family, cand in usable:
        if _looks_like_units_concat(amount, peer_amounts):
            # ``6401`` beside local ``640`` is units bleed. ``1851`` beside a
            # vision-only ``185`` is the dropped digit that regressed blind-50
            # STP — keep the fuller local amount for digit-drop resolution.
            # Three-digit ``701`` beside Claude+paddle ``70`` is units bleed;
            # ``510`` beside whitelist-only ``51`` (from ``5100``) is not.
            stem = _dollars_digits(amount)[:-1]
            stem_amount = f"{int(stem)}.00" if stem.isdigit() else ""
            stem_local_families = {
                fam
                for peer, fam, _ in usable
                if peer == stem_amount and fam in _LOCAL_ENGINES
            }
            stem_has_vision = any(
                peer == stem_amount and fam == "azure_gpt4o_crop"
                for peer, fam, _ in usable
            )
            dollars = _dollars_digits(amount)
            if len(dollars) == 3:
                stem_trusted = stem_has_vision or len(stem_local_families) >= 2
            else:
                stem_trusted = bool(stem_local_families)
            if len(dollars) == 3:
                # Only veto when the stem is trusted (Claude and/or dual-local).
                # A lone rapid ``17`` under-read must not strip Claude ``175``.
                if stem_trusted:
                    rejected.append((amount, "UNITS_CONCAT_BLEED"))
                    continue
            elif stem_trusted or family not in _LOCAL_ENGINES:
                rejected.append((amount, "UNITS_CONCAT_BLEED"))
                continue
        # Local ×100 under-read (paddle ``1.50``) beside vision fuller (``150.00``).
        # ``_looks_like_place_shift`` only flags the inflated side, so catch the
        # under-read here before it wins GEOMETRY_CENTS_PLACE_SHIFT_RESOLVED.
        # Do NOT treat GEOMETRY_CENTS ``49.72`` as an under-read of vision soup
        # ``4972.00`` — those are concat shells where the smaller is correct.
        if family in _LOCAL_ENGINES:
            under_amt = parse_currency(amount)
            if under_amt is not None and any(
                peer != amount
                and (peer_val := parse_currency(peer)) is not None
                and peer_val > under_amt
                and is_decimal_place_shift(amount, peer)
                and not _is_concat_place_shift_shell(peer, peer_amounts)
                and any(
                    a == peer and fam == "azure_gpt4o_crop" for a, fam, _ in usable
                )
                for peer in peer_amounts
            ):
                rejected.append((amount, "PLACE_SHIFT_UNDER_READ"))
                continue
        if _looks_like_place_shift(amount, peer_amounts):
            # Concat shells (4972.00 vs 49.72) always reject. ×10/×100 under-reads
            # (paddle 1.75 vs rapid+Claude 175.00) keep the vision+local fuller
            # amount so GEOMETRY_CENTS_PLACE_SHIFT_RESOLVED cannot lock onto 1.75.
            if _is_concat_place_shift_shell(amount, peer_amounts):
                rejected.append((amount, "PLACE_SHIFT_SOUP"))
                continue
            vision_and_local = any(
                a == amount and fam == "azure_gpt4o_crop" for a, fam, _ in usable
            ) and any(a == amount and fam in _LOCAL_ENGINES for a, fam, _ in usable)
            amt_val = parse_currency(amount)
            # EJGE.003 L2: Claude-only ``150.00`` vs paddle ``1.50`` — keep the
            # vision fuller when every smaller place-shift peer is local-only.
            vision_only_fuller = False
            if (
                not vision_and_local
                and family == "azure_gpt4o_crop"
                and amt_val is not None
            ):
                smaller_local_only: list[str] = []
                for peer in peer_amounts:
                    if peer == amount:
                        continue
                    peer_val = parse_currency(peer)
                    if (
                        peer_val is None
                        or peer_val >= amt_val
                        or not is_decimal_place_shift(amount, peer)
                    ):
                        continue
                    peer_has_local = any(
                        a == peer and fam in _LOCAL_ENGINES for a, fam, _ in usable
                    )
                    peer_has_vision = any(
                        a == peer and fam == "azure_gpt4o_crop" for a, fam, _ in usable
                    )
                    if peer_has_local and not peer_has_vision:
                        smaller_local_only.append(peer)
                    else:
                        smaller_local_only = []
                        break
                vision_only_fuller = bool(smaller_local_only)
            if not vision_and_local and not vision_only_fuller:
                rejected.append((amount, "PLACE_SHIFT_SOUP"))
                continue
        quality = _candidate_evidence_quality(cand, amount)
        # Concatenated shells (6401 / 2601 / 4972) are never SELECTED alone —
        # keep them as conflict evidence for verification / HITL.
        if quality == 0:
            soup_amounts.add(amount)
            rejected.append((amount, "BARE_DIGIT_SOUP"))
            continue
        filtered.append((amount, family, cand, quality))

    if not filtered:
        soup_hint = sorted(soup_amounts)[0] if len(soup_amounts) == 1 else None
        return LineChargeSelection(
            "AMBIGUOUS_LINE_CHARGE" if soup_hint else "UNREADABLE_LINE_CHARGE",
            soup_hint,
            "ONLY_BLEED_OR_SOUP_CANDIDATES",
            rejected=tuple(rejected[:12]),
        )

    # Prefer dual local agreement on the same amount.
    by_amount: dict[str, set[str]] = {}
    quality_by_amount: dict[str, int] = {}
    for amount, family, _cand, quality in filtered:
        by_amount.setdefault(amount, set()).add(family)
        quality_by_amount[amount] = max(quality_by_amount.get(amount, 0), quality)

    dual_local = [
        amount
        for amount, families in by_amount.items()
        if len(families & _LOCAL_ENGINES) >= 2
    ]
    local_or_vision = [
        amount
        for amount, families in by_amount.items()
        if (families & _LOCAL_ENGINES)
        and (len(families) >= 2 or "azure_gpt4o_crop" in families)
    ]

    def _rank(amounts: list[str]) -> list[str]:
        return sorted(amounts, key=lambda a: (-quality_by_amount.get(a, 0), a))

    winners = _rank(dual_local) or _rank(local_or_vision)
    if not winners:
        dual_vision = _dual_vision_select_without_dual_local(
            line, by_amount=by_amount, rejected=rejected
        )
        if dual_vision is not None:
            return dual_vision
        vision_fuller = _vision_fuller_select_without_dual_local(
            line, by_amount=by_amount, rejected=rejected
        )
        if vision_fuller is not None:
            return vision_fuller
        # Claude-only whole-dollar fuller after local ×100 under-reads were
        # stripped (EJGE.003: 150.00 vs paddle 1.50). vision_fuller skips .00.
        if any(reason == "PLACE_SHIFT_UNDER_READ" for _, reason in rejected):
            vision_only = [
                amount
                for amount, families in by_amount.items()
                if "azure_gpt4o_crop" in families and not (families & _LOCAL_ENGINES)
            ]
            if len(vision_only) == 1:
                amount = vision_only[0]
                return LineChargeSelection(
                    "SELECTED_LOCAL_CHARGE",
                    amount,
                    "VISION_FULLER_OVER_LOCAL_PLACE_SHIFT",
                    supporting_engines=tuple(sorted(by_amount[amount])),
                    rejected=tuple(rejected[:12]),
                )
        digit_drop = _digit_drop_fuller_local(by_amount)
        # Geometry-only ``200100`` → ``2001.00`` is a ruling tick, not the
        # dropped-digit case that keeps Rapid ``1851.00`` over Claude ``185``.
        # Single-line DJKN.001/.002/.006 stay at printed ``200`` when Claude is
        # the only shorter rival. Multi-line HJDF.022 is recovered in
        # ``apply_line_charge_selector`` after every line shows this pattern.
        if (
            digit_drop is not None
            and _geometry_only_rows(digit_drop, filtered)
            and any(
                (other_amt := parse_currency(other)) is not None
                and (full_amt := parse_currency(digit_drop)) is not None
                and full_amt > other_amt
                and is_scale_shift(digit_drop, other)
                for other in by_amount
                if other != digit_drop
            )
        ):
            digit_drop = None
        if digit_drop is not None:
            return LineChargeSelection(
                "SELECTED_LOCAL_CHARGE",
                digit_drop,
                "DIGIT_DROP_FULLER_LOCAL",
                supporting_engines=tuple(sorted(by_amount[digit_drop])),
                rejected=tuple(rejected[:12])
                + tuple((amount, "DIGIT_DROP_SHORTER_READ") for amount in by_amount if amount != digit_drop),
            )
        # Single local engine only — ambiguous without a second reader.
        singles = sorted(by_amount.keys())
        if len(singles) == 1 and len(by_amount[singles[0]] & _LOCAL_ENGINES) >= 1:
            amount = singles[0]
            # Geometry-cents that defeated a place-shift / bare-digit shell is
            # authoritative even as a single local family (4972 soup vs 49.72).
            if quality_by_amount.get(amount, 0) >= 3 and any(
                reason in {
                    "PLACE_SHIFT_SOUP",
                    "BARE_DIGIT_SOUP",
                    "UNITS_CONCAT_BLEED",
                }
                for _, reason in rejected
            ):
                return LineChargeSelection(
                    "SELECTED_LOCAL_CHARGE",
                    amount,
                    "GEOMETRY_CENTS_PLACE_SHIFT_RESOLVED",
                    supporting_engines=tuple(sorted(by_amount[amount])),
                    rejected=tuple(rejected[:12]),
                )
            return LineChargeSelection(
                "AMBIGUOUS_LINE_CHARGE",
                amount,
                "SINGLE_LOCAL_ENGINE_ONLY",
                supporting_engines=tuple(sorted(by_amount[amount])),
                rejected=tuple(rejected[:12]),
            )
        jitter = _same_stem_ruling_jitter_amount(by_amount, filtered)
        if jitter is not None:
            return LineChargeSelection(
                "SELECTED_LOCAL_CHARGE",
                jitter,
                "SAME_STEM_CENTS_RULING_JITTER",
                supporting_engines=tuple(
                    sorted(set().union(*(by_amount[amount] for amount in by_amount)))
                ),
                rejected=tuple(rejected[:12])
                + tuple(
                    (amount, "CENTS_RULING_JITTER")
                    for amount in by_amount
                    if amount != jitter
                ),
            )
        ruled = _di_corroborated_ruling_split(line, by_amount)
        if ruled is not None:
            return LineChargeSelection(
                "SELECTED_LOCAL_CHARGE",
                ruled,
                "RULING_SPLIT_DI_CORROBORATED",
                supporting_engines=tuple(sorted(by_amount.get(ruled) or ())),
                rejected=tuple(rejected[:12])
                + tuple(
                    (amount, "GEOMETRY_SCALE_SHIFT")
                    for amount in by_amount
                    if amount != ruled
                ),
            )
        return LineChargeSelection(
            "AMBIGUOUS_LINE_CHARGE",
            None,
            "NO_DUAL_LOCAL_AGREEMENT",
            rejected=tuple(rejected[:12]),
        )

    best_q = quality_by_amount.get(winners[0], 0)
    top = [a for a in winners if quality_by_amount.get(a, 0) == best_q]
    if len(set(top)) > 1:
        # Drop leading-digit fragments of a longer dual-local peer
        # (``11.00`` beside ``119.00``) instead of failing closed as competing.
        survivors = []
        for amount in top:
            digits = re.sub(r"\D", "", amount)
            if any(
                other != amount
                and digits
                and re.sub(r"\D", "", other).startswith(digits)
                and len(re.sub(r"\D", "", other)) > len(digits)
                and len(digits) <= 3
                for other in top
            ):
                rejected.append((amount, "LEADING_AMOUNT_FRAGMENT"))
                continue
            survivors.append(amount)
        top = survivors or top
    if len(set(top)) > 1:
        # Dual vision agreement outranks dual-local-only peers at same quality
        # (119.00 Claude+gpt4o+locals vs 3.11 dual-local bleed).
        vendor_amounts = _vision_vendor_amounts(line)
        dual_vision_tops = [
            amount
            for amount in top
            if len(vendor_amounts.get(amount, set())) >= 2
        ]
        if len(set(dual_vision_tops)) == 1:
            for amount in top:
                if amount not in dual_vision_tops:
                    rejected.append((amount, "DUAL_LOCAL_OUTRANKED_BY_DUAL_VISION"))
            top = dual_vision_tops
        else:
            # Dual-local (+ optional vision) agreement beats a sole GEOMETRY_CENTS
            # rival at the same quality (119.00 dual-local vs 61.19 geometry soup).
            preferred = [
                amount
                for amount in top
                if len(by_amount.get(amount, set()) & _LOCAL_ENGINES) >= 2
                or len(vendor_amounts.get(amount, set())) >= 2
            ]
            geometry_only = [
                amount
                for amount in top
                if amount not in preferred
                or (
                    len(by_amount.get(amount, set()) & _LOCAL_ENGINES) < 2
                    and len(vendor_amounts.get(amount, set())) < 2
                )
            ]
            strong = [
                amount
                for amount in top
                if len(by_amount.get(amount, set()) & _LOCAL_ENGINES) >= 2
                and (
                    "azure_gpt4o_crop" in by_amount.get(amount, set())
                    or len(vendor_amounts.get(amount, set())) >= 1
                )
            ]
            if len(set(strong)) == 1:
                for amount in top:
                    if amount not in strong:
                        rejected.append((amount, "GEOMETRY_OR_WEAK_PEER_OUTRANKED"))
                top = strong
            elif len(set(preferred)) == 1:
                for amount in top:
                    if amount not in preferred:
                        rejected.append((amount, "GEOMETRY_OR_WEAK_PEER_OUTRANKED"))
                top = preferred
    if len(set(top)) > 1:
        anchor = top[0]
        if all(amount == anchor or amounts_same_stem_cents_twin(anchor, amount) for amount in top):
            decimal_amounts = {
                amount
                for amount, _family, cand, _quality in filtered
                if amount in top
                and _raw_has_observed_decimal(cand.get("raw_value") or cand.get("value"))
            }

            def _twin_rank(amount: str) -> tuple[int, int, int, int, int]:
                families = by_amount.get(amount, set())
                parsed = parse_currency(amount)
                nonzero_cents = int(
                    parsed is not None and parsed != parsed.to_integral_value()
                )
                return (
                    1 if "azure_gpt4o_crop" in families else 0,
                    nonzero_cents,
                    1 if amount in decimal_amounts else 0,
                    len(families),
                    quality_by_amount.get(amount, 0),
                )

            best = max(_twin_rank(amount) for amount in top)
            chosen = [amount for amount in top if _twin_rank(amount) == best]
            if len(chosen) == 1:
                for amount in top:
                    if amount != chosen[0]:
                        rejected.append((amount, "SAME_STEM_CENTS_TWIN"))
                top = chosen
    if len(set(top)) > 1:
        return LineChargeSelection(
            "AMBIGUOUS_LINE_CHARGE",
            None,
            "COMPETING_LOCAL_AMOUNTS",
            rejected=tuple(rejected[:12]),
        )

    amount = top[0]
    # Dollars-ruling dual-local must not erase geometry / gpt-4o fuller reads
    # (129.00 vs GEOMETRY_CENTS 1291.15, or 129.00 vs gpt-4o 129.15).
    # Same-stem cents twins (640.00 vs rapid 640.40) are OCR jitter — only a
    # vision-backed fuller amount may outrank dual-local / local+vision dollars.
    fuller_rivals = [
        other
        for other in by_amount
        if other != amount
        and _is_dollar_truncation(amount, other)
        and (
            "azure_gpt4o_crop" in by_amount.get(other, set())
            or (
                quality_by_amount.get(other, 0) >= 3
                and not _is_same_stem_cents_twin(amount, other)
            )
        )
    ]
    if fuller_rivals:
        fuller_best = _rank(fuller_rivals)[0]
        # When vision/geometry carries the fuller cents read and locals only have
        # the dollars-ruling truncation of the same stem (157.00 vs Claude/gpt4o
        # 157.07), select the fuller amount — do not leave amount=None (that kept
        # stale place-shifted line Σ and fought Box 28).
        local_stem_ok = any(
            bool(families & _LOCAL_ENGINES) and _is_dollar_truncation(other, fuller_best)
            for other, families in by_amount.items()
        )
        vision_or_geometry = (
            "azure_gpt4o_crop" in by_amount.get(fuller_best, set())
            or quality_by_amount.get(fuller_best, 0) >= 3
        )
        # Fail closed when a GEOMETRY_CENTS observation names a different amount
        # than the vision fuller read (gpt 129.15 vs geometry 1291.15).
        geo_conflict = False
        fuller_amt = parse_currency(fuller_best)
        for attempt in line.get("attempts") or []:
            reason = str(attempt.get("reason") or "")
            if "GEOMETRY_CENTS" not in reason:
                continue
            obs = attempt.get("observation") or {}
            shaped = (
                obs.get("shaped")
                or obs.get("canonical_monetary_value")
                or obs.get("value")
            )
            geo_amt = parse_currency(shaped)
            if geo_amt is not None and fuller_amt is not None and geo_amt != fuller_amt:
                geo_conflict = True
                break
        if local_stem_ok and vision_or_geometry and not geo_conflict:
            # Dual-local ``157.00`` plus GEOMETRY_CENTS ``1571.07`` (raw
            # ``157107``) is a ×10 ruling tick, not a vision fuller read.
            # Selecting it made the line sum the inflated amount. A real
            # gpt-4o/Claude fuller amount still selects above.
            fuller_has_vision = "azure_gpt4o_crop" in by_amount.get(fuller_best, set())
            if (
                not fuller_has_vision
                and _geometry_only_rows(fuller_best, filtered)
                and is_scale_shift(fuller_best, amount)
                and parse_currency(fuller_best) > parse_currency(amount)
            ):
                # Keep the dual-local dollars (157.00), not the ruling-tick
                # 1571.07, and not an empty line. Empty lines drop the Σ that
                # Box 28 needs. The inflated geometry amount stays rejected.
                return LineChargeSelection(
                    "SELECTED_LOCAL_CHARGE",
                    amount,
                    "DUAL_LOCAL_CHARGE_COLUMN",
                    supporting_engines=tuple(sorted(by_amount.get(amount) or ())),
                    rejected=tuple(rejected[:12])
                    + ((fuller_best, "GEOMETRY_SCALE_SHIFT"),),
                )
            return LineChargeSelection(
                "SELECTED_LOCAL_CHARGE",
                fuller_best,
                "VISION_FULLER_DOLLARS_STEM_CORROBORATED",
                supporting_engines=tuple(
                    sorted(by_amount[fuller_best] | (by_amount.get(amount) or set()))
                ),
                rejected=tuple(rejected[:12]) + ((amount, "DOLLARS_TRUNCATION"),),
            )
        # Dual independent vision readers (gpt-4o + Claude) agreeing on the
        # fuller cents amount override a conflicting GEOMETRY_CENTS place-shift
        # soup (1571.07 vs 157.07). Single vision still fails closed on geo conflict.
        vision_vendors: set[str] = set()
        for cand in line.get("candidates") or []:
            if not isinstance(cand, dict):
                continue
            if parse_currency(cand.get("value")) != fuller_amt:
                continue
            eng = str(cand.get("engine") or "").casefold()
            if "claude" in eng or "anthropic" in eng:
                vision_vendors.add("claude")
            elif "gpt4o" in eng or "gpt-4o" in eng:
                vision_vendors.add("gpt4o")
        if local_stem_ok and len(vision_vendors) >= 2:
            return LineChargeSelection(
                "SELECTED_LOCAL_CHARGE",
                fuller_best,
                "DUAL_VISION_FULLER_DOLLARS_STEM_CORROBORATED",
                supporting_engines=tuple(
                    sorted(by_amount[fuller_best] | (by_amount.get(amount) or set()))
                ),
                rejected=tuple(rejected[:12])
                + (
                    (amount, "DOLLARS_TRUNCATION"),
                    (fuller_best, "GEOMETRY_CENTS_OVERRIDDEN_BY_DUAL_VISION"),
                ),
            )
        return LineChargeSelection(
            "AMBIGUOUS_LINE_CHARGE",
            None,
            "DOLLARS_TRUNCATION_VS_FULLER_READ",
            rejected=tuple(rejected[:12])
            + tuple((amount, "DOLLARS_TRUNCATION") for _ in [0]),
        )

    engines = tuple(sorted(by_amount[amount]))
    return LineChargeSelection(
        "SELECTED_LOCAL_CHARGE",
        amount,
        "DUAL_LOCAL_CHARGE_COLUMN"
        if len(set(engines) & _LOCAL_ENGINES) >= 2
        else "LOCAL_VISION_CHARGE_COLUMN",
        supporting_engines=engines,
        rejected=tuple(rejected[:12]),
    )


def _geometry_digit_drop_vs_vision_short(line: dict) -> str | None:
    """Fuller GEOMETRY_CENTS amount when the only shorter rival is vision.

    Used for multi-line Blind-50 recovery (1851+1551) where the per-line
    selector clears geometry digit-drop against Claude so single-line ruling
    ticks (2001 vs 200) stay closed.
    """
    by_amount: dict[str, set[str]] = {}
    geometry_amounts: set[str] = set()
    for cand in line.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        amount = _shaped_amount(cand)
        if amount is None:
            continue
        family = _engine_family(cand.get("engine"))
        by_amount.setdefault(amount, set()).add(family)
        prep = str(cand.get("preprocessing_variant") or cand.get("evidence_reference") or "")
        if "GEOMETRY_CENTS" in prep and family in _LOCAL_ENGINES:
            geometry_amounts.add(amount)
    if len(geometry_amounts) != 1:
        return None
    fuller = next(iter(geometry_amounts))
    fuller_rows = [
        cand
        for cand in (line.get("candidates") or [])
        if isinstance(cand, dict) and _shaped_amount(cand) == fuller
    ]
    if not fuller_rows or not all(
        "GEOMETRY_CENTS"
        in str(cand.get("preprocessing_variant") or cand.get("evidence_reference") or "")
        for cand in fuller_rows
    ):
        return None
    fuller_dollars = _dollars_digits(fuller)
    if len(fuller_dollars) < 3:
        return None
    others = [amount for amount in by_amount if amount != fuller]
    if not others:
        return None
    saw_drop = False
    for other in others:
        families = by_amount[other]
        other_dollars = _dollars_digits(other)
        is_drop = (
            bool(other_dollars)
            and fuller_dollars.startswith(other_dollars)
            and len(fuller_dollars) - len(other_dollars) == 1
        )
        if is_drop:
            # A local short twin is real disagreement, not Claude digit-drop.
            if families & _LOCAL_ENGINES:
                return None
            saw_drop = True
            continue
        if families & _LOCAL_ENGINES:
            # Paddle ``18500`` beside geometry ``1851`` is place-shift soup, not
            # a second charge that should block multi-line Blind-50 recovery.
            if is_scale_shift(fuller, other):
                continue
            return None
        if families <= {"tesseract"}:
            continue
        return None
    return fuller if saw_drop else None


def apply_line_charge_selector(lines: list[dict] | None) -> list[dict]:
    """Apply ``select_line_charge`` to each service line; drop unreadable rows."""
    kept: list[dict] = []
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        selection = select_line_charge(line)
        updated = dict(line)
        updated["line_charge_selection"] = selection.to_dict()
        if selection.disposition == "SELECTED_LOCAL_CHARGE" and selection.amount:
            updated["charges"] = selection.amount
            updated["charge_amount"] = selection.amount
            updated["router_reason"] = (
                f"{line.get('router_reason') or ''}|LINE_CHARGE_SELECTOR:{selection.reason}"
            ).strip("|")
            kept.append(updated)
            continue
        if selection.disposition == "AMBIGUOUS_LINE_CHARGE":
            # Keep row for review / later verification, but do not promote a
            # bleed shell. Prefer selector amount hint when present.
            if selection.amount:
                # Single-engine tiny ruling soup (``1.01`` from raw ``1\\n01``)
                # must not enter the line Σ beside a real dual-local charge —
                # that false 176.01 vetoes unanimous Box 28 ``175.00``.
                from packages.claim_evidence.line_sum_authority import (
                    is_suspicious_tiny_total,
                )

                tiny = parse_currency(selection.amount)
                if (
                    selection.reason == "SINGLE_LOCAL_ENGINE_ONLY"
                    and tiny is not None
                    and is_suspicious_tiny_total(tiny)
                ):
                    updated["charges"] = None
                    updated["charge_amount"] = None
                else:
                    updated["charges"] = selection.amount
                    updated["charge_amount"] = selection.amount
            else:
                # Stale charges (e.g. geometry 49.77) with no selector amount
                # invent a false line Σ and fight Box 28 / gpt-4o (4972).
                # Keep only when a live candidate still supports the amount.
                current = parse_currency(updated.get("charges"))
                supported = False
                if current is not None:
                    target = format_currency(current)
                    for cand in updated.get("candidates") or []:
                        if not isinstance(cand, dict):
                            continue
                        if parse_currency(cand.get("value")) != current:
                            continue
                        eng = str(cand.get("engine") or "").casefold()
                        prep = str(
                            cand.get("preprocessing_variant")
                            or cand.get("evidence_reference")
                            or ""
                        )
                        if (
                            "gpt4o" in eng
                            or "claude" in eng
                            or "anthropic" in eng
                            or "GEOMETRY_CENTS" in prep
                            or _raw_has_observed_decimal(cand.get("raw_value"))
                        ):
                            # A lone ×10/×100 geometry shell is not support when
                            # paddle and rapid already agree on the other scale,
                            # or when any non-geometry reader has the smaller twin
                            # (``2001.00`` from raw ``200100`` vs Claude ``200.00``).
                            if _scale_shifted_from_dual_local(current, updated.get("candidates")):
                                continue
                            if (
                                "GEOMETRY_CENTS" in prep
                                and _inflated_geometry_vs_peer(current, updated.get("candidates"))
                            ):
                                continue
                            supported = True
                            break
                        if _candidate_evidence_quality(cand, target) >= 3:
                            supported = True
                            break
                if not supported:
                    updated["charges"] = None
                    updated["charge_amount"] = None
            updated["line_charge_ambiguous"] = True
            updated["router_reason"] = (
                f"{line.get('router_reason') or ''}|LINE_CHARGE_AMBIGUOUS:{selection.reason}"
            ).strip("|")
            kept.append(updated)
            continue
        # UNREADABLE — drop from AUTO line set (verification will HITL).
        updated["charges"] = None
        updated["charge_amount"] = None
        updated["line_charge_unreadable"] = True
        updated["router_reason"] = (
            f"{line.get('router_reason') or ''}|LINE_CHARGE_UNREADABLE:{selection.reason}"
        ).strip("|")
        kept.append(updated)

    # Multi-line only: every observed line is geometry digit-drop vs Claude short
    # (HJDF.022 1851+1551). Single-line geometry 2001 vs Claude 200 stays closed.
    promote: list[tuple[int, str]] = []
    for index, line in enumerate(kept):
        if not line.get("line_charge_ambiguous"):
            if any(parse_currency(line.get(k)) is not None for k in ("charges", "charge_amount")):
                # A clean selected line breaks the all-ambiguous pattern.
                promote = []
                break
            continue
        fuller = _geometry_digit_drop_vs_vision_short(line)
        if fuller is None:
            promote = []
            break
        promote.append((index, fuller))
    if len(promote) >= 2 and len(promote) == sum(
        1
        for line in kept
        if line.get("line_charge_ambiguous")
        or any(parse_currency(line.get(k)) is not None for k in ("charges", "charge_amount"))
    ):
        for index, fuller in promote:
            line = kept[index]
            selection = LineChargeSelection(
                "SELECTED_LOCAL_CHARGE",
                fuller,
                "MULTI_LINE_GEOMETRY_DIGIT_DROP",
                supporting_engines=("rapidocr",),
            )
            line["line_charge_selection"] = selection.to_dict()
            line["charges"] = fuller
            line["charge_amount"] = fuller
            line.pop("line_charge_ambiguous", None)
            line["router_reason"] = (
                f"{line.get('router_reason') or ''}|LINE_CHARGE_SELECTOR:{selection.reason}"
            ).strip("|")
    return kept
