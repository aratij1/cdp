"""Private provenance journal for governed Track B reviews, separate from runtime."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from evaluation.qualification_state import mapped
from packages.real_data_evaluation.blind_workflow import content_digest


def record(
    directory: Path,
    kind: str,
    page: str,
    reviewer: str,
    source_hash: str,
    payload: dict,
    *,
    round_name: str,
    reason: str = "",
) -> None:
    """Append every saved version; source values remain in the private evaluator database."""
    with sqlite3.connect(mapped(directory / "review_provenance.local.sqlite3")) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS journal (kind TEXT, page TEXT, reviewer TEXT, "
            "source_hash TEXT, version INTEGER, round TEXT, timestamp TEXT, "
            "payload TEXT, payload_sha256 TEXT, reason TEXT)"
        )
        db.execute("BEGIN IMMEDIATE")
        version = db.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM journal WHERE kind=? AND page=? AND reviewer=?",
            (kind, page, reviewer),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO journal VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                kind,
                page,
                reviewer,
                source_hash,
                version,
                round_name,
                datetime.now(UTC).isoformat(),
                json.dumps(payload, sort_keys=True),
                content_digest(payload),
                reason,
            ),
        )


def verify(directory: Path, reviews: list[dict], adjudications: list[dict]) -> bool:
    if not reviews:
        return True
    path = mapped(directory / "review_provenance.local.sqlite3")
    if not path.exists():
        return False
    with sqlite3.connect(path) as db:
        for row in reviews:
            if not db.execute(
                "SELECT 1 FROM journal WHERE kind=? AND page=? AND reviewer=? "
                "AND source_hash=? AND payload_sha256=? AND version>0",
                (
                    "REVIEW_COMPLETE",
                    row["page_id"],
                    row["reviewer_id"],
                    row["source_sha256"],
                    content_digest(row["annotation"]),
                ),
            ).fetchone():
                return False
        for row in adjudications:
            if not db.execute(
                "SELECT 1 FROM journal WHERE kind=? AND page=? AND reviewer=? "
                "AND payload_sha256=? AND reason<>?",
                ("ADJUDICATION", row["page_id"], row["adjudicator_id"], content_digest(row), ""),
            ).fetchone():
                return False
    return True
