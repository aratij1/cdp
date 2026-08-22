"""Idempotently promote benchmark review fields into the operational HITL queue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID, uuid5

from apps.human_review_api.consumer import TASK_NAMESPACE
from apps.human_review_api.db.repository import ReviewTaskRepository
from apps.human_review_api.db.session import make_session_factory
from packages.domain.review import ReviewTask
from packages.settings import get_settings

BENCHMARK_NAMESPACE = UUID("3942e225-e21d-48f5-9241-2c5bccbc58c1")


def import_tasks(predictions: list[dict], session_factory) -> dict[str, int]:
    created = 0
    existing = 0
    with session_factory() as session:
        repository = ReviewTaskRepository(session)
        for row in predictions:
            if not row.get("review_required"):
                continue
            identity = row.get("field_identity") or {}
            source_document_id = str(identity.get("document_id"))
            page_number = int(identity.get("page_number") or 1)
            family = str(identity.get("document_family") or "unknown")
            field_name = str(identity.get("semantic_field") or "unknown")
            document_id = uuid5(BENCHMARK_NAMESPACE, f"document:{source_document_id}")
            claim_id = uuid5(BENCHMARK_NAMESPACE, f"claim:{source_document_id}")
            field_id = uuid5(
                BENCHMARK_NAMESPACE,
                f"field:{source_document_id}:{page_number}:{family}:{field_name}",
            )
            task_id = uuid5(TASK_NAMESPACE, f"{document_id}:{field_id}")
            if repository.get(task_id) is not None:
                existing += 1
                continue
            selected = row.get("selected_value")
            provenance_reason = str((row.get("provenance") or {}).get("reason") or "")
            disposition = str((row.get("hitl_optimization") or {}).get("disposition") or "")
            repository.add(
                ReviewTask(
                    task_id=task_id,
                    claim_id=claim_id,
                    document_id=document_id,
                    field_id=field_id,
                    field_name=field_name,
                    page_number=page_number,
                    ocr_candidates=[] if selected is None else [str(selected)],
                    validation_errors=[
                        value
                        for value in (
                            "BENCHMARK_COHORT_PROMOTED_TO_PRODUCTION",
                            provenance_reason,
                            disposition,
                        )
                        if value
                    ],
                )
            )
            created += 1
        session.commit()
    return {"created": created, "existing": existing, "open_cohort_fields": created + existing}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.predictions.read_text(encoding="utf-8"))
    result = import_tasks(rows, make_session_factory(get_settings().database_url))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
