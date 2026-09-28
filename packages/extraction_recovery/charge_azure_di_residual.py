"""Crop-scoped Azure Document Intelligence for service-line charge residuals.

Runs only after local CHARGE_DIGITS_FAST → paddle/rapid verify still leaves
the cell empty or unresolved. Never on the common path. Full-page Azure DI
corners stay off; this is one cheap charge-cell crop (same pattern as DOB).
"""

from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from PIL import Image

from packages.extraction_recovery.field_cascade import semantic_accept
from packages.extraction_recovery.span_selection import select_field_span
from packages.recovery.azure_di_meter import azure_di_error_detail, record_azure_di_call
from packages.tool_escalation import EscalationTool, plan_field_escalation

_CHARGE_FIELDS = frozenset(
    {"charges", "charge_amount", "total_charge", "total_charges", "amount_paid"}
)
_CHARGE_GAPS = frozenset(
    {
        "EMPTY_FINANCIAL_INK",
        "CHARGE_LOCAL_EXHAUSTED",
        "CHARGE_DIGIT_CONFLICT",
        "AMBIGUOUS_DIGIT_FRAGMENTS",
        "AMBIGUOUS_CHARGE_DIGITS",
    }
)


@dataclass(frozen=True)
class ChargeAzureDiResidualResult:
    attempted: bool
    configured: bool
    review_only: bool
    value: str | None
    raw_value: str | None
    currency_shaped: bool
    reason: str
    engine: str = "azure_document_intelligence_read"
    validation_results: tuple[str, ...] = ()


class ChargeCropRecognizer(Protocol):
    def recognize_crop(
        self, crop: Image.Image, field_name: str
    ) -> ChargeAzureDiResidualResult: ...


def _env_on(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }


def azure_di_charge_residual_enabled() -> bool:
    # Accuracy-first: DI charge crops ON by default so dual-local Box28 with
    # 0 lines can mint CHARGE_DI_LOCAL_CONFIRMED (strong E4). Disable with
    # CDP_AZURE_DI_CHARGE_RESIDUAL=0 only for latency experiments.
    return _env_on("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")


def azure_di_charge_accept_enabled() -> bool:
    return _env_on("CDP_AZURE_DI_CHARGE_ACCEPT", "1")


def is_charge_local_residual(
    *,
    field_name: str,
    gap_class: str | None,
    local_accepted: bool,
    corroborate: bool = False,
) -> bool:
    # Corroboration path: still run DI after a weak/single-engine local accept.
    if local_accepted and not corroborate:
        return False
    if (field_name or "").casefold() not in _CHARGE_FIELDS:
        return False
    gap = (gap_class or "").upper()
    return gap in _CHARGE_GAPS or gap == "" or corroborate


def _crop_image(image: Image.Image, bbox: tuple[int, int, int, int]) -> Image.Image:
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = max(x0 + 1, int(x1)), max(y0 + 1, int(y1))
    return image.crop((x0, y0, x1, y1))


def _expand_bbox(
    bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
    *,
    pad_ratio: float = 0.35,
) -> tuple[int, int, int, int]:
    """Pad a charge crop so Box 28 amount ink just outside a tight ROI is visible.

    JAJ.022-class: tight DI crop returned label soup (``C -- C L $``) while a
    modestly wider crop reads ``635.00``.
    """
    x0, y0, x1, y1 = (int(v) for v in bbox)
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)
    pad_x = max(8, int(w * pad_ratio))
    pad_y = max(8, int(h * pad_ratio))
    iw, ih = int(image_size[0]), int(image_size[1])
    return (
        max(0, x0 - pad_x),
        max(0, y0 - pad_y),
        min(iw, x1 + pad_x),
        min(ih, y1 + pad_y),
    )


def charge_crop_looks_blank(crop: Image.Image, *, max_ink_ratio: float = 0.004) -> bool:
    """True when a charge crop has essentially no dark ink (empty box-28 / empty line).

    Under F0 (1 analyze/min), skipping blank crops avoids a full-minute wait that
    cannot recover currency. Threshold is conservative: faint pencil still fires DI.
    """
    if crop.width < 2 or crop.height < 2:
        return True
    gray = crop.convert("L")
    # Downsample for speed on large ROIs.
    sample = gray.resize(
        (min(64, gray.width), min(32, gray.height)),
        Image.Resampling.BILINEAR,
    )
    hist = sample.histogram()
    total = max(1, sum(hist))
    # Ink = darker than mid-gray; printed rules alone stay below threshold on empty cells.
    ink = sum(hist[:110])
    return (ink / total) <= max_ink_ratio


