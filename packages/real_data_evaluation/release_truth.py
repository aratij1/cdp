"""Finalize independently collected blind reviews; never ingest predictions as labels."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from packages.hitl_reduction.review_coordination import canonical_reviewer_id
from packages.real_data_evaluation.blind_workflow import FIELDS, PageAnnotation, content_digest


def finalize_reviews(
    rows: list[dict], sources: dict[str, dict], registry: dict, adjudications: Sequence[dict] = ()
) -> dict:
    authorized = {canonical_reviewer_id(r) for r in registry.get("authorized_reviewers", [])}
    adjudicators = {canonical_reviewer_id(r) for r in registry.get("adjudicators", [])}
    if (
        registry.get("identity_verified") is not True
        or not registry.get("policy_id")
        or not authorized
    ):
        return {
            "status": "NOT_FROZEN",
            "reason": "GOVERNED_REVIEWER_REGISTRY_REQUIRED",
            "records": [],
        }
    grouped: dict[str, list[dict]] = {}
    seen = set()
    for row in rows:
        page = row["page_id"]
        reviewer = canonical_reviewer_id(row["reviewer_id"])
        if page not in sources or reviewer not in authorized:
            continue
        key = (page, reviewer)
        if key in seen:
            raise ValueError("DUPLICATE_INDEPENDENT_REVIEWER")
        seen.add(key)
        if row["source_sha256"] != sources[page]["rendered_page_sha256"]:
            raise ValueError("REVIEW_SOURCE_HASH_MISMATCH")
        PageAnnotation.model_validate(row["annotation"])
        grouped.setdefault(page, []).append(row)
    decisions = {(r["page_id"], r["field_name"]): r for r in adjudications}
    if len(decisions) != len(adjudications):
        raise ValueError("DUPLICATE_ADJUDICATION")
    truth = []
    pending = []
    for page, source in sorted(sources.items()):
        reviews = grouped.get(page, [])
        if len(reviews) < 2:
            pending.append({"page_id": page, "reason": "INDEPENDENT_SECOND_REVIEW_REQUIRED"})
            continue
        metadata = {
            tuple(r["annotation"][k] for k in ("form", "quality", "boundary")) for r in reviews
        }
        resolved_metadata = {
            k: reviews[0]["annotation"][k] for k in ("form", "quality", "boundary")
        }
        metadata_digest = None
        if len(metadata) != 1:
            metadata_decision = decisions.get((page, "__metadata__"), {})
            if (
                canonical_reviewer_id(metadata_decision.get("adjudicator_id", ""))
                not in adjudicators
                or canonical_reviewer_id(metadata_decision.get("adjudicator_id", ""))
                in {canonical_reviewer_id(r["reviewer_id"]) for r in reviews}
                or metadata_decision.get("review_digest") != content_digest(reviews)
            ):
                pending.append({"page_id": page, "reason": "PAGE_METADATA_DISAGREEMENT"})
                continue
            if set(metadata_decision["conclusion"]) != {"form", "quality", "boundary"}:
                raise ValueError("INVALID_METADATA_ADJUDICATION")
            resolved_metadata = metadata_decision["conclusion"]
            PageAnnotation.model_validate({**reviews[0]["annotation"], **resolved_metadata})
            metadata_digest = content_digest(metadata_decision)
        for field in FIELDS:
            observations = [r["annotation"]["fields"][field] for r in reviews]
            conclusions = {(o["state"], o["value"]) for o in observations}
            authority = "DUAL_REVIEW_AGREED"
            conclusion = observations[0]
            if len(conclusions) != 1:
                decision = decisions.get((page, field), {})
                if (
                    canonical_reviewer_id(decision.get("adjudicator_id", "")) not in adjudicators
                    or canonical_reviewer_id(decision.get("adjudicator_id", ""))
                    in {canonical_reviewer_id(r["reviewer_id"]) for r in reviews}
                    or decision.get("review_digest") != content_digest(reviews)
                ):
                    pending.append(
                        {
                            "page_id": page,
                            "field_name": field,
                            "reason": "INDEPENDENT_ADJUDICATION_REQUIRED",
                        }
                    )
                    continue
                from packages.real_data_evaluation.blind_workflow import FieldAnnotation

                conclusion = FieldAnnotation.model_validate(decision["conclusion"]).model_dump(
                    mode="json"
                )
                authority = "ADJUDICATED"
            truth.append(
                {
                    "page_id": page,
                    "package_id": source["package_id"],
                    "field_name": field,
                    "critical": True,
                    "state": conclusion["state"],
                    "value": conclusion["value"],
                    "source_sha256": source["rendered_page_sha256"],
                    "authority": authority,
                    "reviewer_ids": sorted(
                        canonical_reviewer_id(r["reviewer_id"]) for r in reviews
                    ),
                    "review_digest": content_digest(reviews),
                    "adjudication_digest": content_digest(decisions[(page, field)])
                    if authority == "ADJUDICATED"
                    else None,
                    "source_regions": [o["region"] for o in observations],
                    "adjudicated_region": conclusion["region"]
                    if authority == "ADJUDICATED"
                    else None,
                    "page_metadata": resolved_metadata,
                    "metadata_adjudication_digest": metadata_digest,
                }
            )
    ready = bool(sources) and not pending and len(truth) == len(sources) * len(FIELDS)
    payload = {
        "status": "FROZEN" if ready else "NOT_FROZEN",
        "records": truth if ready else [],
        "pending": pending,
        "registry_sha256": content_digest(registry),
        "authority": "INDEPENDENT_BLIND_REVIEW",
        "truth_created_from_predictions": False,
    }
    if ready:
        payload["truth_sha256"] = content_digest(payload)
    return payload


def freeze_truth(path: Path, payload: dict) -> None:
    if payload.get("status") != "FROZEN" or not payload.get("records"):
        raise ValueError("INCOMPLETE_TRUTH_CANNOT_FREEZE")
    check = {k: v for k, v in payload.items() if k != "truth_sha256"}
    if content_digest(check) != payload.get("truth_sha256"):
        raise ValueError("TRUTH_SEAL_MISMATCH")
    data = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(data)
    except FileExistsError:
        if path.read_text() != data:
            raise ValueError("FROZEN_TRUTH_CHANGED") from None
