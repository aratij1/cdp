"""Durable blind annotation drafts and independent review completion."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from packages.claim_intelligence.normalization import comparison_key
from packages.hitl_reduction.review_coordination import canonical_reviewer_id

FIELDS = (
    "member_id",
    "provider_name",
    "patient_name",
    "insured_name",
    "patient_dob",
    "service_date",
    "total_charge",
    "principal_diagnosis",
)


class FieldAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal[
        "VALUE", "BLANK", "UNREADABLE", "NOT_PRESENT", "SOURCE_CONFLICT", "NOT_APPLICABLE"
    ]
    value: str | None = None
    region: tuple[float, float, float, float]

    @model_validator(mode="after")
    def valid(self):
        if (self.state == "VALUE") != bool(self.value and self.value.strip()):
            raise ValueError("VALUE_STATE_REQUIRES_OBSERVATION")
        if self.state != "VALUE" and self.value is not None:
            raise ValueError("NON_VALUE_STATE_CANNOT_HAVE_VALUE")
        x0, y0, x1, y1 = self.region
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError("INVALID_SOURCE_REGION")
        return self


class PageAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, FieldAnnotation]
    form: Literal["CMS1500", "UB04", "OTHER_CLAIM_FORM", "SUPPORTING_DOCUMENT", "UNKNOWN"]
    quality: Literal["GOOD", "DEGRADED", "UNREADABLE", "UNCERTAIN"]
    boundary: Literal["START_CLAIM", "CONTINUATION", "SUPPORTING", "UNCERTAIN"]
    prediction_visible: Literal[False] = False

    @model_validator(mode="after")
    def complete(self):
        if set(self.fields) != set(FIELDS):
            raise ValueError("COMPLETE_FIXED_FIELD_SEQUENCE_REQUIRED")
        return self


class BlindReviewStore:
    """Evaluator-only SQLite persistence; never put this database in Git."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reviews (page TEXT, reviewer TEXT, source_hash TEXT, payload TEXT, completed INTEGER, updated TEXT, PRIMARY KEY(page, reviewer))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS adjudications (page TEXT, field TEXT, reviewer TEXT, review_digest TEXT, payload TEXT, updated TEXT, PRIMARY KEY(page,field))"
            )

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def save(
        self, page: str, reviewer: str, source_hash: str, payload: dict, *, complete: bool
    ) -> None:
        reviewer = canonical_reviewer_id(reviewer)
        if not reviewer or not page or len(source_hash) != 64:
            raise ValueError("REVIEW_SCOPE_REQUIRED")
        if complete:
            payload = PageAnnotation.model_validate(payload).model_dump(mode="json")
        elif set(payload) - {"fields", "form", "quality", "boundary", "prediction_visible"}:
            raise ValueError("DRAFT_CONTAINS_UNSUPPORTED_KEYS")
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
        with self.connect() as db:
            prior = db.execute(
                "SELECT source_hash,payload,completed FROM reviews WHERE page=? AND reviewer=?",
                (page, reviewer),
            ).fetchone()
            if prior and (
                prior[0] != source_hash or prior[2] and (prior[1] != encoded or not complete)
            ):
                raise ValueError("COMPLETED_REVIEW_IMMUTABLE")
            db.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?) ON CONFLICT(page,reviewer) DO UPDATE SET payload=excluded.payload,completed=excluded.completed,updated=excluded.updated",
                (
                    page,
                    reviewer,
                    source_hash,
                    encoded,
                    int(complete),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def own(self, page: str, reviewer: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload,completed FROM reviews WHERE page=? AND reviewer=?",
                (page, canonical_reviewer_id(reviewer)),
            ).fetchone()
        return {"annotation": json.loads(row[0]), "complete": bool(row[1])} if row else None

    def completed(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT page,reviewer,source_hash,payload,updated FROM reviews WHERE completed=1 ORDER BY page,reviewer"
            ).fetchall()
        return [
            {
                "page_id": p,
                "reviewer_id": r,
                "source_sha256": s,
                "annotation": json.loads(a),
                "reviewed_at": t,
            }
            for p, r, s, a, t in rows
        ]

    def adjudicate(
        self, page: str, field: str, reviewer: str, review_digest: str, conclusion: dict
    ) -> None:
        payload = {
            "page_id": page,
            "field_name": field,
            "adjudicator_id": canonical_reviewer_id(reviewer),
            "review_digest": review_digest,
            "conclusion": conclusion,
        }
        encoded = json.dumps(payload, sort_keys=True)
        with self.connect() as db:
            previous = db.execute(
                "SELECT payload FROM adjudications WHERE page=? AND field=?", (page, field)
            ).fetchone()
            if previous and previous[0] != encoded:
                raise ValueError("ADJUDICATION_IMMUTABLE")
            db.execute(
                "INSERT OR IGNORE INTO adjudications VALUES(?,?,?,?,?,?)",
                (
                    page,
                    field,
                    canonical_reviewer_id(reviewer),
                    review_digest,
                    encoded,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def adjudications(self) -> list[dict]:
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM adjudications ORDER BY page,field"
                ).fetchall()
            ]


def review_progress(
    rows: list[dict], expected: dict[str, str], authorized_reviewers: frozenset[str]
) -> dict:
    registry = {canonical_reviewer_id(r) for r in authorized_reviewers}
    by_page: dict[str, list[dict]] = {}
    for row in rows:
        if (
            row["page_id"] in expected
            and row["source_sha256"] == expected[row["page_id"]]
            and canonical_reviewer_id(row["reviewer_id"]) in registry
        ):
            by_page.setdefault(row["page_id"], []).append(row)
    dual = agreements = disagreements = 0
    for group in by_page.values():
        valid = [r for r in group if canonical_reviewer_id(r["reviewer_id"]) in registry]
        if len({canonical_reviewer_id(r["reviewer_id"]) for r in valid}) < 2:
            continue
        for name in FIELDS:
            conclusions = {
                (
                    r["annotation"]["fields"][name]["state"],
                    comparison_key(name, r["annotation"]["fields"][name]["value"])
                    if r["annotation"]["fields"][name]["state"] == "VALUE"
                    else None,
                )
                for r in valid
            }
            dual += 1
            agreements += len(conclusions) == 1
            disagreements += len(conclusions) != 1
    reviewer_pages = {
        reviewer: {
            page
            for page, group in by_page.items()
            if any(canonical_reviewer_id(r["reviewer_id"]) == reviewer for r in group)
        }
        for reviewer in registry
    }
    remaining_actions = sum(
        max(0, 2 - len({canonical_reviewer_id(r["reviewer_id"]) for r in by_page.get(page, [])}))
        for page in expected
    )
    return {
        "reviewer_completion": {
            content_digest(reviewer): {
                "completed_pages": len(pages),
                "cohort_pages": len(expected),
                "completion_rate": len(pages) / len(expected) if expected else None,
            }
            for reviewer, pages in sorted(reviewer_pages.items())
        },
        "remaining_independent_page_reviews": remaining_actions,
        "estimated_remaining_review_minutes": None,
        "review_effort_status": "OBSERVED_REVIEW_DURATION_REQUIRED",
        "completion_rate_scope": "COHORT_COVERAGE; no reviewer assignment or elapsed-time estimate inferred",
        "pages_total": len(expected),
        "pages_reviewed": len(by_page),
        "pages_remaining": len(expected) - len(by_page),
        "fields_reviewed": sum(
            len(set().union(*(set(r["annotation"]["fields"]) for r in g))) for g in by_page.values()
        ),
        "review_observations": sum(
            len(r["annotation"]["fields"]) for g in by_page.values() for r in g
        ),
        "critical_fields_reviewed": sum(
            len(set().union(*(set(r["annotation"]["fields"]) & set(FIELDS) for r in g)))
            for g in by_page.values()
        ),
        "trusted_claims": 0,
        "critical_fields_dual_reviewed": dual,
        "agreements": agreements,
        "disagreements": disagreements,
        "adjudications": 0,
        "trusted_labels": 0,
        "reviewer_registry_configured": bool(registry),
        "truth_status": "PENDING_GOVERNED_FINALIZATION",
    }


def content_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