def _normalize_charge_text(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    return cleaned or None


def _shape_charge_text(field_name: str, raw: str | None) -> tuple[str | None, bool]:
    """Span-select then semantic-accept so DI noise around an amount can shape."""
    text = _normalize_charge_text(raw)
    if not text:
        return None, False
    # Ruling-split geometry first: ``7 $ 157 :07`` / ``$ 222 |22`` are dollars|cents
    # ink. Bare ``\d{2,6}`` matches would otherwise invent ``157.00`` / ``222.00``
    # and drop the cents column (DJKH.002/005/010 remain-25 charge HITL).
    try:
        from packages.claim_evidence.line_charge_selector import _ruling_split_amount
    except Exception:  # noqa: BLE001
        _ruling_split_amount = None  # type: ignore[assignment]
    if _ruling_split_amount is not None:
        ruled = _ruling_split_amount(text)
        if ruled:
            shaped = bool(semantic_accept(field_name, ruled)[0]) or bool(
                re.fullmatch(r"\d+\.\d{2}", ruled)
            )
            if shaped:
                return ruled, True
    # Prefer explicit currency; fall back to digit spans from noisy DI lines.
    span = select_field_span(text, "CURRENCY", field_name)
    selected = _normalize_charge_text(span.selected_text) or text
    if not re.search(r"\d", selected or ""):
        return selected, False
    # Strip label bleed; keep first currency-shaped token.
    m = re.search(
        r"\$?\d{1,3}(?:,\d{3})*\.\d{2}|\$?\d{2,6}(?:\.\d{2})?",
        selected or "",
    )
    if m:
        amount = m.group(0).lstrip("$").replace(",", "")
        if "." not in amount and re.fullmatch(r"\d{2,6}", amount):
            amount = f"{amount}.00"
        selected = amount
    shaped = bool(selected) and semantic_accept(field_name, selected)[0]
    if not shaped and selected and re.fullmatch(r"\d+\.\d{2}", selected):
        shaped = True
    return selected, shaped


def _recognize_with_azure_read_engine(
    read_engine: Any,
    crop: Image.Image,
    field_name: str,
    *,
    review_only: bool,
) -> ChargeAzureDiResidualResult:
    from packages.domain.common import BoundingBox
    from packages.domain.enums import ClaimFormType, FieldCriticality
    from packages.ocr.contracts import OCRRequest

    # Azure DI rejects tiny / blank crops — upscale charge cells like DOB.
    working = crop
    min_side = 64
    min_w, min_h = 160, 64
    ow, oh = working.size
    if ow < min_w or oh < min_h or min(ow, oh) < min_side:
        scale = max(min_w / max(1, ow), min_h / max(1, oh), 1.0)
        nw, nh = max(min_w, int(ow * scale)), max(min_h, int(oh * scale))
        working = working.resize((nw, nh), Image.Resampling.LANCZOS)

    box = BoundingBox(
        x0=0.0,
        y0=0.0,
        x1=float(working.width),
        y1=float(working.height),
        image_width=working.width,
        image_height=working.height,
    )
    request = OCRRequest(
        document_id="charge-azure-di-residual",
        page_number=1,
        field_name=field_name,
        field_type="currency",
        form_type=ClaimFormType.CMS1500,
        image=working,
        bounding_box=box,
        criticality=FieldCriticality.CRITICAL,
        scope="FIELD_CROP",
    )
    try:
        candidates = read_engine.recognize(request)
    except Exception as exc:  # noqa: BLE001
        detail = azure_di_error_detail(exc)
        with contextlib.suppress(Exception):
            record_azure_di_call(
                kind="charge_crop",
                field_name=field_name,
                ok=False,
                detail=detail,
            )
        return ChargeAzureDiResidualResult(
            attempted=True,
            configured=True,
            review_only=review_only,
            value=None,
            raw_value=None,
            currency_shaped=False,
            reason=f"AZURE_DI_ERROR:{detail}",
        )
    with contextlib.suppress(Exception):
        record_azure_di_call(
            kind="charge_crop",
            field_name=field_name,
            ok=bool(candidates),
            detail="ok" if candidates else "empty",
        )
    if not candidates:
        return ChargeAzureDiResidualResult(
            attempted=True,
            configured=True,
            review_only=review_only,
            value=None,
            raw_value=None,
            currency_shaped=False,
            reason="AZURE_DI_EMPTY",
        )
    lead = candidates[0]
    raw = _normalize_charge_text(
        getattr(lead, "raw_value", None) or getattr(lead, "value", None)
    )
    value, shaped = _shape_charge_text(field_name, raw)
    validations = tuple(getattr(lead, "validation_results", ()) or ())
    if "SHADOW_REVIEW_ONLY" not in validations:
        validations = (*validations, "SHADOW_REVIEW_ONLY")
    return ChargeAzureDiResidualResult(
        attempted=True,
        configured=True,
        review_only=review_only,
        value=value,
        raw_value=raw,
        currency_shaped=shaped,
        reason=(
            "AZURE_DI_CURRENCY_SHAPED_REVIEW_ONLY"
            if shaped and review_only
            else "AZURE_DI_CURRENCY_SHAPED"
            if shaped
            else "AZURE_DI_UNSHAPED"
        ),
        validation_results=validations,
    )


def run_charge_azure_di_residual(
    *,
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    field_name: str = "charges",
    gap_class: str | None = "CHARGE_LOCAL_EXHAUSTED",
    local_accepted: bool = False,
    azure_di_attempted: bool = False,
    settings: Any | None = None,
    engine: Any | None = None,
    corroborate: bool = False,
) -> ChargeAzureDiResidualResult:
    """Invoke crop-scoped Azure DI Read when local charge OCR is exhausted."""
    if not azure_di_charge_residual_enabled():
        return ChargeAzureDiResidualResult(
            attempted=False,
            configured=False,
            review_only=True,
            value=None,
            raw_value=None,
            currency_shaped=False,
            reason="AZURE_DI_CHARGE_RESIDUAL_DISABLED",
        )
    if not is_charge_local_residual(
        field_name=field_name,
        gap_class=gap_class,
        local_accepted=local_accepted,
        corroborate=corroborate,
    ):
        return ChargeAzureDiResidualResult(
            attempted=False,
            configured=False,
            review_only=True,
            value=None,
            raw_value=None,
            currency_shaped=False,
            reason="NOT_CHARGE_LOCAL_RESIDUAL",
        )

    decision = plan_field_escalation(
        gap_class=gap_class or "CHARGE_LOCAL_EXHAUSTED",
        field_name=field_name,
        regional_ocr_attempted=True,
        empty_financial_ink=True,
        azure_di_attempted=azure_di_attempted,
    )
    if decision.tool != EscalationTool.AZURE_DOCUMENT_INTELLIGENCE_READ:
        return ChargeAzureDiResidualResult(
            attempted=False,
            configured=False,
            review_only=decision.review_only,
            value=None,
            raw_value=None,
            currency_shaped=False,
            reason=f"PLANNER_SKIPPED:{decision.tool.value}",
        )

    def _recognize_one(
        crop: Image.Image, *, read_engine: Any | None
    ) -> ChargeAzureDiResidualResult:
        if engine is not None:
            if hasattr(engine, "recognize_crop"):
                return engine.recognize_crop(crop, field_name)
            return _recognize_with_azure_read_engine(
                engine, crop, field_name, review_only=decision.review_only
            )
        assert read_engine is not None
        return _recognize_with_azure_read_engine(
            read_engine, crop, field_name, review_only=decision.review_only
        )

    crop = _crop_image(image, bbox)
    read_engine: Any | None = None
    try:
        # Skip billable DI on empty white cells (injected engines still run so
        # unit tests can force a shaped residual on blank fixtures).
        if engine is None and charge_crop_looks_blank(crop):
            return ChargeAzureDiResidualResult(
                attempted=False,
                configured=True,
                review_only=decision.review_only,
                value=None,
                raw_value=None,
                currency_shaped=False,
                reason="AZURE_DI_SKIPPED_BLANK_CROP",
            )
        if engine is None:
            try:
                from packages.azure_di_contracts import (
                    AzureDocumentIntelligenceConfigurationError,
                    azure_document_intelligence_configured,
                    build_azure_read_engine,
                )
                from packages.settings import get_settings
            except Exception as exc:  # noqa: BLE001
                return ChargeAzureDiResidualResult(
                    attempted=False,
                    configured=False,
                    review_only=True,
                    value=None,
                    raw_value=None,
                    currency_shaped=False,
                    reason=f"IMPORT_ERROR:{type(exc).__name__}",
                )

            cfg = settings or get_settings()
            if not azure_document_intelligence_configured(cfg):
                return ChargeAzureDiResidualResult(
                    attempted=False,
                    configured=False,
                    review_only=True,
                    value=None,
                    raw_value=None,
                    currency_shaped=False,
                    reason="AZURE_DI_NOT_CONFIGURED",
                )
            try:
                read_engine = build_azure_read_engine(cfg)
            except AzureDocumentIntelligenceConfigurationError as exc:
                return ChargeAzureDiResidualResult(
                    attempted=False,
                    configured=False,
                    review_only=True,
                    value=None,
                    raw_value=None,
                    currency_shaped=False,
                    reason=f"AZURE_DI_CONFIG_ERROR:{exc}",
                )
            except RuntimeError as exc:
                return ChargeAzureDiResidualResult(
                    attempted=False,
                    configured=False,
                    review_only=True,
                    value=None,
                    raw_value=None,
                    currency_shaped=False,
                    reason=f"AZURE_DI_FACTORY_UNCONFIGURED:{exc}",
                )

        primary = _recognize_one(crop, read_engine=read_engine)
        if primary.currency_shaped or not primary.attempted:
            return primary

        # Tight ROI sometimes clips Box 28 dollars; one padded retry only.
        expanded = _expand_bbox(bbox, image.size, pad_ratio=0.35)
        if expanded == tuple(int(v) for v in bbox):
            return primary
        crop2 = _crop_image(image, expanded)
        try:
            if engine is None and charge_crop_looks_blank(crop2):
                return primary
            retry = _recognize_one(crop2, read_engine=read_engine)
        finally:
            crop2.close()
        if retry.currency_shaped:
            return ChargeAzureDiResidualResult(
                attempted=retry.attempted,
                configured=retry.configured,
                review_only=retry.review_only,
                value=retry.value,
                raw_value=retry.raw_value,
                currency_shaped=retry.currency_shaped,
                reason=f"{retry.reason}:EXPANDED_CROP",
                engine=retry.engine,
                validation_results=retry.validation_results,
            )
        return primary
    finally:
        crop.close()


def residual_candidate_dict(
    result: ChargeAzureDiResidualResult,
    *,
    bbox: tuple[int, int, int, int] | None = None,
    image_size: tuple[int, int] | None = None,
) -> dict[str, Any] | None:
    if not result.attempted or not result.value:
        return None
    width = int(image_size[0]) if image_size else max(1, int((bbox or (0, 0, 1, 1))[2]))
    height = int(image_size[1]) if image_size else max(1, int((bbox or (0, 0, 1, 1))[3]))
    x0, y0, x1, y1 = bbox or (0, 0, width, height)
    return {
        "value": result.value,
        "raw_value": result.raw_value or result.value,
        "engine": result.engine,
        "model_name": "prebuilt-read",
        "model_version": "unknown",
        "preprocessing_variant": "charge_azure_di_crop_residual",
        "preprocessing_version": "cascade-v12-azure-di",
        "raw_confidence": 0.85,
        "calibrated_confidence": 0.85,
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
    }


def promote_currency_shaped(
    result: ChargeAzureDiResidualResult,
) -> ChargeAzureDiResidualResult:
    """Drop SHADOW_REVIEW_ONLY when currency-shaped accept is enabled."""
    if not (
        azure_di_charge_accept_enabled()
        and result.currency_shaped
        and result.review_only
        and result.value
    ):
        return result
    validations = tuple(
        v for v in result.validation_results if v != "SHADOW_REVIEW_ONLY"
    )
    return ChargeAzureDiResidualResult(
        attempted=result.attempted,
        configured=result.configured,
        review_only=False,
        value=result.value,
        raw_value=result.raw_value,
        currency_shaped=True,
        reason="AZURE_DI_CURRENCY_SHAPED",
        engine=result.engine,
        validation_results=validations or ("AZURE_DI_CHARGE_CROP",),
    )


def maybe_attach_charge_azure_di_to_field_row(
    field_row: Mapping[str, Any],
    *,
    image: Image.Image,
    gap_class: str | None,
    settings: Any | None = None,
    engine: Any | None = None,
    corroborate: bool = False,
) -> dict[str, Any]:
    """Return an updated field row with optional Azure DI charge candidate."""
    name = str(field_row.get("field") or "charges")
    cascade = field_row.get("cascade") or {}
    local_accepted = bool(cascade.get("accepted"))
    bbox = tuple(field_row.get("ocr_region") or field_row.get("canonical_region") or ())
    if len(bbox) != 4:
        return dict(field_row)
    try:
        from packages.extraction_recovery.cloud_stop_ladder import (
            should_skip_all_cloud,
            should_skip_second_cloud,
        )

        if should_skip_all_cloud(name, field_row) or should_skip_second_cloud(field_row):
            updated = dict(field_row)
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
    do_corroborate = corroborate or (
        local_accepted
        and azure_di_charge_residual_enabled()
        and _env_on("CDP_AZURE_DI_CHARGE_CORROBORATE", "1")
    )
    effective_gap = gap_class
    if do_corroborate and local_accepted:
        effective_gap = gap_class or "AMBIGUOUS_CHARGE_DIGITS"
    result = run_charge_azure_di_residual(
        image=image,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        field_name=name,
        gap_class=effective_gap,
        local_accepted=local_accepted,
        settings=settings,
        engine=engine,
        corroborate=do_corroborate,
    )
    promoted = promote_currency_shaped(result)
    effective_review_only = promoted.review_only
    updated = dict(field_row)
    updated["azure_di_residual"] = {
        "attempted": promoted.attempted,
        "configured": promoted.configured,
        "review_only": effective_review_only,
        "currency_shaped": promoted.currency_shaped,
        "reason": promoted.reason,
        "value": promoted.value,
    }
    candidate = residual_candidate_dict(
        promoted,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        image_size=image.size,
    )
    if candidate is not None:
        cands = list(updated.get("candidates") or [])
        cands.append(candidate)
        updated["candidates"] = cands
        if not effective_review_only and promoted.currency_shaped and promoted.value:
            local_value = str(cascade.get("value") or "").strip()
            if not local_value:
                for prior in cands[:-1]:
                    seed = str(prior.get("value") or prior.get("raw_value") or "").strip()
                    if seed:
                        local_value = seed
                        break
            # Promote DI to accepted only when it fills empty ink or corroborates
            # local / line-sum (tolerance or digit-drop twin). Non-twin conflict
            # stays as a competing candidate for HITL — never silent override.
            promote_accept = True
            if local_accepted and local_value:
                try:
                    from packages.claim_evidence.line_sum_authority import (
                        amounts_corroborate,
                    )
                except Exception:  # noqa: BLE001
                    amounts_corroborate = None  # type: ignore[assignment]
                if amounts_corroborate is not None and not amounts_corroborate(
                    local_value, promoted.value
                ):
                    promote_accept = False
                    updated["azure_di_residual"]["reason"] = (
                        f"{promoted.reason}|LOCAL_CONFLICT_REVIEW"
                    )
            if promote_accept:
                cascade_out = dict(cascade)
                cascade_out["accepted"] = True
                cascade_out["accept_reason"] = f"AZURE_DI_RESIDUAL:{promoted.reason}"
                cascade_out["value"] = promoted.value
                updated["cascade"] = cascade_out
                updated["status"] = "OBSERVED"
    return updated


def try_charge_azure_di_crop(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    *,
    field_name: str = "charges",
    gap_class: str = "CHARGE_LOCAL_EXHAUSTED",
    engine: Any | None = None,
) -> ChargeAzureDiResidualResult:
    """Service-line helper: DI last resort after local empty/conflict."""
    result = run_charge_azure_di_residual(
        image=image,
        bbox=bbox,
        field_name=field_name,
        gap_class=gap_class,
        local_accepted=False,
        engine=engine,
    )
    return promote_currency_shaped(result)
