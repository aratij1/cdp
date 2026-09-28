"""Map gap_class (+ reason fingerprint) → FA-safe remediation playbook.

Never invent field values. Remediations are retry/strip/code_fix only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybookEntry:
    remediation: str
    remediation_detail: str
    priority: int


# Default playbooks keyed by gap_class. Reason fingerprints may refine later.
_DEFAULTS: dict[str, PlaybookEntry] = {
    "LINE_SUM_UNCORROBORATED": PlaybookEntry(
        remediation="retry_geometry_ocr",
        remediation_detail=(
            "Strip claim; re-OCR with expanded Azure DI charge crop + "
            "line-cell corroboration (SINGLE_LINE / MULTI_LINE gates). "
            "scripts.reprocess_field_hitl_from_geometry"
        ),
        priority=10,
    ),
    "EVIDENCE_PLUMBING_GAP": PlaybookEntry(
        remediation="code_fix",
        remediation_detail=(
            "Authorize missing engine family or attach E3/E6 evidence; "
            "then retry_decision_only. Do not treat as unread ink."
        ),
        priority=5,
    ),
    "EVIDENCE_POLICY_GAP": PlaybookEntry(
        remediation="retry_decision_only",
        remediation_detail=(
            "Re-run rank→complete after policy/authority fixes; "
            "scripts.reprocess_field_hitl_decision_only"
        ),
        priority=20,
    ),
    "CALIBRATION_HITL": PlaybookEntry(
        remediation="retry_decision_only",
        remediation_detail=(
            "Calendar/format-valid held for calibrated confidence — "
            "redecide after local OCR corroboration or DATE_VALID relief."
        ),
        priority=25,
    ),
    "SHORT_PADDED_NEEDS_CORROBORATION": PlaybookEntry(
        remediation="retry_geometry_ocr",
        remediation_detail=(
            "Short zero-padded member id — vision/Claude crop corroboration "
            "(match-only, never invent); dual-engine padded settle allowed."
        ),
        priority=15,
    ),
    "NAME_ENGINE_CONFLICT": PlaybookEntry(
        remediation="retry_geometry_ocr",
        remediation_detail=(
            "gpt-4o/Claude name crop residual to arbitrate local OCR conflict; "
            "HITL if still unresolved."
        ),
        priority=18,
    ),
    "AMBIGUOUS_DIGIT_FRAGMENTS": PlaybookEntry(
        remediation="retry_geometry_ocr",
        remediation_detail="Crop/span repair for DOB digit fragments; HITL if not calendar-unique.",
        priority=22,
    ),
    "EMPTY_FINANCIAL_INK": PlaybookEntry(
        remediation="retry_geometry_ocr",
        remediation_detail=(
            "Expanded box-28 + line-cell empty-finance residual; HITL if still blank."
        ),
        priority=12,
    ),
    "NPI_CONTAMINATED_CHARGE": PlaybookEntry(
        remediation="keep_hitl",
        remediation_detail="Never accept NPI bleed as claim total; keep HITL.",
        priority=90,
    ),
    "HANDWRITING_UNREADABLE": PlaybookEntry(
        remediation="active_learning_queue",
        remediation_detail=(
            "Export crop to handwriting active-learning queue; "
            "no auto-accept. evaluation.export_shadow_active_learning pattern."
        ),
        priority=40,
    ),
    "REGISTRATION_HITL": PlaybookEntry(
        remediation="retry_full_cascade",
        remediation_detail="Registration recovery ladder or full cascade reprocess.",
        priority=8,
    ),
    "CLAIM_LEVEL_REVIEW": PlaybookEntry(
        remediation="retry_decision_only",
        remediation_detail=(
            "Claim-level review with no field blocker — redecide after "
            "document_family / finance plumbing fixes."
        ),
        priority=30,
    ),
    "WRONG_DOCUMENT_FAMILY": PlaybookEntry(
        remediation="retry_full_cascade",
        remediation_detail=(
            "UNKNOWN_FAMILY / no CMS geometry — full cascade with unstructured "
            "DI fallback (CDP_UNSTRUCTURED_REG_AGENT) when authorized."
        ),
        priority=7,
    ),
}


def reason_fingerprint(reason_codes: list[str] | tuple[str, ...] | None) -> str:
    """Stable, value-free fingerprint of decision reason codes."""
    codes: list[str] = []
    for raw in reason_codes or []:
        token = str(raw).strip()
        if not token:
            continue
        # Drop engine-id suffixes that are instance-specific but keep family.
        if token.startswith("CANDIDATE_ENGINE_NOT_AUTHORIZED"):
            token = "CANDIDATE_ENGINE_NOT_AUTHORIZED"
        elif token.startswith("LINE_TOTALS_GATE:"):
            token = token  # gate subtype is the learning signal
        codes.append(token)
    # Prefer discriminative gate / policy tokens over boilerplate.
    boost = (
        "LINE_TOTALS_UNCORROBORATED",
        "LINE_TOTALS_GATE:",
        "SHORT_PADDED",
        "UNSHAPED_MEMBER_ID",
        "CALIBRATED_CONFIDENCE",
        "CONFLICT_MARGIN",
        "CANDIDATE_ENGINE_NOT_AUTHORIZED",
        "MISSING_E",
        "CHARGE_VISION",
        "CHARGE_DI",
        "WRONG_DOCUMENT",
        "UNKNOWN_FAMILY",
    )
    discriminative = [
        c
        for c in codes
        if any(b in c for b in boost)
    ]
    chosen = discriminative or codes
    # Cap length for stable keys.
    chosen = sorted(set(chosen))[:8]
    return "+".join(chosen) if chosen else "NO_REASON"


def lookup_playbook(
    gap_class: str,
    *,
    reason_fp: str = "",
) -> PlaybookEntry:
    """Return remediation for a gap; reason_fp may refine LINE_SUM subtypes."""
    gap = (gap_class or "").strip() or "HANDWRITING_UNREADABLE"
    entry = _DEFAULTS.get(gap) or PlaybookEntry(
        remediation="keep_hitl",
        remediation_detail=f"No playbook for {gap}; keep HITL.",
        priority=50,
    )
    # Refine LINE_SUM single-line place-shift: often needs DI scale fix (code).
    if gap == "LINE_SUM_UNCORROBORATED" and "SINGLE_LINE" in (reason_fp or ""):
        return PlaybookEntry(
            remediation="code_fix",
            remediation_detail=(
                "SINGLE_LINE_REQUIRES_DI / place-shift — fix DI×100 scale or "
                "box28 dual-engine corroboration, then retry_geometry_ocr. "
                "Do not auto-accept line sum."
            ),
            priority=6,
        )
    return entry
