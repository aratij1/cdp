"""Evaluate discovery without consuming labels or authorizing canonical localization."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

from PIL import Image

from evaluation.cdp2_comparison import write
from evaluation.closure_candidate_probe import known_source_pages
from evaluation.real_archive_classification import PageRef
from evaluation.strict_identity_cached_replay import (
    observation_from_cache,
    valid_legacy_cache_record,
)
from packages.claim_intelligence.discovery import NoncanonicalDiscovery
from packages.claim_intelligence.document import DocumentPage, Token, fingerprint

ROOT = Path(__file__).resolve().parents[1]


def run() -> dict:
    output = ROOT / "evaluation_results/closure"
    manifest = json.loads((output / "noncanonical_discovery_probe.json").read_text())
    allowed = {p["page_id"]: p for p in manifest["manifest"]}
    review = json.loads(
        (ROOT / "evaluation_results/cdp2/active_learning_blind_manifest.json").read_text()
    )
    if {p["package_id"] for p in allowed.values()} & {p["package_id"] for p in review["pages"]}:
        raise ValueError("HUMAN_REVIEW_PACKAGE_LEAKAGE")
    records = {
        r["source_page_id"]: r
        for r in (
            json.loads(p.read_text())
            for p in (ROOT / "evaluation_data/strict_identity_replay_v3/pages").glob("*.json")
        )
        if fingerprint(r["source_page_id"]) in allowed
    }
    extractor = NoncanonicalDiscovery()
    matched = 0
    for field, value, page in known_source_pages():
        result = extractor.extract(
            replace(page, form_type="OTHER_CLAIM_FORM", form_identity_state="NOT_VERIFIED")
        )
        matched += any(c.value == value for c in result.candidates.get(field, []))
    counts: Counter[str] = Counter()
    pages = []
    evidence_hashes = []
    for path in sorted((ROOT / "evaluation_data/strict_identity_replay_v2/ocr_cache").glob("*.json")):
        cache = json.loads(path.read_text())
        if cache["source_page_id"] not in records:
            continue
        prior = records[cache["source_page_id"]]
        if prior["candidate_class"] != "OTHER_CLAIM_FORM":
            raise ValueError("DISCOVERY_COHORT_CHANGED")
        asset = Path(cache["source_asset_path"])
        if hashlib.sha256(asset.read_bytes()).hexdigest() != cache["source_asset_sha256"]:
            raise ValueError("SOURCE_ASSET_HASH_MISMATCH")
        ref = PageRef(
            prior["archive_id"],
            prior["package_id"],
            prior["source_asset_id"],
            prior["source_page_id"],
            prior["source_page_number"],
            prior["source_asset_page_count"],
            prior["source_asset_sequence"],
            asset,
            cache["source_asset_sha256"],
            prior["source_page_sha256"],
        )
        if not valid_legacy_cache_record(cache, ref, cache["ocr_engine_version"]):
            raise ValueError("OCR_CACHE_PROVENANCE_INVALID")
        observation = observation_from_cache(cache)
        with Image.open(cache["source_asset_path"]) as source:
            source.seek(prior["source_page_number"] - 1)
            width, height = source.size
        if fingerprint(prior["package_id"]) != allowed[fingerprint(prior["source_page_id"])]["package_id"]:
            raise ValueError("DISCOVERY_PACKAGE_BINDING_CHANGED")
        cache_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        evidence_hashes.append(cache_hash)
        tokens = tuple(
            Token(
                t.text,
                " ".join(t.text.split()),
                (t.x0, t.y0, t.x1, t.y1),
                t.confidence,
                observation.engine,
                prior["source_page_id"],
                fingerprint((prior["source_page_sha256"], t.x0, t.y0, t.x1, t.y1)),
                cache_hash,
                cache["source_asset_sha256"],
                prior["source_page_sha256"],
            )
            for t in observation.lines
            if 0 <= t.x0 < t.x1 <= width and 0 <= t.y0 < t.y1 <= height
        )
        page = DocumentPage(
            prior["source_page_id"],
            prior["package_id"],
            "OTHER_CLAIM_FORM",
            "NOT_VERIFIED",
            width,
            height,
            "UNKNOWN",
            tokens,
        )
        result = extractor.extract(page)
        fields = {name: len(values) for name, values in result.candidates.items()}
        counts.update(fields)
        pages.append(
            {
                "page_id": fingerprint(page.page_id),
                "package_id": fingerprint(page.package_id),
                "candidate_counts": fields,
                "authority": result.authority,
                "canonical_localization": result.canonical_localization,
            }
        )
    if len(pages) != len(allowed) or {p["page_id"] for p in pages} != set(allowed):
        raise ValueError("DISCOVERY_COHORT_INCOMPLETE_OR_DUPLICATED")
    report = {
        "cohort_sha256": fingerprint(sorted(allowed.items())),
        "evidence_sha256": fingerprint(sorted(evidence_hashes)),
        "pages": len(pages),
        "pages_with_candidates": sum(bool(p["candidate_counts"]) for p in pages),
        "candidate_counts": dict(counts),
        "known_source_recovered": matched,
        "known_source_fields": 24,
        "authority": "UNVERIFIED_DISCOVERY",
        "release_qualified": False,
        "production_authority": False,
        "canonical_localizations": 0,
        "new_ocr_calls": 0,
        "paid_ai_cost": 0,
        "package_leakage": False,
        "results": pages,
    }
    write(output, "noncanonical_candidate_result.json", report)
    return report


if __name__ == "__main__":
    report = run()
    print({k: v for k, v in report.items() if k != "results"})
