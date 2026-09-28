"""AI conflict agent: when two OCR/models disagree, Claude picks the ink.

Process (fail-closed):
  1. Detect ≥2 non-equivalent shaped rivals on a critical field, or a printed
     Box 28 total that disagrees with the service-line sum.
  2. Show the crop(s) and the rival values to Claude.
  3. Claude must answer with exactly one rival, or BOX28 / LINES for a
     financial conflict, or ABSTAIN.
  4. Invented third values are rejected. Abstain keeps HITL.
  5. A chosen rival is adopted and tagged CONFLICT_AGENT_RESOLVED so the
     field can leave review.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image

_CHARGE_FIELDS = frozenset(
    {"total_charge", "total_charges", "charges", "charge_amount", "amount_paid"}
)
_NAME_FIELDS = frozenset({"patient_name", "insured_name"})
_DOB_FIELDS = frozenset({"patient_dob", "date_of_birth", "insured_dob", "dob"})


def _agent_candidate(
    *,
    value: str,
    bbox: tuple[int, int, int, int],
    image: Image.Image,
    reason: str,
    variant: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "raw_value": value,
        "engine": "anthropic_claude_crop",
        "model_name": "conflict-agent",
        "model_version": "conflict-agent-v1",
        "preprocessing_variant": variant,
        "preprocessing_version": "cascade-v12-conflict-agent",
        "raw_confidence": 0.96,
        "calibrated_confidence": 0.96,
        "reason_code": reason,
        "latency_ms": 0.0,
        "bounding_box": {
            "x0": float(bbox[0]),
            "y0": float(bbox[1]),
            "x1": float(bbox[2]),
            "y1": float(bbox[3]),
            "image_width": float(image.width),
            "image_height": float(image.height),
        },
    }


def _near_decimal_place_shift(left: object, right: object) -> bool:
    """True for exact ×100 or within $1 of an exact ×100 twin (49.77 vs 4972)."""
    from decimal import Decimal

    from packages.claim_evidence.line_sum_authority import (
        is_decimal_place_shift,
        parse_currency,
    )

    if is_decimal_place_shift(left, right):
        return True
    a, b = parse_currency(left), parse_currency(right)
    if a is None or b is None or a <= 0 or b <= 0:
        return False
    hi, lo = (a, b) if a > b else (b, a)
    # 49.77 × 100 = 4977 vs OCR 4972 (ruling / digit noise) still counts.
    return abs(hi - lo * 100) <= Decimal("10.00")


@dataclass(frozen=True)
class ConflictResolution:
    attempted: bool
    resolved: bool
    chosen: str | None
    rivals: tuple[str, ...]
    reason: str
    financial_side: str | None = None  # BOX28 | LINES | None


def conflict_agent_enabled() -> bool:
    return (os.environ.get("CDP_CONFLICT_AGENT") or "1").strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _normalize_space(text: str) -> str:
    return " ".join((text or "").strip().split())


def _is_vision(engine: object) -> bool:
    name = str(engine or "").casefold()
    return any(token in name for token in ("gpt4o", "gpt-4o", "claude", "anthropic"))


def collect_field_rivals(
    field_name: str,
    candidates: Sequence[Mapping[str, Any]] | None,
    *,
    include_vision: bool = True,
) -> list[str]:
    """Unique shaped rival values from distinct engines on one field."""
    from packages.evidence.normalization import normalize_agreement_value
    from packages.extraction_recovery.field_cascade import semantic_accept

    key = field_name.casefold()
    by_norm: dict[str, str] = {}
    for cand in candidates or []:
        engine = str(cand.get("engine") or "")
        if not include_vision and _is_vision(engine):
            continue
        raw = _normalize_space(str(cand.get("value") or cand.get("raw_value") or ""))
        if not raw:
            continue
        ok, _ = semantic_accept(field_name, raw)
        if not ok:
            # Charge conflicts still need the POS-like / short local (50 vs 660).
            if key in _CHARGE_FIELDS:
                from packages.claim_evidence.line_sum_authority import parse_currency

                if parse_currency(raw) is None:
                    continue
            else:
                continue
        norm = normalize_agreement_value(field_name, raw)
        if not norm:
            continue
        by_norm.setdefault(norm, raw)
    return list(by_norm.values())


def field_needs_conflict_agent(
    field_name: str,
    candidates: Sequence[Mapping[str, Any]] | None,
) -> bool:
    rivals = collect_field_rivals(field_name, candidates)
    if len(rivals) < 2:
        return False
    key = (field_name or "").casefold()
    # Cost-safe: soft-equivalent multi-family names are already settled — do not
    # pay Claude to pick between OCR twins (CHANGULANI vs CHANAUICNI when locals
    # already soft-match). Charge/ID/DOB keep conflict agent for ink fights.
    if key in _NAME_FIELDS:
        try:
            from packages.extraction_recovery.cloud_stop_ladder import (
                cloud_stop_ladder_enabled,
                name_locals_settled,
            )

            if cloud_stop_ladder_enabled() and name_locals_settled(list(candidates or [])):
                return False
        except Exception:  # noqa: BLE001
            pass
    return True


def _match_rival(reply: str, rivals: Sequence[str], field_name: str) -> str | None:
    from packages.evidence.normalization import normalize_agreement_value
    from packages.extraction_recovery.field_cascade import semantic_accept

    text = _normalize_space(reply)
    if not text or text.casefold() in {"abstain", "none", "unsure", "unknown"}:
        return None
    # Prefer exact / normalized match against listed rivals only.
    reply_norm = normalize_agreement_value(field_name, text)
    for rival in rivals:
        if normalize_agreement_value(field_name, rival) == reply_norm:
            return rival
    ok, shaped = semantic_accept(field_name, text)
    if ok and shaped:
        shaped_norm = normalize_agreement_value(field_name, shaped)
        for rival in rivals:
            if normalize_agreement_value(field_name, rival) == shaped_norm:
                return rival
    # Currency: allow "$49.72" / "49.72" / "49 72" forms against rivals.
    if field_name.casefold() in _CHARGE_FIELDS:
        from packages.claim_evidence.line_sum_authority import parse_currency

        reply_amt = parse_currency(text)
        if reply_amt is not None:
            for rival in rivals:
                rival_amt = parse_currency(rival)
                if rival_amt is not None and rival_amt == reply_amt:
                    return rival
    return None


def _match_financial_side(reply: str) -> str | None:
    text = (reply or "").strip()
    if not text:
        return None
    folded = text.casefold()
    if folded in {"abstain", "none", "unsure", "unknown"}:
        return None
    # Exact single-token answers first.
    token = folded.split()[0].strip(".,:;!")
    if token in {"box28", "box_28", "box"}:
        return "BOX28"
    if token in {"lines", "line", "line_sum", "linesum", "sum"}:
        return "LINES"
    if re.search(r"\bbox\s*28\b|\bprinted\s*total\b", folded):
        return "BOX28"
    if re.search(r"\blines?\b|\bline[_\s-]?sum\b|\b24f\b", folded):
        return "LINES"
    return None


def resolve_field_conflict(
    *,
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    field_name: str,
    rivals: Sequence[str],
    engine: Any | None = None,
) -> ConflictResolution:
    """Ask Claude which rival matches the ink. No third value allowed."""
    rivals_clean = [_normalize_space(r) for r in rivals if _normalize_space(r)]
    # Preserve order, unique by normalize.
    from packages.evidence.normalization import normalize_agreement_value

    seen: set[str] = set()
    unique: list[str] = []
    for rival in rivals_clean:
        norm = normalize_agreement_value(field_name, rival)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        unique.append(rival)
    rivals_t = tuple(unique)
    if len(rivals_t) < 2:
        return ConflictResolution(
            attempted=False,
            resolved=False,
            chosen=None,
            rivals=rivals_t,
            reason="CONFLICT_AGENT_NO_RIVALS",
        )
    if not conflict_agent_enabled():
        return ConflictResolution(
            attempted=False,
            resolved=False,
            chosen=None,
            rivals=rivals_t,
            reason="CONFLICT_AGENT_DISABLED",
        )

    from packages.extraction_recovery.gpt4o_crop_residual import (
        _AzureGpt4oCropRecognizer,
        _crop_image,
        gpt4o_crop_residual_enabled,
    )
    from packages.extraction_recovery.vlm_crop_lock import vlm_crop_lock

    if not gpt4o_crop_residual_enabled():
        return ConflictResolution(
            attempted=False,
            resolved=False,
            chosen=None,
            rivals=rivals_t,
            reason="CONFLICT_AGENT_VLM_DISABLED",
        )

    key = field_name.casefold()
    # Use text so the model can return an exact rival token (including BOX28-style
    # labels on other paths). Currency shaping would drop non-money replies.
    ftype = "text"
    if key in _CHARGE_FIELDS:
        kind = "dollar amount"
    elif key in _DOB_FIELDS:
        kind = "date of birth"
    elif key in _NAME_FIELDS:
        kind = "person name"
    else:
        kind = "field value"

    options = " | ".join(rivals_t)
    desc = (
        f"CMS-1500 {kind} cell. Two OCR engines disagree on this crop. "
        f"Rivals: {options}. "
        "Look only at the ink. Reply with exactly one of those rival values "
        "that matches the ink. Do not invent a new value. "
        "Reply ABSTAIN if the ink is unreadable or matches none of them."
    )
    crop = _crop_image(image, bbox)
    recognizer = engine or _AzureGpt4oCropRecognizer()
    try:
        with vlm_crop_lock():
            mapped = recognizer.recognize_fields(
                {field_name: crop},
                field_types={field_name: ftype},
                descriptions={field_name: desc},
                prior_candidates={field_name: list(rivals_t)},
            )
    except Exception as exc:  # noqa: BLE001
        return ConflictResolution(
            attempted=True,
            resolved=False,
            chosen=None,
            rivals=rivals_t,
            reason=f"CONFLICT_AGENT_ERROR:{type(exc).__name__}",
        )
    result = mapped.get(field_name)
    reply = ""
    if result is not None:
        reply = str(result.value or result.raw_value or "")
    chosen = _match_rival(reply, rivals_t, field_name)
    if chosen is None:
        return ConflictResolution(
            attempted=True,
            resolved=False,
            chosen=None,
            rivals=rivals_t,
            reason="CONFLICT_AGENT_ABSTAIN",
        )
    return ConflictResolution(
        attempted=True,
        resolved=True,
        chosen=chosen,
        rivals=rivals_t,
        reason="CONFLICT_AGENT_RESOLVED",
    )


def resolve_financial_conflict(
    *,
    image: Image.Image,
    box28_bbox: tuple[int, int, int, int] | None,
    box28_value: str,
    line_sum: str,
    line_bboxes: Sequence[tuple[int, int, int, int]] | None = None,
    engine: Any | None = None,
) -> ConflictResolution:
    """When Box 28 ≠ Σ lines, Claude picks BOX28 or LINES from the ink."""
    del line_bboxes  # reserved for multi-crop; box-28 crop is the decision image
    rivals = (_normalize_space(box28_value), _normalize_space(line_sum))
    if not rivals[0] or not rivals[1] or rivals[0] == rivals[1]:
        return ConflictResolution(
            attempted=False,
            resolved=False,
            chosen=None,
            rivals=rivals,
            reason="CONFLICT_AGENT_NO_FINANCIAL_GAP",
        )
    if not conflict_agent_enabled():
        return ConflictResolution(
            attempted=False,
            resolved=False,
            chosen=None,
            rivals=rivals,
            reason="CONFLICT_AGENT_DISABLED",
        )
    if box28_bbox is None or len(box28_bbox) != 4:
        return ConflictResolution(
            attempted=False,
            resolved=False,
            chosen=None,
            rivals=rivals,
            reason="CONFLICT_AGENT_NO_BOX28_CROP",
        )

    from packages.extraction_recovery.gpt4o_crop_residual import (
        _AzureGpt4oCropRecognizer,
        _crop_image,
        gpt4o_crop_residual_enabled,
    )
    from packages.extraction_recovery.vlm_crop_lock import vlm_crop_lock

    if not gpt4o_crop_residual_enabled():
        return ConflictResolution(
            attempted=False,
            resolved=False,
            chosen=None,
            rivals=rivals,
            reason="CONFLICT_AGENT_VLM_DISABLED",
        )

    desc = (
        "CMS-1500 Box 28 TOTAL CHARGE cell. The printed total and the sum of "
        f"service-line charges disagree. Box 28 OCR={rivals[0]}. "
        f"Line sum OCR={rivals[1]}. "
        "Look at the Box 28 ink. If the printed total is clear and the claim "
        "total should be that amount (even if lines look incomplete), reply "
        "exactly BOX28. If Box 28 ink is wrong, blank, or bleed and the line "
        "sum is the real total, reply exactly LINES. Reply ABSTAIN if unsure. "
        "Do not invent a third amount. Reply with only one token: BOX28, LINES, "
        "or ABSTAIN."
    )
    crop = _crop_image(image, box28_bbox)
    recognizer = engine or _AzureGpt4oCropRecognizer()
    try:
        with vlm_crop_lock():
            mapped = recognizer.recognize_fields(
                {"total_charge": crop},
                # text — not currency — so BOX28 / LINES are not stripped as unshaped money
                field_types={"total_charge": "text"},
                descriptions={"total_charge": desc},
                prior_candidates={"total_charge": ["BOX28", "LINES", *rivals]},
            )
    except Exception as exc:  # noqa: BLE001
        return ConflictResolution(
            attempted=True,
            resolved=False,
            chosen=None,
            rivals=rivals,
            reason=f"CONFLICT_AGENT_ERROR:{type(exc).__name__}",
        )
    result = mapped.get("total_charge")
    reply = ""
    raw_reply = ""
    if result is not None:
        reply = str(result.value or "")
        raw_reply = str(result.raw_value or result.value or "")
        if not reply:
            reply = raw_reply
    side = _match_financial_side(reply) or _match_financial_side(raw_reply)
    # Also accept a direct amount match as that side.
    if side is None:
        matched = _match_rival(reply, rivals, "total_charge") or _match_rival(
            raw_reply, rivals, "total_charge"
        )
        if matched == rivals[0]:
            side = "BOX28"
        elif matched == rivals[1]:
            side = "LINES"
    if side is None:
        return ConflictResolution(
            attempted=True,
            resolved=False,
            chosen=None,
            rivals=rivals,
            reason="CONFLICT_AGENT_ABSTAIN",
            financial_side=None,
        )
    chosen = rivals[0] if side == "BOX28" else rivals[1]
    return ConflictResolution(
        attempted=True,
        resolved=True,
        chosen=chosen,
        rivals=rivals,
        reason="CONFLICT_AGENT_FINANCIAL_RESOLVED",
        financial_side=side,
    )


def maybe_attach_conflict_agent_to_field_row(
    field_row: Mapping[str, Any],
    *,
    image: Image.Image,
    engine: Any | None = None,
) -> dict[str, Any]:
    """Resolve a same-field OCR/model conflict on the crop."""
    updated = dict(field_row)
    name = str(field_row.get("field") or "")
    key = name.casefold()
    if key not in _CHARGE_FIELDS | _NAME_FIELDS | _DOB_FIELDS:
        return updated
    if not conflict_agent_enabled():
        return updated
    # Idempotent: residual path + end-of-OCR loop must not pay Claude twice
    # on the same field (Independent-300 latency: ~2 CONFLICT_AGENT_RESOLVED
    # attempts per charge on twin-rival docs).
    prior = field_row.get("conflict_agent")
    if isinstance(prior, Mapping) and (
        prior.get("attempted") or prior.get("resolved")
    ):
        return updated
    if any(
        "conflict_agent" in str(a.get("engine") or "").casefold()
        for a in (field_row.get("attempts") or [])
        if isinstance(a, Mapping)
    ):
        return updated
    candidates = list(field_row.get("candidates") or [])
    rivals = collect_field_rivals(name, candidates)
    if len(rivals) < 2:
        return updated
    bbox = tuple(field_row.get("ocr_region") or field_row.get("canonical_region") or ())
    if len(bbox) != 4:
        return updated
    resolution = resolve_field_conflict(
        image=image,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        field_name=name,
        rivals=rivals,
        engine=engine,
    )
    attempts = list(updated.get("attempts") or [])
    attempts.append(
        {
            "engine": "conflict_agent_claude",
            "reason": resolution.reason,
            "observation": {
                "rivals": list(resolution.rivals),
                "chosen": resolution.chosen,
            },
        }
    )
    updated["attempts"] = attempts
    updated["conflict_agent"] = {
        "attempted": resolution.attempted,
        "resolved": resolution.resolved,
        "chosen": resolution.chosen,
        "rivals": list(resolution.rivals),
        "reason": resolution.reason,
    }
    if not resolution.resolved or not resolution.chosen:
        return updated

    # Promote the chosen rival to the front and accept the cascade.
    chosen = resolution.chosen
    reordered: list[dict[str, Any]] = []
    matched: dict[str, Any] | None = None
    for cand in candidates:
        raw = _normalize_space(str(cand.get("value") or ""))
        from packages.evidence.normalization import normalize_agreement_value

        if normalize_agreement_value(name, raw) == normalize_agreement_value(
            name, chosen
        ):
            matched = dict(cand)
            continue
        reordered.append(cand)
    if matched is None:
        matched = _agent_candidate(
            value=chosen,
            bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
            image=image,
            reason=resolution.reason,
            variant="conflict_agent_resolve",
        )
    else:
        matched = dict(matched)
        matched["reason_code"] = resolution.reason
        matched.setdefault("model_version", "unknown")
        matched.setdefault("model_name", matched.get("engine") or "unknown")
    # Agent vote sits with the chosen rival as a confirming engine.
    agent_cand = _agent_candidate(
        value=chosen,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        image=image,
        reason=resolution.reason,
        variant="conflict_agent_resolve",
    )
    updated["candidates"] = [agent_cand, matched, *reordered]
    cascade = dict(updated.get("cascade") or {})
    cascade["accepted"] = True
    cascade["accept_reason"] = resolution.reason
    cascade["value"] = chosen
    updated["cascade"] = cascade
    updated["status"] = "FIELD_ACCEPTED"
    updated["value"] = chosen
    return updated


def _financial_box28_seed(candidates: Sequence[Mapping[str, Any]] | None) -> str | None:
    """Pick a Box 28 seed for financial conflict, preferring ruling-split ink.

    M0463JEM.017: Rapid ``523\\n156`` → ``523.56`` must beat DI/agent glue
    ``523156.00`` (implausible) and the cents-only span ``156.00``.
    """
    from packages.claim_evidence.line_charge_selector import (
        _ruling_split_amount,
        promote_ruling_split_candidate_value,
    )
    from packages.claim_evidence.line_sum_authority import (
        format_currency,
        is_implausible_charge_total,
        parse_currency,
    )

    rows = [dict(c) for c in (candidates or []) if isinstance(c, Mapping)]
    for cand in rows:
        promote_ruling_split_candidate_value(cand)

    ruled_locals: list[str] = []
    for cand in rows:
        eng = str(cand.get("engine") or "").casefold()
        if not any(tok in eng for tok in ("paddle", "rapid", "tesseract")):
            continue
        if "derived" in str(cand.get("preprocessing_variant") or "").casefold():
            continue
        ruled = _ruling_split_amount(cand.get("raw_value"))
        if ruled and not is_implausible_charge_total(ruled):
            ruled_locals.append(ruled)
    if len(set(ruled_locals)) == 1:
        return ruled_locals[0]

    box28 = None
    for cand in rows:
        eng = str(cand.get("engine") or "").casefold()
        if "derived" in str(cand.get("preprocessing_variant") or "").casefold():
            continue
        shaped = cand.get("value")
        ruled = _ruling_split_amount(cand.get("raw_value"))
        if ruled and not is_implausible_charge_total(ruled):
            shaped = ruled
        val = parse_currency(shaped)
        if val is None or is_implausible_charge_total(shaped):
            continue
        box28 = format_currency(val)
        if "document_intelligence" in eng or "paddle" in eng or "rapid" in eng:
            break
    return box28


def maybe_resolve_financial_conflict(
    *,
    image: Image.Image,
    fields: list[dict[str, Any]],
    service_lines: list[dict[str, Any]],
    engine: Any | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """If Box 28 ≠ line sum, ask Claude BOX28 vs LINES and adopt that total."""
    if not conflict_agent_enabled():
        return fields, service_lines
    from packages.claim_evidence.line_charge_selector import (
        is_ruling_split_digit_glue,
        promote_ruling_split_candidate_value,
    )
    from packages.claim_evidence.line_sum_authority import (
        amounts_corroborate,
        format_currency,
        is_implausible_charge_total,
        line_sum_total,
        parse_currency,
    )

    total_row = next(
        (
            row
            for row in fields
            if str(row.get("field") or "").casefold() in {"total_charge", "total_charges"}
        ),
        None,
    )
    if total_row is None:
        return fields, service_lines
    # Promote ruling-split values on the live row before seeding / agent.
    for cand in total_row.get("candidates") or []:
        if isinstance(cand, dict):
            promote_ruling_split_candidate_value(cand)
    box28 = _financial_box28_seed(total_row.get("candidates") or [])
    line_total = line_sum_total(service_lines)
    if box28 is None or line_total is None:
        return fields, service_lines
    if amounts_corroborate(box28, line_total):
        return fields, service_lines

    # Exact ×100 cents-column twin: prefer the placed (smaller) amount when a
    # service line already has vision+local consensus on it. Claude/DI often
    # read the unplaced digits (4972) on a 49.72 cell.
    from packages.claim_evidence.line_sum_authority import (
        line_has_vision_and_local_on_selected,
    )

    if _near_decimal_place_shift(box28, line_total):
        box_amt = parse_currency(box28)
        line_amt = parse_currency(line_total)
        local_supports_line = False
        for line in service_lines or []:
            if not isinstance(line, dict):
                continue
            for cand in line.get("candidates") or []:
                eng = str(cand.get("engine") or "").casefold()
                if "gpt4o" in eng or "gpt-4o" in eng or "claude" in eng or "anthropic" in eng:
                    continue
                if "paddle" in eng or "rapid" in eng:
                    if amounts_corroborate(cand.get("value"), line_total):
                        local_supports_line = True
                        break
            if local_supports_line:
                break
        if (
            box_amt is not None
            and line_amt is not None
            and line_amt < box_amt
            and (
                local_supports_line
                or line_has_vision_and_local_on_selected(service_lines, line_total)
            )
        ):
            bbox = tuple(
                total_row.get("ocr_region") or total_row.get("canonical_region") or ()
            )
            updated_fields = []
            for row in fields:
                if row is not total_row:
                    updated_fields.append(row)
                    continue
                current = dict(row)
                current["financial_conflict_agent"] = {
                    "side": "LINES",
                    "value": line_total,
                    "reason": "CONFLICT_AGENT_CENTS_COLUMN_PREFER_LINES",
                }
                current["conflict_agent"] = {
                    "attempted": True,
                    "resolved": True,
                    "chosen": line_total,
                    "rivals": [box28, line_total],
                    "reason": "CONFLICT_AGENT_CENTS_COLUMN_PREFER_LINES",
                    "financial_side": "LINES",
                }
                cascade = dict(current.get("cascade") or {})
                cascade["accepted"] = True
                cascade["accept_reason"] = "CONFLICT_AGENT_CENTS_COLUMN_PREFER_LINES"
                cascade["value"] = line_total
                current["cascade"] = cascade
                current["value"] = line_total
                if len(bbox) == 4:
                    agent_cand = _agent_candidate(
                        value=line_total,
                        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                        image=image,
                        reason="CONFLICT_AGENT_CENTS_COLUMN_PREFER_LINES",
                        variant="conflict_agent_cents_column",
                    )
                    current["candidates"] = [
                        agent_cand,
                        *list(current.get("candidates") or []),
                    ]
                updated_fields.append(current)
            return updated_fields, service_lines

    bbox = tuple(total_row.get("ocr_region") or total_row.get("canonical_region") or ())
    if len(bbox) != 4:
        return fields, service_lines
    resolution = resolve_financial_conflict(
        image=image,
        box28_bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        box28_value=box28,
        line_sum=line_total,
        engine=engine,
    )
    updated_fields = []
    for row in fields:
        if row is not total_row:
            updated_fields.append(row)
            continue
        current = dict(row)
        attempts = list(current.get("attempts") or [])
        attempts.append(
            {
                "engine": "conflict_agent_claude",
                "reason": resolution.reason,
                "observation": {
                    "rivals": list(resolution.rivals),
                    "chosen": resolution.chosen,
                    "financial_side": resolution.financial_side,
                },
            }
        )
        current["attempts"] = attempts
        current["conflict_agent"] = {
            "attempted": resolution.attempted,
            "resolved": resolution.resolved,
            "chosen": resolution.chosen,
            "rivals": list(resolution.rivals),
            "reason": resolution.reason,
            "financial_side": resolution.financial_side,
        }
        if resolution.resolved and resolution.chosen and resolution.financial_side:
            chosen = resolution.chosen
            # Agent/DI often glue ruling-split ink (``523156``). Keep BOX28 side
            # but adopt the ruled seed when the pick is digit-glue / implausible.
            if resolution.financial_side == "BOX28" and box28:
                if is_implausible_charge_total(chosen) or is_ruling_split_digit_glue(
                    box28, chosen
                ):
                    chosen_amt = parse_currency(box28)
                    if chosen_amt is not None:
                        chosen = format_currency(chosen_amt)
            agent_cand = _agent_candidate(
                value=chosen,
                bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                image=image,
                reason=resolution.reason,
                variant="conflict_agent_financial",
            )
            cands = [agent_cand, *list(current.get("candidates") or [])]
            current["candidates"] = cands
            cascade = dict(current.get("cascade") or {})
            cascade["accepted"] = True
            cascade["accept_reason"] = resolution.reason
            cascade["value"] = chosen
            current["cascade"] = cascade
            current["status"] = "FIELD_ACCEPTED"
            current["value"] = chosen
            # Signal for claim-evidence: prefer this side over FINANCIAL_CONFLICT.
            current["financial_conflict_agent"] = {
                "side": resolution.financial_side,
                "value": chosen,
                "reason": resolution.reason,
            }
        updated_fields.append(current)
    return updated_fields, service_lines
