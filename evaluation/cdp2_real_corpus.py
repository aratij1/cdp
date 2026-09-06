"""Unlabeled operational replay and blind-review selection, separate from claims."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from packages.claim_intelligence.document import DocumentPage, Token, fingerprint
from packages.claim_intelligence.spatial import SpatialCandidateExtractor
from packages.claim_intelligence.telemetry import OCRInvocationLedger, PerformanceProfile


def select_review(records: list[dict], excluded_packages: set[str], limit: int = 150) -> dict:
    remaining = [r for r in records if r["package_id"] not in excluded_packages]
    selected: list[dict] = []
    packages: Counter[str] = Counter()
    forms: Counter[str] = Counter()
    while remaining and len(selected) < limit:
        chosen = min(
            remaining,
            key=lambda r: (
                packages[r["package_id"]],
                forms[r.get("candidate_class", "UNKNOWN")],
                float(r.get("classification_confidence", 0)),
                r["source_page_id"],
            ),
        )
        remaining.remove(chosen)
        selected.append(chosen)
        packages[chosen["package_id"]] += 1
        forms[chosen.get("candidate_class", "UNKNOWN")] += 1
    view = [
        {"page_id": fingerprint(r["source_page_id"]), "package_id": fingerprint(r["package_id"])}
        for r in selected
    ]
    return {
        "target_pages": limit,
        "selected_pages": len(view),
        "human_review_view": view,
        "selection_metadata": [
            {
                **v,
                "form_candidate": r.get("candidate_class", "UNKNOWN"),
                "quality_band": "UNKNOWN",
                "critical_blockers": None,
                "technical_unlock_distance": None,
                "candidate_ambiguity": None,
                "selection_reasons": ["PACKAGE_DIVERSITY", "FORM_DIVERSITY", "ROUTING_UNCERTAINTY"],
            }
            for v, r in zip(view, selected, strict=True)
        ],
        "excluded_package_ids": sorted(fingerprint(p) for p in excluded_packages),
        "cohort_sha256": fingerprint(view),
        "creates_labels": False,
        "package_leakage_with_operational_replay": False,
        "limitation": "No real claim linkage, field ambiguity, or governed quality bands available",
    }


def real_corpus(root: Path, output: Path, limit: int) -> dict[str, Any]:
    from evaluation.cdp2_comparison import latency_summary, write
    from evaluation.real_archive_classification import PageRef
    from evaluation.strict_identity_cached_replay import (
        _canaries,
        _load_page,
        _page_result,
        decision_policy_manifest,
        observation_from_cache,
        valid_legacy_cache_record,
    )
    from packages.document_routing import MultiSignalRouter

    if limit <= 0:
        raise ValueError("OPERATIONAL_SAMPLE_REQUIRED")
    records = [
        json.loads(p.read_text("utf-8"))
        for p in sorted((root / "evaluation_data/strict_identity_replay_v3/pages").glob("*.json"))
    ]
    assets = [p for p in (root / "evaluation_data/source_b_1000_claims").rglob("*") if p.is_file()]
    actual_pages = 0
    packages = set()
    for asset in assets:
        with Image.open(asset) as source:
            actual_pages += source.n_frames
            packages.add(fingerprint(str(source.tag_v2.get(45016, "")).strip() or asset.stem))
    inventory = {
        "assets": len(assets),
        "pages": actual_pages,
        "packages": len(packages),
        "cached_page_records": len(records),
        "authority": "UNLABELED",
    }
    if len(records) != actual_pages:
        raise ValueError("REAL_PAGE_INVENTORY_MISMATCH")
    ordered = sorted(
        records,
        key=lambda r: (not r["production_chain"]["localization_authorized"], r["source_page_id"]),
    )
    reserved: set[str] = set()
    for r in ordered:
        if len(reserved) < max(1, len(packages) // 5):
            reserved.add(r["package_id"])
    selected = [r for r in ordered if r["package_id"] in reserved][:limit]
    selected_packages = {r["package_id"] for r in selected}
    review = select_review(records, selected_packages)
    review["operator_only"] = True
    review["reviewer_artifact"] = "active_learning_blind_manifest.json"
    write(output, "active_learning_manifest.json", review)
    write(
        output,
        "active_learning_blind_manifest.json",
        {
            "pages": review["human_review_view"],
            "cohort_sha256": review["cohort_sha256"],
            "creates_labels": False,
        },
    )
    lookup = {r["source_page_id"]: r for r in selected}
    frozen = {}
    cache_paths = {}
    for path in sorted(
        (root / "evaluation_data/strict_identity_replay_v2/ocr_cache").glob("*.json")
    ):
        raw = path.read_bytes()
        record = json.loads(raw)
        key = record["source_page_id"]
        if key in lookup:
            if key in frozen:
                raise ValueError("DUPLICATE_OCR_CACHE")
            frozen[key] = hashlib.sha256(raw).hexdigest()
            cache_paths[key] = path
    if set(frozen) != set(lookup):
        raise ValueError("SELECTED_CACHE_MISSING")
    write(
        output,
        "operational_manifest.json",
        {
            "page_ids": sorted(fingerprint(k) for k in lookup),
            "package_ids": sorted(fingerprint(k) for k in selected_packages),
            "evidence_sha256": fingerprint({fingerprint(k): v for k, v in frozen.items()}),
            "authority": "UNLABELED_OPERATIONAL",
            "claim_comparison_cohort": False,
        },
    )
    router, spatial = MultiSignalRouter.load(), SpatialCandidateExtractor()
    policy = decision_policy_manifest()
    profiles, ledgers = [], []
    candidate_counts: Counter[str] = Counter()
    other = unknown = canonical_localizations = 0
    asset_hashes = {}
    for key in sorted(lookup):
        raw = cache_paths[key].read_bytes()
        if hashlib.sha256(raw).hexdigest() != frozen[key]:
            raise ValueError("OCR_EVIDENCE_CHANGED_AFTER_FREEZE")
        cache, prior = json.loads(raw), lookup[key]
        asset_path = Path(cache["source_asset_path"])
        if asset_path not in asset_hashes:
            asset_hashes[asset_path] = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        if asset_hashes[asset_path] != cache["source_asset_sha256"]:
            raise ValueError("SOURCE_ASSET_HASH_MISMATCH")
        ref = PageRef(
            prior["archive_id"],
            prior["package_id"],
            prior["source_asset_id"],
            key,
            prior["source_page_number"],
            prior["source_asset_page_count"],
            prior["source_asset_sequence"],
            asset_path,
            cache["source_asset_sha256"],
            prior["source_page_sha256"],
        )
        profile, ledger = PerformanceProfile(), OCRInvocationLedger()
        with profile.measure("decode_ms"):
            image = _load_page(ref)
        observation = ledger.use_validated_cache(
            frozen[key],
            observation_from_cache(cache),
            provenance_valid=valid_legacy_cache_record(cache, ref, cache["ocr_engine_version"]),
        )
        with profile.measure("form_identity_ms"):
            result = _page_result(
                ref, image, observation, router, cache["ocr_engine_version"], "CACHE_HIT", policy
            )
        chain = result["production_chain"]
        canonical_localizations += bool(chain["actual_localization_invoked"])
        other += (
            result["candidate_class"] == "OTHER_CLAIM_FORM" and chain["localization_authorized"]
        )
        unknown += (
            result["candidate_class"] in {"UNKNOWN", "SUPPORTING_DOCUMENT"}
            and chain["localization_authorized"]
        )
        with profile.measure("candidate_assembly_ms"):
            tokens = []
            for line in observation.lines:
                box = (line.x0, line.y0, line.x1, line.y1)
                # Invalid token geometry is not clipped into a plausible observation.
                if not (
                    0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height
                ):
                    continue
                tokens.append(
                    Token(
                        line.text,
                        " ".join(line.text.split()),
                        box,
                        line.confidence,
                        observation.engine,
                        key,
                        fingerprint((ref.page_sha256, box)),
                        frozen[key],
                        ref.asset_sha256,
                        ref.page_sha256,
                    )
                )
            page = DocumentPage(
                key,
                ref.package_id,
                chain.get("verified_identity_family") or "UNKNOWN",
                chain.get("verification_status") or "NOT_VERIFIED",
                image.width,
                image.height,
                "UNKNOWN",
                tuple(tokens),
            )
        with profile.measure("spatial_reasoning_ms"):
            generated = spatial.extract(page)
            candidate_counts.update({name: len(values) for name, values in generated.items()})
        with profile.measure("serialization_ms"):
            fingerprint(page.diagnostics())
        profiles.append(profile.diagnostics())
        ledgers.append(ledger.diagnostics())
        image.close()
    canaries = _canaries(router)
    safety = {
        "OTHER_canonical_localization": other,
        "UNKNOWN_canonical_localization": unknown,
        "false_UB04_canaries_passed": sum(c["ub04_rejected"] for c in canaries),
        "runtime_authority": False,
        "actual_canonical_localizations": canonical_localizations,
    }
    safety["passed"] = (
        other == unknown == canonical_localizations == 0
        and safety["false_UB04_canaries_passed"] == 3
    )
    page_latency = latency_summary([p["total_ms"] for p in profiles])
    page_latency["throughput_pages_per_second"] = page_latency.pop("throughput_claims_per_second")
    return {
        "inventory": inventory,
        "safety": safety,
        "profile": {
            "scope": "REAL_CACHED_ROUTING_AND_SPATIAL_EXTRACTION",
            "pages": len(profiles),
            "profiles": profiles,
            "latency_per_page": page_latency,
            "candidate_counts": dict(candidate_counts),
            "fresh_ocr_target_status": "NOT_MEASURED",
        },
        "ledger": {k: sum(p[k] for p in ledgers) for k in ledgers[0]} if ledgers else {},
    }
