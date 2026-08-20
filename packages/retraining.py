"""Append-only, local correction sink for supervised retraining data."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CorrectionExample:
    document_id: str
    field_name: str
    previous_value: str | None
    corrected_value: str
    crop_reference: str | None
    reviewer: str
    corrected_at: str
    tenant_id: str = "default"
    reason: str | None = None


@dataclass(frozen=True)
class CorrectionPattern:
    field_name: str
    observed: str
    corrected: str
    occurrences: int
    distinct_documents: int
    distinct_reviewers: int
    agreement_ratio: float
    promotion_eligible: bool


class CorrectionSink(Protocol):
    def append(self, example: CorrectionExample) -> None: ...


class JsonlCorrectionSink:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def append(self, example: CorrectionExample) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(example), ensure_ascii=False) + "\n")


def correction_example(
    document_id: str,
    field_name: str,
    previous_value: str | None,
    corrected_value: str,
    crop_reference: str | None,
    reviewer: str,
    tenant_id: str = "default",
    reason: str | None = None,
) -> CorrectionExample:
    return CorrectionExample(
        document_id, field_name, previous_value, corrected_value, crop_reference,
        reviewer, datetime.now(UTC).isoformat(), tenant_id, reason,
    )


class CorrectionMemory:
    """Read bounded, field-scoped exemplars from append-only correction memory."""

    def __init__(self, path: Path, *, limit: int = 3) -> None:
        self._path = path
        self._limit = max(0, limit)

    def exemplars(self, field_name: str, tenant_id: str = "default") -> list[dict[str, str]]:
        if self._limit == 0 or not self._path.is_file():
            return []
        selected: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        lines = self._path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("field_name") != field_name or row.get("tenant_id", "default") != tenant_id:
                continue
            previous = str(row.get("previous_value") or "")
            corrected = str(row.get("corrected_value") or "")
            if not corrected or (previous, corrected) in seen:
                continue
            selected.append({"observed": previous, "corrected": corrected})
            seen.add((previous, corrected))
            if len(selected) >= self._limit:
                break
        return list(reversed(selected))

    def promotion_candidates(
        self,
        tenant_id: str = "default",
        *,
        minimum_documents: int = 5,
        minimum_reviewers: int = 2,
        minimum_agreement: float = 0.95,
    ) -> list[CorrectionPattern]:
        """Identify patterns for holdout testing; this never activates a route."""
        if not self._path.is_file():
            return []
        observations: dict[tuple[str, str], list[dict]] = {}
        for line in self._path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("tenant_id", "default") != tenant_id:
                continue
            field = str(row.get("field_name") or "")
            observed = str(row.get("previous_value") or "")
            corrected = str(row.get("corrected_value") or "")
            if field and corrected:
                observations.setdefault((field, observed), []).append(row)

        candidates: list[CorrectionPattern] = []
        for (field, observed), rows in observations.items():
            corrected_counts: dict[str, int] = {}
            for row in rows:
                corrected = str(row.get("corrected_value") or "")
                corrected_counts[corrected] = corrected_counts.get(corrected, 0) + 1
            corrected, occurrences = max(corrected_counts.items(), key=lambda item: item[1])
            documents = {str(row["document_id"]) for row in rows if row.get("document_id")}
            reviewers = {str(row["reviewer"]) for row in rows if row.get("reviewer")}
            agreement = occurrences / len(rows)
            eligible = (
                len(documents) >= minimum_documents
                and len(reviewers) >= minimum_reviewers
                and agreement >= minimum_agreement
            )
            candidates.append(CorrectionPattern(
                field, observed, corrected, occurrences, len(documents), len(reviewers), agreement, eligible,
            ))
        return sorted(
            candidates,
            key=lambda item: (-int(item.promotion_eligible), -item.occurrences, item.field_name),
        )
