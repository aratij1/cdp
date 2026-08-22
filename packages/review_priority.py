from __future__ import annotations

from datetime import datetime

from packages.domain.review import ReviewTask


_CRITICALITY = {"C0": 0, "C1": 1, "C2": 2, "C3": 3}


def review_priority_key(
    task: ReviewTask,
    *,
    criticality: str,
    now: datetime,
) -> tuple:
    """SLA, value/impact, criticality, single-blocker, then oldest-first."""
    sla = task.sla_due_at or datetime.max.replace(tzinfo=now.tzinfo)
    value = task.claim_value_usd or 0
    return (
        sla,
        -value,
        -_CRITICALITY.get(criticality, 0),
        -int(task.single_blocker_claim),
        task.created_at,
    )
