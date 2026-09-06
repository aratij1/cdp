"""Immutable prediction snapshots kept separate from source-only human review."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def freeze_predictions(
    path: Path,
    *,
    cohort: dict[str, str],
    predictions: list[dict],
    configuration_sha256: str,
    source_sha256: dict[str, str],
) -> dict:
    """Persist actual supplied outputs only; never invent missing predictions.

    ``cohort`` maps page ID to package ID. The host must supply an evaluator-only
    path outside Git and the human-review directory. An empty field dictionary
    represents an actual executed no-output result, not an unexecuted page.
    """
    if not cohort or not re.fullmatch(r"[a-f0-9]{64}", configuration_sha256):
        raise ValueError("INVALID_PREDICTION_FREEZE_SCOPE")
    if set(source_sha256) != set(cohort) or any(
        not re.fullmatch(r"[a-f0-9]{64}", value) for value in source_sha256.values()
    ):
        raise ValueError("SOURCE_BINDINGS_INCOMPLETE")
    seen = set()
    for row in predictions:
        if set(row) != {"page_id", "package_id", "fields", "execution_status"}:
            raise ValueError("INVALID_PREDICTION_ROW")
        page = row["page_id"]
        if page in seen or page not in cohort or cohort[page] != row["package_id"]:
            raise ValueError("PREDICTION_COHORT_MISMATCH")
        if row["execution_status"] != "EXECUTED" or not isinstance(row["fields"], dict):
            raise ValueError("UNEXECUTED_PREDICTION")
        seen.add(page)
    if seen != set(cohort):
        raise ValueError("INCOMPLETE_PREDICTION_COHORT")
    payload = {
        "schema_version": "prediction-freeze-v1",
        "configuration_sha256": configuration_sha256,
        "cohort": cohort,
        "source_sha256": source_sha256,
        "predictions": sorted(predictions, key=lambda r: r["page_id"]),
        "authority": "PREDICTIONS_NOT_TRUTH",
        "reviewer_visible": False,
    }
    data = (
        json.dumps(payload, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n"
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("FROZEN_PREDICTIONS_CHANGED") from None
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "pages": len(cohort),
        "status": "PREDICTIONS_FROZEN_NOT_TRUTH",
        "reviewer_visible": False,
    }
