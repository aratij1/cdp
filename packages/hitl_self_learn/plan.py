"""Build FA-safe retry plans from mined events + pattern memory."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .memory import MemoryStore
from .models import MineEvent, RetryPlanItem
from .playbook import lookup_playbook, reason_fingerprint


def plan_retries(
    events: list[MineEvent],
    store: MemoryStore | None = None,
    *,
    include_keep_hitl: bool = False,
    include_active_learning: bool = True,
) -> list[RetryPlanItem]:
    """One plan item per claim (worst/highest-priority field pattern)."""
    by_claim: dict[str, list[MineEvent]] = defaultdict(list)
    for ev in events:
        by_claim[ev.claim_id].append(ev)

    items: list[RetryPlanItem] = []
    for claim_id, claim_events in by_claim.items():
        best: RetryPlanItem | None = None
        for ev in claim_events:
            fp = reason_fingerprint(ev.reason_codes)
            pid = None
            rem = None
            detail = None
            priority = 50
            if store is not None:
                # Resolve via upserted memory if present.
                from .models import PatternKey

                key = PatternKey(ev.gap_class, ev.field_name, fp)
                pid = key.pattern_id()
                rec = store.get(pid)
                if rec is not None:
                    rem = rec.remediation
                    detail = rec.remediation_detail
                    play = lookup_playbook(ev.gap_class, reason_fp=fp)
                    priority = play.priority
            if rem is None:
                play = lookup_playbook(ev.gap_class, reason_fp=fp)
                rem = play.remediation
                detail = play.remediation_detail
                priority = play.priority
                from .models import PatternKey

                pid = PatternKey(ev.gap_class, ev.field_name, fp).pattern_id()

            if rem == "keep_hitl" and not include_keep_hitl:
                continue
            if rem == "active_learning_queue" and not include_active_learning:
                continue

            item = RetryPlanItem(
                claim_id=claim_id,
                document=ev.document,
                pattern_id=pid or "",
                gap_class=ev.gap_class,
                field_name=ev.field_name,
                remediation=rem,
                remediation_detail=detail or "",
                priority=priority,
                evidence=ev.evidence,
            )
            if best is None or item.priority < best.priority:
                best = item
        if best is not None:
            items.append(best)

    items.sort(key=lambda x: (x.priority, x.gap_class, x.claim_id))
    return items


def write_plan(
    items: list[RetryPlanItem],
    out_dir: Path | str,
    *,
    meta: dict[str, Any] | None = None,
) -> dict[str, Path]:
    """Write plan.jsonl, inventories by remediation, and summary.json."""
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    plan_path = root / "plan.jsonl"
    plan_path.write_text(
        "".join(json.dumps(i.to_dict(), sort_keys=True) + "\n" for i in items),
        encoding="utf-8",
    )

    by_rem: dict[str, list[RetryPlanItem]] = defaultdict(list)
    for item in items:
        by_rem[item.remediation].append(item)

    inv_dir = root / "inventories"
    inv_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {"plan": plan_path}
    for rem, group in by_rem.items():
        docs = sorted({g.document for g in group if g.document})
        inv = inv_dir / f"{rem}.txt"
        inv.write_text("".join(d + "\n" for d in docs), encoding="utf-8")
        paths[f"inventory_{rem}"] = inv

    summary = {
        "item_count": len(items),
        "claim_count": len({i.claim_id for i in items}),
        "by_remediation": {k: len(v) for k, v in sorted(by_rem.items())},
        "by_gap_class": {},
        **(meta or {}),
    }
    from collections import Counter

    summary["by_gap_class"] = dict(Counter(i.gap_class for i in items).most_common())
    summary_path = root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    paths["summary"] = summary_path
    return paths
