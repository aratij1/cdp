"""Persistent HITL pattern memory (JSONL + index). Pattern → playbook only."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import MineEvent, PatternKey, PatternRecord, REMEDIATION_KINDS
from .playbook import lookup_playbook, reason_fingerprint


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    """Append-friendly JSONL store under ``root/patterns.jsonl``."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.patterns_path = self.root / "patterns.jsonl"
        self.index_path = self.root / "index.json"
        self._lock = threading.Lock()
        self._by_id: dict[str, PatternRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.patterns_path.exists():
            return
        for line in self.patterns_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec = PatternRecord.from_dict(row)
            self._by_id[rec.pattern_id] = rec

    def get(self, pattern_id: str) -> PatternRecord | None:
        return self._by_id.get(pattern_id)

    def all_patterns(self) -> list[PatternRecord]:
        return sorted(
            self._by_id.values(),
            key=lambda r: (-r.hit_count, r.gap_class, r.field_name),
        )

    def upsert_from_event(self, event: MineEvent) -> PatternRecord:
        """Observe one HITL field event; bump hit_count; never invent values."""
        fp = reason_fingerprint(event.reason_codes)
        key = PatternKey(
            gap_class=event.gap_class,
            field_name=event.field_name,
            reason_fingerprint=fp,
        )
        pid = key.pattern_id()
        play = lookup_playbook(event.gap_class, reason_fp=fp)
        rem = play.remediation if play.remediation in REMEDIATION_KINDS else "keep_hitl"
        with self._lock:
            existing = self._by_id.get(pid)
            now = event.ts or _utc_now()
            if existing is None:
                rec = PatternRecord(
                    pattern_id=pid,
                    gap_class=event.gap_class,
                    field_name=event.field_name,
                    reason_fingerprint=fp,
                    action_catalog=event.action_catalog or play.remediation_detail,
                    remediation=rem,
                    remediation_detail=play.remediation_detail,
                    hit_count=1,
                    example_claim_ids=[event.claim_id],
                    example_evidence=[event.evidence[:240]] if event.evidence else [],
                    first_seen_ts=now,
                    last_seen_ts=now,
                    last_run_id=event.run_id,
                )
            else:
                rec = existing
                rec.hit_count += 1
                rec.last_seen_ts = now
                rec.last_run_id = event.run_id
                if event.claim_id not in rec.example_claim_ids:
                    rec.example_claim_ids = (rec.example_claim_ids + [event.claim_id])[-20:]
                if event.evidence and event.evidence[:240] not in rec.example_evidence:
                    rec.example_evidence = (rec.example_evidence + [event.evidence[:240]])[-10:]
                # Keep playbook fresh if gap taxonomy evolved.
                rec.remediation = rem
                rec.remediation_detail = play.remediation_detail
                if event.action_catalog:
                    rec.action_catalog = event.action_catalog
            self._by_id[pid] = rec
            self._rewrite()
            return rec

    def record_stp_flip(self, pattern_id: str, claim_id: str) -> None:
        """Credit a pattern when a retry flips HITL → TRUE_STP (FA-gated externally)."""
        with self._lock:
            rec = self._by_id.get(pattern_id)
            if rec is None:
                return
            rec.stp_flip_count += 1
            note = f"stp_flip:{claim_id}:{_utc_now()}"
            rec.notes = (rec.notes + [note])[-50:]
            self._rewrite()

    def _rewrite(self) -> None:
        rows = [r.to_dict() for r in self.all_patterns()]
        tmp = self.patterns_path.with_suffix(".jsonl.tmp")
        tmp.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        tmp.replace(self.patterns_path)
        index = {
            "updated_ts": _utc_now(),
            "pattern_count": len(rows),
            "total_hits": sum(r["hit_count"] for r in rows),
            "by_gap_class": {},
            "by_remediation": {},
        }
        for r in rows:
            index["by_gap_class"][r["gap_class"]] = (
                index["by_gap_class"].get(r["gap_class"], 0) + r["hit_count"]
            )
            index["by_remediation"][r["remediation"]] = (
                index["by_remediation"].get(r["remediation"], 0) + r["hit_count"]
            )
        self.index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


# Alias used by package __init__
HitlLearnMemory = MemoryStore


def apply_events(store: MemoryStore, events: Iterable[MineEvent]) -> list[PatternRecord]:
    return [store.upsert_from_event(ev) for ev in events]
