"""Crop-scoped Azure gpt-4o residual for DOB / member-ID / name / box-28 charge.

Runs only after local Rapid→Paddle/Tesseract (and DOB TrOCR→Azure DI) leave
the field unshaped, ID-chrome contaminated, with same-length digit conflicts,
or with genuine person-name engine conflicts. For charges, runs when local +
Azure DI leave box-28 empty/unshaped. Crop-only evidence — never a full-page
vision call. Accepts when the value is date-/ID-/name-/currency-shaped and the
model does not abstain.

Bakeoff (hard-150 FIELD_INK HITL, 26 docs): DOB shaped 16/17, ID shaped 14/14,
mean ~2.0s/call. See docs/metrics/dob_id_hitl_techstack_v12_3n.md.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from PIL import Image

from packages.extraction_recovery.field_cascade import semantic_accept
from packages.extraction_recovery.span_selection import select_field_span

_DOB_FIELDS = frozenset({"patient_dob", "date_of_birth"})
_ID_FIELDS = frozenset({"insured_id_number", "member_id", "subscriber_id"})
_NAME_FIELDS = frozenset({"patient_name", "insured_name"})
_CHARGE_FIELDS = frozenset(
    {"total_charge", "total_charges", "charges", "charge_amount"}
)
_ID_CHROME = re.compile(
    r"INSURED|NUMBER|PROGRAM|ITEM\s*1|1A\.|FOR\s*PROGRAM|PICA|LAST\s*NAME|MIDDLE",
    re.IGNORECASE,
)
_HANDWRITING_GAPS = frozenset({"HANDWRITING_UNREADABLE", "AMBIGUOUS_DIGIT_FRAGMENTS", ""})
_NAME_GAPS = frozenset(
    {
        "HANDWRITING_UNREADABLE",
        "NAME_ENGINE_CONFLICT",
        "EVIDENCE_POLICY_GAP",
        "CALIBRATION_HITL",
        "",
    }
)
_CHARGE_GAPS = frozenset(
    {
        "EMPTY_FINANCIAL_INK",
        "LINE_SUM_UNCORROBORATED",
        "CHARGE_LOCAL_EXHAUSTED",
        "CHARGE_DIGIT_CONFLICT",
        "AMBIGUOUS_DIGIT_FRAGMENTS",
        "AMBIGUOUS_CHARGE_DIGITS",
        "CALIBRATION_HITL",
        "",
    }
)

_build_gpt4o_vision_adapter: Callable[..., Any] | None = None


def configure_gpt4o_vision_adapter_factory(factory: Callable[..., Any]) -> None:
    """Composition root injects Azure OpenAI vision adapter construction."""
    global _build_gpt4o_vision_adapter
    _build_gpt4o_vision_adapter = factory


@dataclass(frozen=True)
class Gpt4oCropResidualResult:
    attempted: bool
    configured: bool
    review_only: bool
    value: str | None
    raw_value: str | None
    shaped: bool
    insufficient_evidence: bool
    reason: str
    engine: str = "azure_gpt4o_crop"
    confidence: float | None = None
    validation_results: tuple[str, ...] = ()


class Gpt4oCropRecognizer(Protocol):
    def recognize_fields(
        self,
        crops: Mapping[str, Image.Image],
        *,
        field_types: Mapping[str, str],
        descriptions: Mapping[str, str],
        prior_candidates: Mapping[str, list[str]],
    ) -> Mapping[str, Gpt4oCropResidualResult]: ...


def gpt4o_crop_residual_enabled() -> bool:
    raw = (os.environ.get("CDP_GPT4O_CROP_RESIDUAL") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def gpt4o_crop_accept_enabled() -> bool:
    raw = (os.environ.get("CDP_GPT4O_CROP_ACCEPT") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def empty_financial_ink_gpt4o_enabled() -> bool:
    """gpt-4o sweep when local OCR finds no box-28 and no line charges.

    Default on with CDP_GPT4O_CROP_RESIDUAL. Disable with
    CDP_GPT4O_EMPTY_FINANCE=0.
    """
    if not gpt4o_crop_residual_enabled():
        return False
    raw = (os.environ.get("CDP_GPT4O_EMPTY_FINANCE") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def empty_financial_ink_max_lines() -> int:
    raw = (os.environ.get("CDP_GPT4O_EMPTY_FINANCE_MAX_LINES") or "4").strip()
    try:
        return max(0, min(8, int(raw)))
    except ValueError:
        return 4


def _expand_charge_bbox(
    bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
    *,
    pad_x: float = 0.35,
    pad_y: float = 0.55,
) -> tuple[int, int, int, int]:
    """Widen/tall-en a tight charge crop so faint ink is not clipped."""
    x0, y0, x1, y1 = (int(v) for v in bbox)
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    width, height = image_size
    nx0 = max(0, x0 - int(pad_x * w))
    ny0 = max(0, y0 - int(pad_y * h))
    nx1 = min(width, x1 + int(pad_x * w))
    ny1 = min(height, y1 + int(pad_y * h))
    return (nx0, ny0, max(nx0 + 1, nx1), max(ny0 + 1, ny1))


def _normalize(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    return cleaned or None


def _shape_dob(raw: str | None) -> tuple[str | None, bool]:
    text = _normalize(raw)
    if not text:
        return None, False
    span = select_field_span(text, "DATE", "patient_dob")
    selected = _normalize(span.selected_text) or text
    ok = bool(selected) and semantic_accept("patient_dob", selected)[0]
    return selected, ok


def _shape_id(raw: str | None) -> tuple[str | None, bool]:
    text = _normalize(raw)
    if not text:
        return None, False
    if _ID_CHROME.search(text):
        return text, False
    span = select_field_span(text, "ALPHANUMERIC_ID", "insured_id_number")
    selected = _normalize(span.selected_text) or text
    if _ID_CHROME.search(selected or ""):
        return selected, False
    alnum = re.sub(r"[^A-Za-z0-9]", "", selected or "")
    if len(alnum) < 5 or not re.search(r"\d", alnum):
        return selected, False
    # Reject label-bleed ghosts (NUMBER/PROGRAM fragments fused into alnum).
    if re.search(r"N0?BER|NUMB|PROGRAM|INSURE|ITEM", alnum, re.IGNORECASE):
        return selected, False
    ok = bool(selected) and semantic_accept("insured_id_number", selected)[0]
    return selected, ok


def _shape_charge(raw: str | None) -> tuple[str | None, bool]:
    """Currency-shape box-28 / line charge ink from gpt-4o crop text."""
    text = _normalize(raw)
    if not text:
        return None, False
    span = select_field_span(text, "CURRENCY", "total_charge")
    selected = _normalize(span.selected_text) or text
    m = re.search(
        r"\$?\d{1,3}(?:,\d{3})*\.\d{2}|\$?\d{2,6}(?:\.\d{2})?",
        selected or "",
    )
    if not m:
        return selected, False
    amount = m.group(0).lstrip("$").replace(",", "")
    if "." not in amount and re.fullmatch(r"\d{2,6}", amount):
        amount = f"{amount}.00"
    # Reject suspicious single-digit dollars (form-rule noise).
    if re.fullmatch(r"[0-9]\.\d{2}", amount):
        return amount, False
    ok = bool(amount) and semantic_accept("total_charge", amount)[0]
    return amount, ok


def _shape_name(field_name: str, raw: str | None) -> tuple[str | None, bool]:
    """Person-name shape from gpt-4o crop text (handwriting / engine conflict)."""
    text = _normalize(raw)
    if not text:
        return None, False
    span = select_field_span(text, "PERSON_NAME", field_name)
    selected = _normalize(span.selected_text) or text
    # Strip common CMS-1500 label bleed.
    selected = re.sub(
        r"\b(PATIENT|NAME|INSURED|FIRST|LAST|MI|MIDDLE)\b",
        " ",
        selected or "",
        flags=re.IGNORECASE,
    )
    selected = _normalize(selected)
    if not selected:
        return None, False
    ok = bool(selected) and semantic_accept(field_name, selected)[0]
    return selected, ok


def charge_needs_gpt4o(
    *,
    local_accepted: bool,
    azure_di_shaped: bool,
    gap_class: str | None = None,
    candidates: list[Mapping[str, Any]] | None = None,
    observed_line_charges: list[str] | None = None,
) -> bool:
    """Run gpt-4o when local+DI left box-28 empty/unshaped (hard-15 charge hole).

    Also run when DIGITS_FIRST accepted a currency shell but local candidates
    include a decimal-place rival (222.22 vs 2221.22) — otherwise Box 28 never
    gets vision arbitration and CALIBRATION_HITL / place-shift fights persist.

    ``observed_line_charges`` must be passed (or stamped on the field row) so
    dual-local Box28 with 0 lines / place-shift vs Σ does not falsely settle.
    """
    try:
        from packages.extraction_recovery.cloud_stop_ladder import (
            charge_locals_settled,
            cloud_stop_ladder_enabled,
        )

        if cloud_stop_ladder_enabled() and charge_locals_settled(
            candidates, observed_line_charges=observed_line_charges
        ):
            return False
    except Exception:  # noqa: BLE001
        pass
    if azure_di_shaped:
        # DI already read a currency, but a local amount that is not that
        # currency still needs Claude (50.00 beside 660.00, 405 beside 495).
        return _charge_local_disagrees_with_di(candidates)
    if local_accepted:
        if _charge_candidates_have_place_shift_rival(candidates):
            return True
        # Dual-local accepted with no line ink still needs cloud for strong E4
        # unless lines were never provided (legacy unit tests).
        if observed_line_charges is not None and len(
            [x for x in observed_line_charges if str(x).strip()]
        ) == 0:
            return True
        # Place-shift vs line Σ: still need vision even if locals agree.
        if observed_line_charges:
            try:
                from packages.claim_evidence.line_sum_authority import (
                    format_currency,
                    is_decimal_place_shift,
                    is_scale_shift,
                    parse_currency,
                )
                from decimal import Decimal

                line_amts = [
                    parse_currency(x) for x in observed_line_charges if x
                ]
                line_amts = [a for a in line_amts if a is not None]
                if line_amts:
                    line_txt = format_currency(sum(line_amts, start=Decimal("0")))
                    for cand in candidates or []:
                        eng = str(cand.get("engine") or "").casefold()
                        if any(
                            t in eng
                            for t in ("gpt4o", "claude", "anthropic", "document_intelligence")
                        ):
                            continue
                        amt = parse_currency(cand.get("value") or cand.get("raw_value"))
                        if amt is None:
                            continue
                        txt = format_currency(amt)
                        if is_decimal_place_shift(txt, line_txt) or is_scale_shift(
                            txt, line_txt
                        ):
                            return True
            except Exception:  # noqa: BLE001
                pass
        return False
    gap = (gap_class or "").upper()
    return gap in _CHARGE_GAPS


def _charge_candidates_have_place_shift_rival(
    candidates: list[Mapping[str, Any]] | None,
) -> bool:
    """True when ≥2 currency-shaped locals disagree by place/digit shift."""
    if not candidates:
        return False
    try:
        from packages.claim_evidence.line_sum_authority import (
            is_currency_digit_drop_twin,
            is_decimal_place_shift,
            parse_currency,
        )
    except Exception:  # noqa: BLE001
        return False

    amounts: list[object] = []
    texts: list[str] = []
    for cand in candidates:
        eng = str(cand.get("engine") or "").casefold()
        if "gpt4o" in eng or "gpt-4o" in eng or "claude" in eng or "anthropic" in eng:
            continue
        raw = cand.get("value") or cand.get("raw_value")
        parsed = parse_currency(raw)
        if parsed is None:
            continue
        amounts.append(parsed)
        texts.append(str(raw))
    for i, left in enumerate(amounts):
        for j, right in enumerate(amounts):
            if j <= i:
                continue
            if is_decimal_place_shift(left, right):
                return True
            if is_currency_digit_drop_twin(texts[i], texts[j]):
                return True
            # Near ×10 shells (222.22 vs 2221.22 / 157.07 vs 1571.07).
            from decimal import Decimal

            for factor in (Decimal(10), Decimal(100)):
                if abs(left * factor - right) <= Decimal("2.00"):
                    return True
                if abs(right * factor - left) <= Decimal("2.00"):
                    return True
    return False


def _charge_local_disagrees_with_di(
    candidates: list[Mapping[str, Any]] | None,
) -> bool:
    """True when a local currency is not the Document Intelligence amount."""
    if not candidates:
        return False
    try:
        from packages.claim_evidence.line_sum_authority import (
            amounts_corroborate,
            parse_currency,
        )
    except Exception:  # noqa: BLE001
        return False

    di_values: list[object] = []
    local_values: list[object] = []
    for cand in candidates:
        engine = str(cand.get("engine") or "").casefold()
        raw = cand.get("value") or cand.get("raw_value")
        if parse_currency(raw) is None:
            continue
        if "gpt4o" in engine or "gpt-4o" in engine or "claude" in engine or "anthropic" in engine:
            continue
        if "document_intelligence" in engine or (
            "azure" in engine and "gpt" not in engine
        ):
            di_values.append(raw)
        else:
            local_values.append(raw)
    if not di_values:
        return False
    # No local currency, or every local currency misses the DI amount.
    return not any(
        any(amounts_corroborate(local, di) for di in di_values) for local in local_values
    )


def id_local_needs_gpt4o(value: str | None, *, accepted: bool) -> bool:
    """True when local ID cascade is missing, chrome-contaminated, or too weak.

    Short zero-padded shells (``00000259054``) always need a second family /
    vision corroboration — cascade may mark them accepted as shaped, but
    reconciler still fail-closes without multi-engine corroboration.
    """
    text = _normalize(value) or ""
    try:
        from packages.candidate_reconciliation.reconciler import (
            _member_id_is_short_padded_shell,
        )

        if text and _member_id_is_short_padded_shell(text):
            return True
    except Exception:  # noqa: BLE001
        pass
    if not accepted:
        return True
    if _ID_CHROME.search(text):
        return True
    alnum = re.sub(r"[^A-Za-z0-9]", "", text)
    if len(alnum) < 7:
        return True
    return bool(alnum.isalpha())


def id_local_digit_conflict(candidates: list[Mapping[str, Any]] | None) -> bool:
    """True when ≥2 same-length shaped local IDs disagree (genuine digit twins).

    Example: paddle ``909295500`` vs rapid ``909293380``. Confusable-only twins
    (O↔0, J↔U) are excluded — those already have reconcile relief.
    """
    if not candidates:
        return False
    from packages.candidate_reconciliation.reconciler import (
        _canonical_member_id,
        _member_id_is_shaped,
        values_conflict_equivalent,
    )

    shaped: list[str] = []
    for cand in candidates:
        engine = str(cand.get("engine") or "")
        if "gpt4o" in engine.casefold() or "gpt-4o" in engine.casefold() or "claude" in engine.casefold() or "anthropic" in engine.casefold():
            continue
        raw = cand.get("value") or cand.get("text")
        text = str(raw or "").strip()
        if not text or not _member_id_is_shaped(text):
            continue
        canon = _canonical_member_id(text)
        if canon and canon not in shaped:
            shaped.append(canon)
    if len(shaped) < 2:
        return False
    for i, left in enumerate(shaped):
        for right in shaped[i + 1 :]:
            if len(left) != len(right) or len(left) < 7:
                continue
            if values_conflict_equivalent("insured_id_number", left, right):
                continue
            return True
    return False


def id_local_already_settled(candidates: list[Mapping[str, Any]] | None) -> bool:
    """True when ≥2 local engines already agree on one shaped ID — skip cloud.

    Saves DI/Claude when paddle+rapid (etc.) already corroborate the subscriber
    id. Digit conflicts and weak/chrome locals still need a vision read.
    Short zero-padded shells may settle when ≥2 local families agree on the
    same canon; a lone padded shell still needs vision (see ``id_needs_gpt4o``).
    """
    if not candidates:
        return False
    from packages.candidate_reconciliation.reconciler import (
        _canonical_member_id,
        _member_id_is_shaped,
        _member_id_is_weak_for_gpt4o_gate,
    )
    from packages.ocr.independence import independence_group

    by_canon: dict[str, set[str]] = {}
    for cand in candidates:
        engine = str(cand.get("engine") or "")
        eng_cf = engine.casefold()
        if any(
            t in eng_cf
            for t in ("gpt4o", "gpt-4o", "claude", "anthropic", "document_intelligence", "azure_di")
        ):
            continue
        raw = str(cand.get("value") or cand.get("text") or "").strip()
        if not raw or _member_id_is_weak_for_gpt4o_gate(raw):
            continue
        if not _member_id_is_shaped(raw):
            continue
        canon = _canonical_member_id(raw)
        if not canon:
            continue
        by_canon.setdefault(canon, set()).add(independence_group(engine))
    for groups in by_canon.values():
        if len(groups) >= 2:
            return True
    return False


def id_needs_gpt4o(
    value: str | None,
    *,
    accepted: bool,
    candidates: list[Mapping[str, Any]] | None = None,
) -> bool:
    """Weak/chrome local OR same-length digit conflict between local engines.

    Skip when locals already multi-engine agree on one shaped ID (no DI/Claude).
    Short-padded shells always need vision/second family even if cascade accepted.
    """
    try:
        from packages.candidate_reconciliation.reconciler import (
            _member_id_is_short_padded_shell,
        )

        if value and _member_id_is_short_padded_shell(str(value)):
            # Already multi-engine on the same padded canon → cloud optional.
            if not id_local_already_settled(candidates):
                return True
    except Exception:  # noqa: BLE001
        pass
    if id_local_already_settled(candidates):
        # Settled locals still need vision when same-length digit twins conflict.
        return id_local_digit_conflict(candidates)
    if id_local_needs_gpt4o(value, accepted=accepted):
        return True
    return id_local_digit_conflict(candidates)


def dob_needs_gpt4o(
    *,
    local_accepted: bool,
    trocr_shaped: bool,
    azure_di_shaped: bool,
    gap_class: str | None,
    candidates: list[Mapping[str, Any]] | None = None,
) -> bool:
    """Unresolved DOB gets a vision read. Accepted / already-shaped locals do not."""
    if local_accepted or trocr_shaped or azure_di_shaped:
        return False
    try:
        from packages.extraction_recovery.cloud_stop_ladder import (
            cloud_stop_ladder_enabled,
            dob_locals_settled,
        )

        if cloud_stop_ladder_enabled() and dob_locals_settled(candidates):
            return False
    except Exception:  # noqa: BLE001
        pass
    gap = (gap_class or "").upper()
    if gap in _HANDWRITING_GAPS or gap in {
        "CALIBRATION_HITL",
        "NORMALIZATION_FAILED",
        "EVIDENCE_POLICY_GAP",
    }:
        return True
    # Missing second engine on a calendar-shaped date still needs vision corroboration.
    return True


def name_local_engine_conflict(candidates: list[Mapping[str, Any]] | None) -> bool:
    """True when ≥2 local name engines disagree beyond soft-equivalence."""
    if not candidates:
        return False
    from packages.candidate_reconciliation.reconciler import values_conflict_equivalent

    shaped: list[str] = []
    for cand in candidates:
        engine = str(cand.get("engine") or "")
        if "gpt4o" in engine.casefold() or "gpt-4o" in engine.casefold() or "claude" in engine.casefold() or "anthropic" in engine.casefold():
            continue
        raw = cand.get("value") or cand.get("text")
        text = _normalize(str(raw or ""))
        if not text:
            continue
        if not semantic_accept("patient_name", text)[0]:
            continue
        if text not in shaped:
            shaped.append(text)
    if len(shaped) < 2:
        return False
    for i, left in enumerate(shaped):
        for right in shaped[i + 1 :]:
            if not values_conflict_equivalent("patient_name", left, right):
                return True
    return False


def _local_names_need_vision_tiebreak(
    candidates: list[Mapping[str, Any]] | None,
) -> bool:
    """True when local engines are not normalize-exact, even if confusable.

    ``KIVERALARAA`` vs ``RIVERA LARAA`` is one K/R substitution. That is not a
    hard identity conflict, but it also is not independent E2. Vision is the
    tie-break; it is not allowed to invent a third name.
    """
    from packages.evidence.normalization import normalize_agreement_value

    norms: list[str] = []
    for cand in candidates or []:
        engine = str(cand.get("engine") or "").casefold()
        if "gpt4o" in engine or "gpt-4o" in engine or "claude" in engine or "anthropic" in engine:
            continue
        text = _normalize(str(cand.get("value") or cand.get("text") or ""))
        if not text or not semantic_accept("patient_name", text)[0]:
            continue
        norm = normalize_agreement_value("patient_name", text)
        if norm and norm not in norms:
            norms.append(norm)
    return len(norms) >= 2


def name_needs_gpt4o(
    *,
    local_accepted: bool,
    candidates: list[Mapping[str, Any]] | None = None,
    gap_class: str | None = None,
) -> bool:
    """Run gpt-4o on name crops for unread ink or genuine local engine conflict.

    Cascade may accept a shaped primary while paddle/rapid still disagree
    (CONFLICT_MARGIN later). Those conflicts need a crop vision arbitrator —
    not another local OCR pass. Confusable-but-not-exact locals (KIVERA vs
    RIVERA) also need that arbitrator so E2 is not skipped — unless stop
    ladder already has soft-equivalent multi-family settlement.
    """
    try:
        from packages.extraction_recovery.cloud_stop_ladder import (
            cloud_stop_ladder_enabled,
            name_locals_settled,
        )

        if cloud_stop_ladder_enabled() and name_locals_settled(candidates):
            return False
    except Exception:  # noqa: BLE001
        pass
    if name_local_engine_conflict(candidates) or _local_names_need_vision_tiebreak(
        candidates
    ):
        return True
    gap = (gap_class or "").upper()
    if gap in _NAME_GAPS and not local_accepted:
        return True
    if not local_accepted:
        local_engines: set[str] = set()
        for cand in candidates or []:
            eng = str(cand.get("engine") or "").casefold()
            if "gpt4o" in eng or "gpt-4o" in eng or "claude" in eng or "anthropic" in eng:
                continue
            if str(cand.get("value") or cand.get("text") or "").strip():
                local_engines.add(eng)
        # One local engine cannot mint E2. Vision residual is the arbitrator.
        if len(local_engines) < 2:
            return True
        has_shaped = False
        for cand in candidates or []:
            text = _normalize(str(cand.get("value") or cand.get("text") or ""))
            if text and semantic_accept("patient_name", text)[0]:
                has_shaped = True
                break
        return not has_shaped
    # Cascade can accept one shaped local name. A second engine that only
    # emitted a fragment ("M") is not E2, so Claude still has to read the crop.
    shaped_locals: set[str] = set()
    for cand in candidates or []:
        eng = str(cand.get("engine") or "").casefold()
        if "gpt4o" in eng or "gpt-4o" in eng or "claude" in eng or "anthropic" in eng:
            continue
        text = _normalize(str(cand.get("value") or cand.get("text") or ""))
        if text and semantic_accept("patient_name", text)[0]:
            shaped_locals.add(eng)
    if len(shaped_locals) < 2:
        return True
    return False


def _crop_image(image: Image.Image, bbox: tuple[int, int, int, int]) -> Image.Image:
    x0, y0, x1, y1 = bbox
    pad = 10
    x0, y0 = max(0, int(x0) - pad), max(0, int(y0) - pad)
    x1, y1 = max(x0 + 1, int(x1) + pad), max(y0 + 1, int(y1) + pad)
    x1, y1 = min(image.width, x1), min(image.height, y1)
    crop = image.crop((x0, y0, x1, y1)).convert("RGB")
    if crop.width < 120 or crop.height < 40:
        scale = max(2, int(140 / max(crop.width, 1)))
        crop = crop.resize(
            (crop.width * scale, crop.height * scale), Image.Resampling.LANCZOS
        )
    return crop


class _AzureGpt4oCropRecognizer:
    """Crop recognizer over Azure gpt-4o or Anthropic Claude Sonnet (env-selected)."""

    def __init__(self, adapter: Any | None = None, *, provider: str | None = None) -> None:
        self._adapter = adapter
        self._provider = (provider or "").strip().casefold()
        self.engine_name = "azure_gpt4o_crop"

    def _resolve_provider(self) -> str:
        if self._provider:
            return self._provider
        raw = (os.environ.get("CDP_CROP_VLM_PROVIDER") or "").strip().casefold()
        if raw in {"claude", "anthropic", "sonnet"}:
            return "claude"
        try:
            from packages.settings import Settings

            if Settings().anthropic_crop_residual_enabled:
                return "claude"
        except Exception:  # noqa: BLE001
            pass
        return "gpt4o"

    def _ensure(self) -> Any:
        if self._adapter is not None:
            return self._adapter
        provider = self._resolve_provider()
        if provider == "claude":
            from workers.vlm_fallback.factory import build_anthropic_claude_adapter

            # 35s fail-fast — parallel 1000 runs must not stall 60s on hung sockets.
            timeout_raw = (os.environ.get("CDP_VLM_CROP_TIMEOUT_SECONDS") or "35").strip()
            try:
                timeout_seconds = max(10.0, float(timeout_raw))
            except ValueError:
                timeout_seconds = 35.0
            self._adapter = build_anthropic_claude_adapter(
                enabled=True, timeout_seconds=timeout_seconds
            )
            self.engine_name = "anthropic_claude_crop"
            return self._adapter

        from packages.settings import Settings

        if _build_gpt4o_vision_adapter is None:
            raise RuntimeError(
                "gpt-4o vision adapter factory not configured; "
                "call configure_gpt4o_vision_adapter_factory from composition root"
            )
        settings = Settings()
        if not settings.azure_ai_evaluation_enabled:
            raise RuntimeError("Azure gpt-4o evaluation disabled")
        if not (
            settings.azure_openai_endpoint
            and settings.azure_openai_api_key
            and settings.azure_ai_evaluation_deployment
        ):
            raise RuntimeError("Azure OpenAI credentials missing")
        self._adapter = _build_gpt4o_vision_adapter(
            endpoint=settings.azure_openai_endpoint,
            deployment=settings.azure_ai_evaluation_deployment,
            api_version=settings.azure_openai_api_version or "2024-10-21",
            api_key=settings.azure_openai_api_key,
            enabled=True,
            timeout_seconds=45.0,
        )
        self.engine_name = "azure_gpt4o_crop"
        return self._adapter

    def recognize_fields(
        self,
        crops: Mapping[str, Image.Image],
        *,
        field_types: Mapping[str, str],
        descriptions: Mapping[str, str],
        prior_candidates: Mapping[str, list[str]],
    ) -> Mapping[str, Gpt4oCropResidualResult]:
        from packages.vlm_schema import VLMFieldRequest

        adapter = self._ensure()
        provider = self._resolve_provider()
        stamp = (
            "ANTHROPIC_CLAUDE_CROP"
            if provider == "claude"
            else "AZURE_GPT4O_CROP"
        )
        reason_prefix = "CLAUDE" if provider == "claude" else "GPT4O"
        pngs: dict[str, bytes] = {}
        requests: list[VLMFieldRequest] = []
        for name, crop in crops.items():
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            pngs[name] = buf.getvalue()
            requests.append(
                VLMFieldRequest(
                    field_name=name,
                    field_type=field_types.get(name, "text"),
                    expected_description=descriptions.get(name, name),
                    prior_ocr_candidates=list(prior_candidates.get(name) or [])[:6],
                )
            )
        results = adapter.extract_fields(pngs, requests)
        try:
            from packages.recovery.vlm_token_meter import record_vlm_call

            record_vlm_call(
                provider=provider,
                engine=self.engine_name,
                field_names=list(crops.keys()),
                kind="crop_residual",
                usage=getattr(adapter, "last_usage", None) or {},
                ok=True,
            )
        except Exception:  # noqa: BLE001 — metering must never break OCR
            pass
        out: dict[str, Gpt4oCropResidualResult] = {}
        for item in results:
            raw = _normalize(item.value)
            name = item.field_name
            if name.casefold() in _DOB_FIELDS:
                shaped_val, shaped = _shape_dob(raw)
            elif name.casefold() in _ID_FIELDS:
                shaped_val, shaped = _shape_id(raw)
            elif name.casefold() in _NAME_FIELDS:
                shaped_val, shaped = _shape_name(name, raw)
            elif name.casefold() in _CHARGE_FIELDS:
                shaped_val, shaped = _shape_charge(raw)
            else:
                shaped_val, shaped = raw, False
            insuff = bool(item.insufficient_evidence) or not raw
            reason = (
                f"{reason_prefix}_ABSTAIN"
                if insuff
                else (f"{reason_prefix}_SHAPED" if shaped else f"{reason_prefix}_UNSHAPED")
            )
            out[name] = Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value=shaped_val if shaped else raw,
                raw_value=raw,
                shaped=shaped and not insuff,
                insufficient_evidence=insuff,
                reason=reason,
                engine=self.engine_name,
                confidence=float(item.confidence),
                validation_results=(stamp,),
            )
        for name in crops:
            if name not in out:
                out[name] = Gpt4oCropResidualResult(
                    attempted=True,
                    configured=True,
                    review_only=True,
                    value=None,
                    raw_value=None,
                    shaped=False,
                    insufficient_evidence=True,
                    reason=f"{reason_prefix}_MISSING_FIELD",
                    engine=self.engine_name,
                    confidence=0.0,
                    validation_results=(stamp,),
                )
        return out


def _dob_cell_bboxes(
    bbox: tuple[int, int, int, int],
) -> list[tuple[int, int, int, int]]:
    """Split a DOB ROI into approximate MM / DD / YY cells (equal thirds)."""
    x0, y0, x1, y1 = bbox
    width = max(1, x1 - x0)
    third = max(1, width // 3)
    cells = []
    for i in range(3):
        cx0 = x0 + i * third
        cx1 = x1 if i == 2 else x0 + (i + 1) * third
        cells.append((cx0, y0, max(cx0 + 1, cx1), y1))
    return cells


def _dob_description(prior: list[str], *, cell_mode: bool = False) -> str:
    base = (
        "Handwritten CMS-1500 box 3 patient date of birth with MM DD YY cells. "
        "Return MM/DD/YYYY when digits are visible. Colon/comma/period between "
        "digit groups are damaged separators (e.g. 7:30.77 means 07/30/1977). "
        "Abstain only if the crop is empty or truly illegible."
    )
    if cell_mode:
        base = (
            "Three cropped CMS-1500 DOB cells (month, day, year). "
            "Read each cell's handwritten digits and return one MM/DD/YYYY. "
            "Abstain only if cells are empty."
        )
    hints = [p for p in prior if p and p.strip()]
    if hints:
        base += " Prior OCR saw: " + " | ".join(hints[:4]) + "."
    return base


def run_gpt4o_crop_residual(
    *,
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    field_name: str,
    prior_candidates: list[str] | None = None,
    engine: Gpt4oCropRecognizer | None = None,
) -> Gpt4oCropResidualResult:
    if not gpt4o_crop_residual_enabled():
        return Gpt4oCropResidualResult(
            attempted=False,
            configured=False,
            review_only=True,
            value=None,
            raw_value=None,
            shaped=False,
            insufficient_evidence=True,
            reason="GPT4O_CROP_DISABLED",
        )
    name = (field_name or "").casefold()
    if (
        name not in _DOB_FIELDS
        and name not in _ID_FIELDS
        and name not in _NAME_FIELDS
        and name not in _CHARGE_FIELDS
    ):
        return Gpt4oCropResidualResult(
            attempted=False,
            configured=True,
            review_only=True,
            value=None,
            raw_value=None,
            shaped=False,
            insufficient_evidence=True,
            reason="GPT4O_FIELD_UNSUPPORTED",
        )
    prior = list(prior_candidates or [])
    crop = _crop_image(image, bbox)
    if name in _DOB_FIELDS:
        ftype, desc = "date", _dob_description(prior)
    elif name in _CHARGE_FIELDS:
        ftype = "currency"
        desc = (
            "CMS-1500 charge amount cell (box 28 total or service-line charges). "
            "Read the handwritten or typed dollar amount only from the ink "
            "(e.g. 233.00). Ignore labels like TOTAL CHARGE, NPI, diagnosis "
            "pointers, and any suggested prior OCR values if they disagree "
            "with the visible digits. Prefer the full amount with cents. "
            "Abstain if the crop has no amount ink."
        )
        # Do not append prior OCR for charges — priors anchored wrong digit
        # reads (222 vs 233) and false dual-engine corroboration.
    elif name in _NAME_FIELDS:
        ftype = "text"
        which = "patient" if "patient" in name else "insured"
        desc = (
            f"CMS-1500 handwritten or typed {which} person name cell. "
            "Read the person's name only (LAST FIRST or FIRST LAST as written). "
            "Ignore printed labels like PATIENT NAME, INSURED NAME, FIRST, LAST, "
            "MI. Prefer the spacing and token order that matches the ink. "
            "Abstain if the crop has no name ink."
        )
        if prior:
            desc += " Prior OCR saw: " + " | ".join(prior[:4]) + "."
    else:
        desc = (
            "Handwritten or typed CMS-1500 box 1a insured/member ID. "
            "Alphanumeric ID only — not phone, NPI, EIN, or printed labels. "
            "Read every digit carefully; when prior OCR engines disagree on "
            "digits, choose the ID that matches the ink."
        )
        if prior:
            desc += " Prior OCR saw: " + " | ".join(prior[:4]) + "."
        ftype = "code"
    recognizer = engine or _AzureGpt4oCropRecognizer()

    def _call(
        crop_image: Image.Image,
        *,
        description: str,
        field_type: str,
    ) -> Gpt4oCropResidualResult:
        from packages.extraction_recovery.vlm_crop_lock import vlm_crop_lock

        try:
            with vlm_crop_lock():
                mapped = recognizer.recognize_fields(
                    {field_name: crop_image},
                    field_types={field_name: field_type},
                    descriptions={field_name: description},
                    prior_candidates={field_name: prior},
                )
        except Exception as exc:  # noqa: BLE001 — residual must fail closed
            return Gpt4oCropResidualResult(
                attempted=True,
                configured=True,
                review_only=True,
                value=None,
                raw_value=None,
                shaped=False,
                insufficient_evidence=True,
                reason=f"GPT4O_ERROR:{type(exc).__name__}",
                validation_results=(f"ERROR:{exc}"[:160],),
            )
        return mapped.get(field_name) or Gpt4oCropResidualResult(
            attempted=True,
            configured=True,
            review_only=True,
            value=None,
            raw_value=None,
            shaped=False,
            insufficient_evidence=True,
            reason="GPT4O_EMPTY_RESPONSE",
        )

    # Single full-box crop first.
    result = _call(crop, description=desc, field_type=ftype)

    # Charge abstain on a tight ROI → taller/wider crop retry (faint ink / clip).
    if name in _CHARGE_FIELDS and (result.insufficient_evidence or not result.shaped):
        expanded = _expand_charge_bbox(bbox, (image.width, image.height))
        if expanded != bbox:
            with contextlib.suppress(Exception):
                retry = _call(
                    _crop_image(image, expanded),
                    description=desc + " Crop is expanded around the charge cell.",
                    field_type=ftype,
                )
                if retry.shaped and not retry.insufficient_evidence:
                    return Gpt4oCropResidualResult(
                        attempted=True,
                        configured=True,
                        review_only=retry.review_only,
                        value=retry.value,
                        raw_value=retry.raw_value,
                        shaped=True,
                        insufficient_evidence=False,
                        reason="GPT4O_EXPANDED_CHARGE_SHAPED",
                        engine=retry.engine,
                        confidence=retry.confidence,
                        validation_results=tuple(retry.validation_results)
                        + ("GPT4O_EXPANDED_CHARGE",),
                    )

    # DOB abstain → MM/DD/YY cell-split retry (DI hint already in description).
    if name in _DOB_FIELDS and (result.insufficient_evidence or not result.shaped):
        cells = _dob_cell_bboxes(bbox)
        with contextlib.suppress(Exception):
            cell_imgs = [_crop_image(image, cell) for cell in cells]
            widths = [c.width for c in cell_imgs]
            height = max(c.height for c in cell_imgs)
            strip = Image.new(
                "RGB", (sum(widths) + 4, height), color=(255, 255, 255)
            )
            x = 0
            for cell_img in cell_imgs:
                strip.paste(cell_img, (x, 0))
                x += cell_img.width + 2
            retry = _call(
                strip,
                description=_dob_description(prior, cell_mode=True),
                field_type="date",
            )
            if retry.shaped and not retry.insufficient_evidence:
                return Gpt4oCropResidualResult(
                    attempted=True,
                    configured=True,
                    review_only=retry.review_only,
                    value=retry.value,
                    raw_value=retry.raw_value,
                    shaped=True,
                    insufficient_evidence=False,
                    reason="GPT4O_CELL_SPLIT_SHAPED",
                    engine=retry.engine,
                    confidence=retry.confidence,
                    validation_results=tuple(retry.validation_results)
                    + ("GPT4O_CELL_SPLIT",),
                )
    return result


def residual_candidate_dict(
    result: Gpt4oCropResidualResult,
    *,
    bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
) -> dict[str, Any] | None:
    if not result.attempted or not result.value:
        return None
    width, height = image_size
    x0, y0, x1, y1 = bbox
    conf = float(result.confidence) if result.confidence is not None else 0.9
    engine = str(result.engine or "azure_gpt4o_crop")
    claude = "claude" in engine.casefold() or "anthropic" in engine.casefold()
    return {
        "value": result.value,
        "raw_value": result.raw_value or result.value,
        "engine": engine,
        "model_name": "claude-sonnet-4-6" if claude else "gpt-4o",
        "model_version": "anthropic-messages" if claude else "azure-openai",
        "preprocessing_variant": (
            "claude_crop_residual" if claude else "gpt4o_crop_residual"
        ),
        "preprocessing_version": "cascade-v12-3n",
        "raw_confidence": conf,
        "calibrated_confidence": conf,
        "confidence": conf,
        "reason_code": result.reason,
        "validation_results": list(result.validation_results),
        "shadow_review_only": result.review_only,
        "latency_ms": 0.0,
        "bounding_box": {
            "x0": float(x0),
            "y0": float(y0),
            "x1": float(x1),
            "y1": float(y1),
            "image_width": float(width),
            "image_height": float(height),
        },
        "bbox": list(bbox),
        "image_width": float(width),
        "image_height": float(height),
        "reason": result.reason,
    }


def recover_empty_financial_service_lines(
    *,
    image: Image.Image,
    line_bboxes: list[tuple[int, int, int, int]],
    engine: Gpt4oCropRecognizer | None = None,
    local_recognize: Callable[
        [tuple[int, int, int, int]],
        tuple[list[dict[str, Any]], list[dict[str, Any]], str],
    ]
    | None = None,
) -> list[dict[str, Any]]:
    """gpt-4o sweep of empty service-line charge cells (EMPTY_FINANCIAL_INK path).

    Local OCR often skips blank-looking rows; faint charge ink still needs a
    vision residual. For each bbox: gpt-4o first; when shaped, optionally re-run
    local OCR for corroboration (SINGLE_LINE_GPT4O_LOCAL). Never invents amounts
    when the model abstains.
    """
    if not empty_financial_ink_gpt4o_enabled():
        return []
    out: list[dict[str, Any]] = []
    limit = empty_financial_ink_max_lines()
    for index, bbox in enumerate(line_bboxes[:limit]):
        x0, y0, x1, y1 = (int(v) for v in bbox)
        if x1 <= x0 or y1 <= y0:
            continue
        # Ruling-only / blank cells must not be GPT-filled (hallucinated 260s).
        with contextlib.suppress(Exception):
            from packages.image_evidence import InkDisposition, analyze_roi

            crop = image.crop(
                (
                    max(0, x0),
                    max(0, y0),
                    min(image.width, x1),
                    min(image.height, y1),
                )
            )
            evidence = analyze_roi(crop, ocr_empty=True, geometry_valid=True)
            if (
                evidence.disposition == InkDisposition.BLANK_CONFIRMED
                and "FORM_RULING_ONLY" in evidence.reasons
            ):
                continue
        result = run_gpt4o_crop_residual(
            image=image,
            bbox=(x0, y0, x1, y1),
            field_name="charges",
            prior_candidates=[],
            engine=engine,
        )
        attempts: list[dict[str, Any]] = [
            {
                "engine": "azure_gpt4o_crop",
                "reason": result.reason,
                "observation": {"text": result.raw_value or result.value or ""},
            }
        ]
        candidates: list[dict[str, Any]] = []
        value = None
        raw = None
        reason = f"EMPTY_FINANCE_GPT4O:{result.reason}"
        if result.shaped and result.value and not result.insufficient_evidence:
            cand = residual_candidate_dict(
                result,
                bbox=(x0, y0, x1, y1),
                image_size=(image.width, image.height),
            )
            if cand is not None:
                candidates.append(cand)
            value = result.value
            raw = result.raw_value or result.value
            # Local corroboration pass — fail-closed without inventing.
            if local_recognize is not None:
                with contextlib.suppress(Exception):
                    local_cands, local_attempts, local_reason = local_recognize(
                        (x0, y0, x1, y1)
                    )
                    attempts.extend(list(local_attempts or []))
                    reason = f"{reason}|{local_reason}"
                    for lc in local_cands or []:
                        if isinstance(lc, dict) and (lc.get("value") or "").strip():
                            candidates.append(lc)
        if not value:
            continue
        out.append(
            {
                "line_number": index + 1,
                "charges": value,
                "charge_amount": value,
                "raw_charges": raw,
                "canonical_region": [x0, y0, x1, y1],
                "candidates": candidates,
                "attempts": attempts,
                "router_reason": f"{reason}|EMPTY_FINANCE_GPT4O_SWEEP",
                "status": "OBSERVED",
            }
        )
    return out


def maybe_attach_gpt4o_crop_to_field_row(
    field_row: Mapping[str, Any],
    *,
    image: Image.Image,
    gap_class: str | None = None,
    engine: Gpt4oCropRecognizer | None = None,
) -> dict[str, Any]:
    """Attach gpt-4o crop residual for DOB, ID, name conflict/ink, or charge."""
    updated = dict(field_row)
    name = str(field_row.get("field") or "")
    key = name.casefold()
    cascade = dict(field_row.get("cascade") or {})
    local_accepted = bool(cascade.get("accepted"))
    if key in _DOB_FIELDS:
        try:
            from packages.extraction_recovery.dob_azure_di_residual import (
                dob_residual_bbox,
            )

            bbox = dob_residual_bbox(field_row)
        except Exception:  # noqa: BLE001
            bbox = tuple(
                field_row.get("ocr_region") or field_row.get("canonical_region") or ()
            )
    else:
        bbox = tuple(field_row.get("ocr_region") or field_row.get("canonical_region") or ())
    if len(bbox) != 4:
        return updated

    try:
        from packages.extraction_recovery.cloud_stop_ladder import (
            should_skip_all_cloud,
            should_skip_second_cloud,
        )

        if should_skip_all_cloud(name, field_row) or should_skip_second_cloud(field_row):
            meta = dict(updated.get("cloud_stop_ladder") or {})
            meta["skipped"] = (
                "LOCALS_SETTLED"
                if should_skip_all_cloud(name, field_row)
                else "ONE_CLOUD_SHAPED"
            )
            updated["cloud_stop_ladder"] = meta
            return updated
    except Exception:  # noqa: BLE001
        pass

    prior = [
        str(c.get("value") or c.get("text") or "").strip()
        for c in (field_row.get("candidates") or [])
        if (c.get("value") or c.get("text"))
    ]
    # Include DI residual as prior hint for charge/DOB.
    di_meta = field_row.get("azure_di_residual") or {}
    if di_meta.get("value"):
        prior = [str(di_meta.get("value")), *prior]

    if key in _DOB_FIELDS:
        trocr = field_row.get("trocr_residual") or {}
        di = field_row.get("azure_di_residual") or {}
        if not dob_needs_gpt4o(
            local_accepted=local_accepted,
            trocr_shaped=bool(trocr.get("date_shaped") and not trocr.get("review_only")),
            azure_di_shaped=bool(di.get("date_shaped") and not di.get("review_only")),
            gap_class=gap_class,
            candidates=list(field_row.get("candidates") or []),
        ):
            return updated
    elif key in _ID_FIELDS:
        cascade_value = None
        for step in cascade.get("steps") or []:
            if step.get("accepted"):
                cascade_value = step.get("selected_value")
                break
        if cascade_value is None and prior:
            cascade_value = prior[0]
        if not id_needs_gpt4o(
            cascade_value,
            accepted=local_accepted,
            candidates=list(field_row.get("candidates") or []),
        ):
            return updated
    elif key in _NAME_FIELDS:
        if not name_needs_gpt4o(
            local_accepted=local_accepted,
            candidates=list(field_row.get("candidates") or []),
            gap_class=gap_class,
        ):
            return updated
    elif key in _CHARGE_FIELDS:
        di = field_row.get("azure_di_residual") or {}
        di_shaped = bool(
            di.get("currency_shaped") and not di.get("review_only") and di.get("value")
        )
        line_meta = field_row.get("observed_line_charges")
        line_charges = (
            [str(x) for x in line_meta if x]
            if isinstance(line_meta, list)
            else None
        )
        if not charge_needs_gpt4o(
            local_accepted=local_accepted,
            azure_di_shaped=di_shaped,
            gap_class=gap_class or "EMPTY_FINANCIAL_INK",
            candidates=list(field_row.get("candidates") or []),
            observed_line_charges=line_charges,
        ):
            return updated
    else:
        return updated

    result = run_gpt4o_crop_residual(
        image=image,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        field_name=name,
        prior_candidates=prior,
        engine=engine,
    )
    accept = gpt4o_crop_accept_enabled()
    effective_review_only = result.review_only and not (accept and result.shaped)
    updated["gpt4o_crop_residual"] = {
        "attempted": result.attempted,
        "configured": result.configured,
        "review_only": effective_review_only,
        "shaped": result.shaped,
        "insufficient_evidence": result.insufficient_evidence,
        "reason": result.reason,
        "value": result.value,
        "confidence": result.confidence,
    }
    promoted = result
    if accept and result.shaped and result.review_only:
        promoted = Gpt4oCropResidualResult(
            attempted=result.attempted,
            configured=result.configured,
            review_only=False,
            value=result.value,
            raw_value=result.raw_value,
            shaped=True,
            insufficient_evidence=False,
            reason="GPT4O_SHAPED_ACCEPTED",
            engine=result.engine,
            confidence=result.confidence,
            validation_results=tuple(
                v for v in result.validation_results if v != "SHADOW_REVIEW_ONLY"
            )
            or ("AZURE_GPT4O_CROP",),
        )
        updated["gpt4o_crop_residual"]["review_only"] = False
        updated["gpt4o_crop_residual"]["reason"] = promoted.reason
    candidate = residual_candidate_dict(
        promoted,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        image_size=(image.width, image.height),
    )
    if candidate is not None:
        candidates = list(updated.get("candidates") or [])
        candidates.insert(0, candidate)
        updated["candidates"] = candidates
        if promoted.shaped and not promoted.review_only:
            cascade_out = dict(cascade)
            # Charge: only promote over empty local; keep line-sum conflicts for HITL.
            promote_accept = True
            if key in _CHARGE_FIELDS:
                # Redesign: GPT-4o is never sole monetary authority.
                try:
                    from packages.architecture.redesign_stack import (
                        gpt_may_be_sole_monetary_authority,
                    )

                    sole_ok = gpt_may_be_sole_monetary_authority()
                except Exception:  # noqa: BLE001
                    sole_ok = False
                local_value = str(cascade.get("value") or "").strip()
                has_local = False
                if not local_value:
                    for prior_c in candidates[1:]:
                        seed = str(
                            prior_c.get("value") or prior_c.get("raw_value") or ""
                        ).strip()
                        eng = str(prior_c.get("engine") or "").casefold()
                        if "gpt4o" in eng or "gpt-4o" in eng or "claude" in eng or "anthropic" in eng:
                            continue
                        if seed:
                            local_value = seed
                            has_local = True
                            break
                else:
                    has_local = True
                if not sole_ok and not has_local:
                    promote_accept = False
                    updated["gpt4o_crop_residual"]["reason"] = (
                        f"{promoted.reason}|GPT_NOT_MONETARY_AUTHORITY"
                    )
                elif local_value and local_accepted:
                    with contextlib.suppress(Exception):
                        from packages.claim_evidence.line_sum_authority import (
                            amounts_corroborate,
                        )

                        if not amounts_corroborate(local_value, promoted.value):
                            promote_accept = False
                            updated["gpt4o_crop_residual"]["reason"] = (
                                f"{promoted.reason}|LOCAL_CONFLICT_REVIEW"
                            )
                # Calibration: annotate acceptance risk (never invents STP).
                with contextlib.suppress(Exception):
                    from packages.architecture.acceptance_risk import (
                        estimate_acceptance_risk,
                    )

                    risk = estimate_acceptance_risk(
                        field_name=key,
                        calibrated_confidence=float(promoted.confidence or 0.0),
                        engine_count=1 + (1 if has_local else 0),
                        dual_engine_agree=bool(has_local and promote_accept),
                        gpt4o_only=not has_local,
                        gap_class=gap_class,
                    )
                    updated["acceptance_risk"] = {
                        "risk": risk.risk,
                        "method": risk.method,
                        "review_recommended": risk.review_recommended,
                    }
                    if risk.review_recommended and not has_local:
                        promote_accept = False
            if key in _DOB_FIELDS and promote_accept:
                # Vision date is not sole authority. A local read must carry
                # at least four of the same digits (handwriting 7:30.77 vs
                # 07/30/1977). A lone "1" cannot confirm 07/02/1980.
                gpt_digits = re.sub(r"\D", "", str(promoted.value or ""))

                def _is_subseq(needle: str, hay: str) -> bool:
                    idx = 0
                    for ch in hay:
                        if idx < len(needle) and ch == needle[idx]:
                            idx += 1
                    return bool(needle) and idx == len(needle)

                local_ok = False
                for prior_c in candidates[1:]:
                    eng = str(prior_c.get("engine") or "").casefold()
                    if "gpt4o" in eng or "gpt-4o" in eng or "claude" in eng or "anthropic" in eng:
                        continue
                    digits = re.sub(
                        r"\D",
                        "",
                        str(prior_c.get("raw_value") or prior_c.get("value") or ""),
                    )
                    if len(digits) < 4:
                        continue
                    if _is_subseq(digits, gpt_digits) or _is_subseq(gpt_digits, digits):
                        local_ok = True
                        break
                if not local_ok:
                    promote_accept = False
                    updated["gpt4o_crop_residual"]["reason"] = (
                        f"{promoted.reason}|GPT_DOB_NEEDS_LOCAL_DIGITS"
                    )
            if key in _NAME_FIELDS and promote_accept:
                # Vision name is not sole authority. At least one local read
                # must be the same person (exact or confusable). Unrelated
                # GPT text cannot replace the cascade value.
                from packages.candidate_reconciliation.reconciler import (
                    values_conflict_equivalent,
                )
                from packages.evidence.normalization import normalize_agreement_value

                gpt_name = str(promoted.value or "")
                local_ok = False
                for prior_c in candidates[1:]:
                    eng = str(prior_c.get("engine") or "").casefold()
                    if "gpt4o" in eng or "gpt-4o" in eng or "claude" in eng or "anthropic" in eng:
                        continue
                    local = str(
                        prior_c.get("raw_value") or prior_c.get("value") or ""
                    ).strip()
                    if not local:
                        continue
                    if normalize_agreement_value(key, gpt_name) == (
                        normalize_agreement_value(key, local)
                    ) or values_conflict_equivalent(key, gpt_name, local):
                        local_ok = True
                        break
                if not local_ok:
                    promote_accept = False
                    updated["gpt4o_crop_residual"]["reason"] = (
                        f"{promoted.reason}|GPT_NAME_NEEDS_LOCAL"
                    )
            if promote_accept:
                cascade_out["accepted"] = True
                cascade_out["accept_reason"] = f"GPT4O_CROP_RESIDUAL:{promoted.reason}"
                cascade_out["value"] = promoted.value
                updated["cascade"] = cascade_out
                updated["status"] = "FIELD_ACCEPTED"
    return updated
