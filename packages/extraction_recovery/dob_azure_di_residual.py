"""Crop-scoped Azure Document Intelligence for DOB-only residuals.

Runs only after local Rapid→Paddle/Tesseract exhaustion on handwriting /
ambiguous-digit DOB gaps. Never on the common path. Results stay
SHADOW_REVIEW_ONLY until secondary policy promotes the route.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from PIL import Image

from packages.extraction_recovery.field_cascade import semantic_accept
from packages.extraction_recovery.span_selection import select_field_span
from packages.recovery.azure_di_meter import azure_di_error_detail, record_azure_di_call
from packages.tool_escalation import EscalationTool, plan_field_escalation

_DOB_FIELDS = frozenset({"patient_dob", "date_of_birth"})
_HANDWRITING_GAPS = frozenset({"HANDWRITING_UNREADABLE", "AMBIGUOUS_DIGIT_FRAGMENTS"})
# Year-wide cascade strips under this height starve DI/Claude (JEH.036 ~18px).
_MIN_DOB_CROP_HEIGHT_PX = 28


def dob_residual_bbox(field_row: Mapping[str, Any]) -> tuple[float, ...]:
    """Full Box 3 cell when the cascade left a razor-thin year strip."""
    ocr = tuple(field_row.get("ocr_region") or ())
    canon = tuple(field_row.get("canonical_region") or ())
    if len(ocr) == 4:
        try:
            height = float(ocr[3]) - float(ocr[1])
        except (TypeError, ValueError):
            height = 0.0
        if height >= _MIN_DOB_CROP_HEIGHT_PX:
            return ocr
    if len(canon) == 4:
        return canon
    return ocr if len(ocr) == 4 else ()


@dataclass(frozen=True)
class DobAzureDiResidualResult:
    attempted: bool
    configured: bool
    review_only: bool
    value: str | None
    raw_value: str | None
    date_shaped: bool
    reason: str
    engine: str = "azure_document_intelligence_read"
    validation_results: tuple[str, ...] = ()


class DobCropRecognizer(Protocol):
    def recognize_crop(
        self, crop: Image.Image, field_name: str
    ) -> DobAzureDiResidualResult: ...


def is_dob_handwriting_residual(
    *,
    field_name: str,
    gap_class: str | None,
    local_accepted: bool,
) -> bool:
    if local_accepted:
        return False
    if (field_name or "").casefold() not in _DOB_FIELDS:
        return False
    gap = (gap_class or "").upper()
    return gap in _HANDWRITING_GAPS or gap == ""


def _crop_image(image: Image.Image, bbox: tuple[int, int, int, int]) -> Image.Image:
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = max(x0 + 1, int(x1)), max(y0 + 1, int(y1))
    return image.crop((x0, y0, x1, y1))


def _normalize_dob_text(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    return cleaned or None


def _shape_dob_text(field_name: str, raw: str | None) -> tuple[str | None, bool]:
    """Span-select then semantic-accept so DI noise around a date can still shape."""
    text = _normalize_dob_text(raw)
    if not text:
        return None, False
    span = select_field_span(text, "DATE", field_name)
    selected = _normalize_dob_text(span.selected_text) or text
    shaped = bool(selected) and semantic_accept(field_name, selected)[0]
    return selected, shaped


def _recognize_with_azure_read_engine(
    read_engine: Any,
    crop: Image.Image,
    field_name: str,
    *,
    review_only: bool,
) -> DobAzureDiResidualResult:
    from packages.domain.common import BoundingBox
    from packages.domain.enums import ClaimFormType, FieldCriticality
    from packages.ocr.contracts import OCRRequest

    # Azure DI rejects tiny / empty crops (InvalidContentDimensions). Upscale
    # short DOB cells to a safe minimum before analyze — still one cheap crop.
    working = crop
    min_side = 64
    min_w, min_h = 200, 80
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
        document_id="dob-azure-di-residual",
        page_number=1,
        field_name=field_name,
        field_type="date",
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
                kind="dob_crop",
                field_name=field_name,
                ok=False,
                detail=detail,
            )
        return DobAzureDiResidualResult(
            attempted=True,
            configured=True,
            review_only=review_only,
            value=None,
            raw_value=None,
            date_shaped=False,
            reason=f"AZURE_DI_ERROR:{detail}",
        )
    with contextlib.suppress(Exception):
        record_azure_di_call(
            kind="dob_crop",
            field_name=field_name,
            ok=bool(candidates),
            detail="ok" if candidates else "empty",
        )
    if not candidates:
        return DobAzureDiResidualResult(
            attempted=True,
            configured=True,
            review_only=review_only,
            value=None,
            raw_value=None,
            date_shaped=False,
            reason="AZURE_DI_EMPTY",
        )
    lead = candidates[0]
    raw = _normalize_dob_text(getattr(lead, "raw_value", None) or getattr(lead, "value", None))
    value, shaped = _shape_dob_text(field_name, raw)
    validations = tuple(getattr(lead, "validation_results", ()) or ())
    if "SHADOW_REVIEW_ONLY" not in validations:
        validations = (*validations, "SHADOW_REVIEW_ONLY")
    return DobAzureDiResidualResult(
        attempted=True,
        configured=True,
        review_only=review_only,
        value=value,
        raw_value=raw,
        date_shaped=shaped,
        reason=(
            "AZURE_DI_DATE_SHAPED_REVIEW_ONLY"
            if shaped and review_only
            else "AZURE_DI_DATE_SHAPED"
            if shaped
            else "AZURE_DI_UNSHAPED"
        ),
        validation_results=validations,
    )


def run_dob_azure_di_residual(
    *,
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    field_name: str = "patient_dob",
    gap_class: str | None = "HANDWRITING_UNREADABLE",
    local_accepted: bool = False,
    trocr_attempted: bool = True,
    azure_di_attempted: bool = False,
    settings: Any | None = None,
    engine: Any | None = None,
) -> DobAzureDiResidualResult:
    """Invoke crop-scoped Azure DI Read when the planner selects it for DOB.

    Default ``trocr_attempted=True`` so Azure DI is the fallback after local
    TrOCR (preferred) rather than being skipped by the planner.
    """
    if not is_dob_handwriting_residual(
        field_name=field_name,
        gap_class=gap_class,
        local_accepted=local_accepted,
    ):
        return DobAzureDiResidualResult(
            attempted=False,
            configured=False,
            review_only=True,
            value=None,
            raw_value=None,
            date_shaped=False,
            reason="NOT_DOB_HANDWRITING_RESIDUAL",
        )

    decision = plan_field_escalation(
        gap_class=gap_class or "HANDWRITING_UNREADABLE",
        field_name=field_name,
        trocr_attempted=trocr_attempted,
        azure_di_attempted=azure_di_attempted,
    )
    if decision.tool != EscalationTool.AZURE_DOCUMENT_INTELLIGENCE_READ:
        return DobAzureDiResidualResult(
            attempted=False,
            configured=False,
            review_only=decision.review_only,
            value=None,
            raw_value=None,
            date_shaped=False,
            reason=f"PLANNER_SKIPPED:{decision.tool.value}",
        )

    crop = _crop_image(image, bbox)
    try:
        if engine is not None:
            if hasattr(engine, "recognize_crop"):
                return engine.recognize_crop(crop, field_name)
            return _recognize_with_azure_read_engine(
                engine, crop, field_name, review_only=decision.review_only
            )

        try:
            from packages.azure_di_contracts import (
                AzureDocumentIntelligenceConfigurationError,
                azure_document_intelligence_configured,
                build_azure_read_engine,
            )
            from packages.settings import get_settings
        except Exception as exc:  # noqa: BLE001
            return DobAzureDiResidualResult(
                attempted=False,
                configured=False,
                review_only=True,
                value=None,
                raw_value=None,
                date_shaped=False,
                reason=f"IMPORT_ERROR:{type(exc).__name__}",
            )

        cfg = settings or get_settings()
        if not azure_document_intelligence_configured(cfg):
            return DobAzureDiResidualResult(
                attempted=False,
                configured=False,
                review_only=True,
                value=None,
                raw_value=None,
                date_shaped=False,
                reason="AZURE_DI_NOT_CONFIGURED",
            )
        try:
            read_engine = build_azure_read_engine(cfg)
        except AzureDocumentIntelligenceConfigurationError as exc:
            return DobAzureDiResidualResult(
                attempted=False,
                configured=False,
                review_only=True,
                value=None,
                raw_value=None,
                date_shaped=False,
                reason=f"AZURE_DI_CONFIG_ERROR:{exc}",
            )
        except RuntimeError as exc:
            return DobAzureDiResidualResult(
                attempted=False,
                configured=False,
                review_only=True,
                value=None,
                raw_value=None,
                date_shaped=False,
                reason=f"AZURE_DI_FACTORY_UNCONFIGURED:{exc}",
            )
        return _recognize_with_azure_read_engine(
            read_engine, crop, field_name, review_only=decision.review_only
        )
    finally:
        crop.close()


def residual_candidate_dict(
    result: DobAzureDiResidualResult,
    *,
    bbox: tuple[int, int, int, int] | None = None,
    image_size: tuple[int, int] | None = None,
) -> dict[str, Any] | None:
    """Serialize a DI residual into an OCR-candidates-compatible row."""
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
        "preprocessing_variant": "dob_azure_di_crop_residual",
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


def maybe_attach_dob_azure_di_to_field_row(
    field_row: Mapping[str, Any],
    *,
    image: Image.Image,
    gap_class: str | None,
    settings: Any | None = None,
    engine: Any | None = None,
    trocr_attempted: bool = True,
) -> dict[str, Any]:
    """Return an updated field row with optional Azure DI candidate (+ cascade accept)."""
    import os

    name = str(field_row.get("field") or "")
    cascade = field_row.get("cascade") or {}
    local_accepted = bool(cascade.get("accepted"))
    # Prefer the full Box 3 cell when the cascade left a razor-thin year strip
    # (M0471JEH.036 ocr_region height ~18px → Claude abstain / DI miss).
    bbox = dob_residual_bbox(field_row)
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
    result = run_dob_azure_di_residual(
        image=image,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        field_name=name,
        gap_class=gap_class,
        local_accepted=local_accepted,
        trocr_attempted=trocr_attempted,
        settings=settings,
        engine=engine,
    )
    # Date-shaped DOB crops are cheap and high-signal — accept when enabled
    # (default on). Keeps full-page corners off for cost.
    accept_shaped = (os.environ.get("CDP_AZURE_DI_DOB_ACCEPT") or "1").strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }
    effective_review_only = result.review_only and not (accept_shaped and result.date_shaped)
    updated = dict(field_row)
    updated["azure_di_residual"] = {
        "attempted": result.attempted,
        "configured": result.configured,
        "review_only": effective_review_only,
        "date_shaped": result.date_shaped,
        "reason": result.reason,
        "value": result.value,
    }
    # Rebuild candidate with accept semantics when promoting date-shaped crops.
    promoted = result
    if accept_shaped and result.date_shaped and result.review_only:
        validations = tuple(
            v for v in result.validation_results if v != "SHADOW_REVIEW_ONLY"
        )
        promoted = DobAzureDiResidualResult(
            attempted=result.attempted,
            configured=result.configured,
            review_only=False,
            value=result.value,
            raw_value=result.raw_value,
            date_shaped=result.date_shaped,
            reason="AZURE_DI_DATE_SHAPED",
            engine=result.engine,
            validation_results=validations or ("AZURE_DI_DOB_CROP",),
        )
    candidate = residual_candidate_dict(
        promoted,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        image_size=(image.width, image.height),
    )
    if candidate is not None:
        candidates = list(updated.get("candidates") or [])
        candidates.insert(0, candidate)
        updated["candidates"] = candidates
        if promoted.date_shaped and not promoted.review_only:
            cascade_out = dict(cascade)
            cascade_out["accepted"] = True
            cascade_out["accept_reason"] = f"AZURE_DI_RESIDUAL:{promoted.reason}"
            updated["cascade"] = cascade_out
            updated["status"] = "FIELD_ACCEPTED"
    return updated
