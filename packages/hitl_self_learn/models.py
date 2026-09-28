"""Contracts for HITL self-learn memory (pattern → playbook, never value invent)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# FA-safe remediation kinds. ``code_fix`` is a human/agent engineering task;
# retry kinds strip+requeue via existing cascade / reprocess runners.
REMEDIATION_KINDS = frozenset(
    {
        "retry_decision_only",
        "retry_geometry_ocr",
        "retry_full_cascade",
        "code_fix",
        "keep_hitl",
        "active_learning_queue",
    }
)


@dataclass
class PatternKey:
    gap_class: str
    field_name: str
    reason_fingerprint: str

    def pattern_id(self) -> str:
        raw = f"{self.gap_class}|{self.field_name}|{self.reason_fingerprint}"
        # Stable short id for files / inventories.
        import hashlib

        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class PatternRecord:
    pattern_id: str
    gap_class: str
    field_name: str
    reason_fingerprint: str
    action_catalog: str
    remediation: str
    remediation_detail: str
    hit_count: int = 0
    stp_flip_count: int = 0
    example_claim_ids: list[str] = field(default_factory=list)
    example_evidence: list[str] = field(default_factory=list)
    first_seen_ts: str | None = None
    last_seen_ts: str | None = None
    last_run_id: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "PatternRecord":
        return cls(
            pattern_id=str(row["pattern_id"]),
            gap_class=str(row.get("gap_class") or ""),
            field_name=str(row.get("field_name") or ""),
            reason_fingerprint=str(row.get("reason_fingerprint") or ""),
            action_catalog=str(row.get("action_catalog") or ""),
            remediation=str(row.get("remediation") or "keep_hitl"),
            remediation_detail=str(row.get("remediation_detail") or ""),
            hit_count=int(row.get("hit_count") or 0),
            stp_flip_count=int(row.get("stp_flip_count") or 0),
            example_claim_ids=list(row.get("example_claim_ids") or []),
            example_evidence=list(row.get("example_evidence") or []),
            first_seen_ts=row.get("first_seen_ts"),
            last_seen_ts=row.get("last_seen_ts"),
            last_run_id=row.get("last_run_id"),
            notes=list(row.get("notes") or []),
        )


@dataclass
class MineEvent:
    """One HITL field observation from a ledger row (+ optional DecisionResult)."""

    claim_id: str
    document: str
    field_name: str
    gap_class: str
    evidence: str
    action_catalog: str
    reason_codes: list[str]
    selected_value: str | None
    disposition: str
    ts: str | None
    run_id: str


@dataclass
class RetryPlanItem:
    claim_id: str
    document: str
    pattern_id: str
    gap_class: str
    field_name: str
    remediation: str
    remediation_detail: str
    priority: int
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
