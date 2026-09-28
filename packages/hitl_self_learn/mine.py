"""Mine HITL residuals from a cascade run ledger into MineEvents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from packages.extraction_recovery.gap_taxonomy import classify_field_gap

from .models import MineEvent
from .playbook import reason_fingerprint

_HITL_DISPS = frozenset(
    {
        "HITL",
        "HUMAN_REVIEW_REQUIRED",
        "ESCALATE",
        "FIELD_REVIEW_REQUIRED",
        "CLAIM_REVIEW_REQUIRED",
        "REVIEW_REQUIRED",
    }
)
_CRITICAL_FIELDS = (
    "insured_id_number",
    "patient_name",
    "patient_dob",
    "insured_name",
    "total_charge",
)


def _as_reasons(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw if x]
    return []


def _field_needs_review(field: dict[str, Any]) -> bool:
    disp = str(field.get("disp") or field.get("disposition") or "").upper()
    if disp in _HITL_DISPS:
        return True
    if disp and disp not in {"AUTO_ACCEPTED", "ACCEPTED", "TRUE_STP"}:
        # Unknown non-accept dispositions still count.
        if "ACCEPT" not in disp:
            return True
    return False


def _load_decision(run_dir: Path, claim_id: str) -> dict[str, Any]:
    path = run_dir / "claims" / claim_id / "final" / "DecisionResult.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _events_from_row(
    row: dict[str, Any],
    *,
    run_id: str,
    run_dir: Path | None,
) -> list[MineEvent]:
    disposition = str(row.get("disposition") or "").upper()
    if disposition not in _HITL_DISPS and not row.get("review_required"):
        return []
    if row.get("true_stp"):
        return []

    claim_id = str(row.get("claim_id") or "")
    document = str(row.get("document") or claim_id)
    ts = row.get("ts")
    fields = row.get("fields") or {}
    service_lines = int(row.get("service_line_charges") or 0)
    events: list[MineEvent] = []

    # Prefer ledger gap_classes when cascade summarized them.
    for gap in row.get("gap_classes") or []:
        if not isinstance(gap, dict):
            continue
        fname = str(gap.get("field") or gap.get("field_name") or "")
        fval = fields.get(fname) if isinstance(fields.get(fname), dict) else {}
        events.append(
            MineEvent(
                claim_id=claim_id,
                document=document,
                field_name=fname or "_unknown",
                gap_class=str(gap.get("gap_class") or "HANDWRITING_UNREADABLE"),
                evidence=str(gap.get("evidence") or ""),
                action_catalog=str(gap.get("action") or ""),
                reason_codes=_as_reasons(fval.get("reasons") if fval else None),
                selected_value=str(fval.get("value")) if fval and fval.get("value") is not None else None,
                disposition=disposition or "HITL",
                ts=str(ts) if ts else None,
                run_id=run_id,
            )
        )
    if events:
        return events

    # Else classify non-accepted critical fields.
    blockers: list[str] = list(row.get("critical_blockers") or [])
    if not blockers and run_dir is not None:
        decision = _load_decision(run_dir, claim_id)
        blockers = list(decision.get("critical_blockers") or [])

    review_fields: list[str] = []
    for fname, fval in fields.items():
        if isinstance(fval, dict) and _field_needs_review(fval):
            review_fields.append(str(fname))
    for b in blockers:
        if b not in review_fields:
            review_fields.append(str(b))

    for fname in review_fields:
        fval = fields.get(fname) if isinstance(fields.get(fname), dict) else {}
        reasons = _as_reasons(fval.get("reasons") if fval else None)
        observed = str(fval.get("value") or "") if fval else ""
        gap = classify_field_gap(
            fname,
            observed_text=observed,
            accepted=False,
            service_line_charges=service_lines,
            reason_codes=reasons,
        )
        if gap is None:
            continue
        events.append(
            MineEvent(
                claim_id=claim_id,
                document=document,
                field_name=gap.field_name,
                gap_class=gap.gap_class,
                evidence=gap.evidence,
                action_catalog=gap.action,
                reason_codes=reasons,
                selected_value=observed or None,
                disposition=disposition or "HITL",
                ts=str(ts) if ts else None,
                run_id=run_id,
            )
        )

    if events:
        return events

    # Claim-level HITL with no field blockers (family / claim gate).
    finance = row.get("document_finance") or {}
    fin_gap = str(finance.get("gap_class") or "") if isinstance(finance, dict) else ""
    fin_reasons = _as_reasons(finance.get("reasons") if isinstance(finance, dict) else None)
    claim_status = str(row.get("claim_status") or "")
    if fin_gap == "WRONG_DOCUMENT_FAMILY" or "UNKNOWN_FAMILY" in "+".join(fin_reasons):
        gap_class = "WRONG_DOCUMENT_FAMILY"
        evidence = f"document_finance gap={fin_gap or 'n/a'} reasons={fin_reasons}"
    else:
        gap_class = "CLAIM_LEVEL_REVIEW"
        evidence = f"claim_status={claim_status or disposition}; no field blockers"
    events.append(
        MineEvent(
            claim_id=claim_id,
            document=document,
            field_name="_claim",
            gap_class=gap_class,
            evidence=evidence,
            action_catalog="Claim-level review; redecide or full cascade.",
            reason_codes=fin_reasons or [claim_status or disposition],
            selected_value=None,
            disposition=disposition or "HITL",
            ts=str(ts) if ts else None,
            run_id=run_id,
        )
    )
    return events


def iter_ledger_rows(ledger: Path) -> Iterable[dict[str, Any]]:
    if not ledger.exists():
        return
    with ledger.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def mine_run(
    run_dir: Path | str,
    *,
    ledger_name: str = "results.jsonl",
    run_id: str | None = None,
) -> list[MineEvent]:
    """Mine all HITL MineEvents from a cascade run directory."""
    root = Path(run_dir)
    ledger = root / ledger_name
    rid = run_id or root.name
    events: list[MineEvent] = []
    for row in iter_ledger_rows(ledger):
        events.extend(_events_from_row(row, run_id=rid, run_dir=root))
    return events


def summarize_events(events: list[MineEvent]) -> dict[str, Any]:
    from collections import Counter

    by_gap = Counter(e.gap_class for e in events)
    by_field = Counter(e.field_name for e in events)
    by_fp = Counter(
        reason_fingerprint(e.reason_codes) for e in events
    )
    return {
        "event_count": len(events),
        "claim_count": len({e.claim_id for e in events}),
        "by_gap_class": dict(by_gap.most_common()),
        "by_field": dict(by_field.most_common()),
        "top_reason_fingerprints": dict(by_fp.most_common(15)),
    }
