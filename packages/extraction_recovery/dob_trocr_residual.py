"""Crop-scoped TrOCR for DOB handwriting residuals (preferred over Azure DI).

Runs only after local Rapid→Paddle/Tesseract exhaustion on handwriting /
ambiguous-digit DOB gaps. Never on the common path. Date-shaped TrOCR
reads are eligible for cascade accept (local model); unshaped results stay HITL.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from PIL import Image

from packages.extraction_recovery.field_cascade import semantic_accept
from packages.extraction_recovery.span_selection import select_field_span
from packages.tool_escalation import EscalationTool, plan_field_escalation

_DOB_FIELDS = frozenset({"patient_dob", "date_of_birth"})
_HANDWRITING_GAPS = frozenset({"HANDWRITING_UNREADABLE", "AMBIGUOUS_DIGIT_FRAGMENTS"})

_get_shared_trocr_adapter: Callable[..., Any] | None = None


def configure_trocr_adapter_factory(factory: Callable[..., Any]) -> None:
    """Composition root injects shared TrOCR adapter construction."""
    global _get_shared_trocr_adapter
    _get_shared_trocr_adapter = factory


@dataclass(frozen=True)
class DobTrOCRResidualResult:
    attempted: bool
    configured: bool
    review_only: bool
    value: str | None
    raw_value: str | None
    date_shaped: bool
    reason: str
    confidence: float | None = None
    engine: str = "trocr"
    validation_results: tuple[str, ...] = ()


class DobCropRecognizer(Protocol):
    def recognize_crop(
        self, crop: Image.Image, field_name: str
    ) -> DobTrOCRResidualResult: ...


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
    """Span-select then semantic-accept so YY century repair applies."""
    text = _normalize_dob_text(raw)
    if not text:
        return None, False
    span = select_field_span(text, "DATE", field_name)
    selected = _normalize_dob_text(span.selected_text) or text
    shaped = bool(selected) and semantic_accept(field_name, selected)[0]
    return selected, shaped


def _recognize_with_trocr_adapter(
    adapter: Any,
    crop: Image.Image,
    field_name: str,
    *,
    review_only: bool,
) -> DobTrOCRResidualResult:
    try:
        result = adapter.recognize(crop)
    except Exception as exc:  # noqa: BLE001
        return DobTrOCRResidualResult(
            attempted=True,
            configured=True,
            review_only=review_only,
            value=None,
            raw_value=None,
            date_shaped=False,
            reason=f"TROCR_ERROR:{type(exc).__name__}",
        )
    raw = _normalize_dob_text(getattr(result, "text", None))
    if not raw or bool(getattr(result, "insufficient_evidence", False)):
        return DobTrOCRResidualResult(
            attempted=True,
            configured=True,
            review_only=review_only,
            value=None,
            raw_value=raw,
            date_shaped=False,
            confidence=getattr(result, "confidence", None),
            reason="TROCR_INSUFFICIENT_EVIDENCE",
        )
    value, shaped = _shape_dob_text(field_name, raw)
    confidence = float(getattr(result, "confidence", 0.0) or 0.0)
    validations: tuple[str, ...] = ("HANDWRITTEN_STYLE", "TROCR_CROP_RESIDUAL")
    if review_only:
        validations = (*validations, "SHADOW_REVIEW_ONLY")
    return DobTrOCRResidualResult(
        attempted=True,
        configured=True,
        review_only=review_only,
        value=value,
        raw_value=raw,
        date_shaped=shaped,
        confidence=confidence,
        reason=(
            "TROCR_DATE_SHAPED_REVIEW_ONLY"
            if shaped and review_only
            else "TROCR_DATE_SHAPED"
            if shaped
            else "TROCR_UNSHAPED"
        ),
        validation_results=validations,
    )


def run_dob_trocr_residual(
    *,
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    field_name: str = "patient_dob",
    gap_class: str | None = "HANDWRITING_UNREADABLE",
    local_accepted: bool = False,
    trocr_attempted: bool = False,
    settings: Any | None = None,
    engine: Any | None = None,
) -> DobTrOCRResidualResult:
    """Invoke crop-scoped TrOCR when the planner selects it for DOB."""
    if not is_dob_handwriting_residual(
        field_name=field_name,
        gap_class=gap_class,
        local_accepted=local_accepted,
    ):
        return DobTrOCRResidualResult(
            attempted=False,
            configured=False,
            review_only=False,
            value=None,
            raw_value=None,
            date_shaped=False,
            reason="NOT_DOB_HANDWRITING_RESIDUAL",
        )

    decision = plan_field_escalation(
        gap_class=gap_class or "HANDWRITING_UNREADABLE",
        field_name=field_name,
        trocr_attempted=trocr_attempted,
    )
    if decision.tool != EscalationTool.TROCR:
        return DobTrOCRResidualResult(
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
            return _recognize_with_trocr_adapter(
                engine, crop, field_name, review_only=decision.review_only
            )

        try:
            from packages.settings import get_settings
        except Exception as exc:  # noqa: BLE001
            return DobTrOCRResidualResult(
                attempted=False,
                configured=False,
                review_only=False,
                value=None,
                raw_value=None,
                date_shaped=False,
                reason=f"IMPORT_ERROR:{type(exc).__name__}",
            )

        if _get_shared_trocr_adapter is None:
            return DobTrOCRResidualResult(
                attempted=False,
                configured=False,
                review_only=False,
                value=None,
                raw_value=None,
                date_shaped=False,
                reason="TROCR_FACTORY_UNCONFIGURED",
            )

        cfg = settings or get_settings()
        adapter = _get_shared_trocr_adapter(
            model_name=getattr(cfg, "trocr_model_name", None)
            or "microsoft/trocr-base-handwritten",
            device=getattr(cfg, "trocr_device", "auto") or "auto",
            min_confidence=float(getattr(cfg, "trocr_min_confidence", 0.55) or 0.55),
        )
        return _recognize_with_trocr_adapter(
            adapter, crop, field_name, review_only=decision.review_only
        )
    finally:
        crop.close()


def residual_candidate_dict(
    result: DobTrOCRResidualResult,
    *,
    bbox: tuple[int, int, int, int] | None = None,
    image_size: tuple[int, int] | None = None,
) -> dict[str, Any] | None:
    """Serialize a TrOCR residual into an OCR-candidates-compatible row."""
    if not result.attempted or not result.value:
        return None
    width = int(image_size[0]) if image_size else max(1, int((bbox or (0, 0, 1, 1))[2]))
    height = int(image_size[1]) if image_size else max(1, int((bbox or (0, 0, 1, 1))[3]))
    x0, y0, x1, y1 = bbox or (0, 0, width, height)
    payload: dict[str, Any] = {
        "value": result.value,
        "raw_value": result.raw_value or result.value,
        "engine": result.engine,
        "model_name": "microsoft/trocr-base-handwritten",
        "model_version": "unknown",
        "preprocessing_variant": "dob_trocr_crop_residual",
        "preprocessing_version": "cascade-v12-trocr",
        "raw_confidence": result.confidence,
        "calibrated_confidence": result.confidence,
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
    return payload


def maybe_attach_dob_trocr_to_field_row(
    field_row: Mapping[str, Any],
    *,
    image: Image.Image,
    gap_class: str | None,
    settings: Any | None = None,
    engine: Any | None = None,
) -> dict[str, Any]:
    """Return an updated field row with optional TrOCR candidate (+ cascade accept)."""
    name = str(field_row.get("field") or "")
    cascade = field_row.get("cascade") or {}
    local_accepted = bool(cascade.get("accepted"))
    try:
        from packages.extraction_recovery.dob_azure_di_residual import dob_residual_bbox

        bbox = dob_residual_bbox(field_row)
    except Exception:  # noqa: BLE001
        bbox = tuple(field_row.get("ocr_region") or field_row.get("canonical_region") or ())
    if len(bbox) != 4:
        return dict(field_row)
    result = run_dob_trocr_residual(
        image=image,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        field_name=name,
        gap_class=gap_class,
        local_accepted=local_accepted,
        settings=settings,
        engine=engine,
    )
    updated = dict(field_row)
    updated["trocr_residual"] = {
        "attempted": result.attempted,
        "configured": result.configured,
        "review_only": result.review_only,
        "date_shaped": result.date_shaped,
        "reason": result.reason,
        "value": result.value,
        "confidence": result.confidence,
    }
    candidate = residual_candidate_dict(
        result,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        image_size=(image.width, image.height),
    )
    if candidate is not None:
        candidates = list(updated.get("candidates") or [])
        candidates.insert(0, candidate)
        updated["candidates"] = candidates
        if result.date_shaped and not result.review_only:
            cascade_out = dict(cascade)
            cascade_out["accepted"] = True
            cascade_out["accept_reason"] = f"TROCR_RESIDUAL:{result.reason}"
            updated["cascade"] = cascade_out
            updated["status"] = "FIELD_ACCEPTED"
    return updated
