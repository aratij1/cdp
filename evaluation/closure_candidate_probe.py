"""Bounded known-source and unlabeled real-page candidate-generation probes."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image

from evaluation.cdp2_comparison import write
from evaluation.closure_fresh_perception import selected_pages
from evaluation.strict_identity_cached_replay import observation_from_cache
from packages.claim_intelligence.document import DocumentPage, Token, fingerprint
from packages.claim_intelligence.spatial import SpatialCandidateExtractor

ROOT = Path(__file__).resolve().parents[1]


def known_source_pages():
    cases = [
        ("CMS1500", "member_id", "1a. INSURED'S ID NUMBER", "EXAMPLE123"),
        ("CMS1500", "patient_name", "2. PATIENT'S NAME (Last, First, Middle)", "EXAMPLE PERSON"),
        ("CMS1500", "patient_dob", "3. PATIENT'S BIRTH DATE", "01/02/1980"),
        ("CMS1500", "insured_name", "4. INSURED'S NAME", "EXAMPLE SUBSCRIBER"),
        ("CMS1500", "provider_name", "33. BILLING PROVIDER", "EXAMPLE CLINIC"),
        ("CMS1500", "service_date", "24. DATE(S) OF SERVICE", "01/02/2024"),
        ("CMS1500", "total_charge", "28. TOTAL CHARGE", "123.45"),
        ("UB04", "principal_diagnosis", "67. PRINCIPAL DIAGNOSIS", "A12.3"),
    ]
    for family, field, label, value in cases:
        for index, (scale, dx, dy) in enumerate(((1, 0, 0), (1.5, 80, 40), (0.8, 30, 60))):
            key = f"synthetic-{field}-{index}"

            def token(text, box, scale=scale, dx=dx, dy=dy, key=key):
                transformed = tuple(
                    v * scale + (dx if i % 2 == 0 else dy) for i, v in enumerate(box)
                )
                return Token(
                    text,
                    text,
                    transformed,
                    0.99,
                    "KNOWN_SOURCE",
                    key,
                    fingerprint(box),
                    key,
                    key,
                    key,
                )

            tokens = (token(label, (100, 100, 450, 112)), token(value, (100, 130, 230, 144)))
            page = DocumentPage(
                key,
                key,
                family,
                "VERIFIED",
                int(1000 * scale),
                int(1000 * scale),
                "KNOWN_SOURCE",
                tokens,
                0.99,
            )
            yield field, value, page


def probe() -> dict:
    extractor = SpatialCandidateExtractor()
    matched: Counter[str] = Counter()
    measured: Counter[str] = Counter()
    count: Counter[str] = Counter()
    for field, value, page in known_source_pages():
        alternatives = extractor.extract(page).get(field, [])
        measured[field] += 1
        matched[field] += any(c.value == value for c in alternatives[:5])
        count[field] += len(alternatives)
    real = []
    for item in selected_pages(2):
        prior, cache = item["prior"], item["cache"]
        observation = observation_from_cache(cache)
        with Image.open(cache["source_asset_path"]) as source:
            source.seek(prior["source_page_number"] - 1)
            width, height = source.size
        tokens = tuple(
            Token(
                t.text,
                " ".join(t.text.split()),
                (t.x0, t.y0, t.x1, t.y1),
                t.confidence,
                observation.engine,
                prior["source_page_id"],
                fingerprint((t.x0, t.y0, t.x1, t.y1)),
                "cache",
                cache["source_asset_sha256"],
                prior["source_page_sha256"],
            )
            for t in observation.lines
        )
        chain = prior["production_chain"]
        page = DocumentPage(
            prior["source_page_id"],
            prior["package_id"],
            chain.get("verified_identity_family") or "UNKNOWN",
            chain.get("verification_status") or "NOT_VERIFIED",
            width,
            height,
            "UNKNOWN",
            tokens,
        )
        candidates = extractor.extract(page)
        real.append(
            {
                "page_id": fingerprint(page.page_id),
                "authority": "UNLABELED",
                "counts": {k: len(v) for k, v in candidates.items()},
                "valid": {
                    k: sum(c.features.format_valid is True for c in v)
                    for k, v in candidates.items()
                },
                "accuracy": None,
            }
        )
    return {
        "known_source": {
            "authority": "SYNTHETIC_KNOWN_SOURCE",
            "fields": dict(measured),
            "matched_at_5": dict(matched),
            "candidate_counts": dict(count),
        },
        "real": real,
        "release_qualified": False,
    }


if __name__ == "__main__":
    result = probe()
    write(ROOT / "evaluation_results/closure", "candidate_probe.json", result)
    print(result)
