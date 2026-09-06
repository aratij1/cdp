"""Reconstruct source/replay lineage from verified bytes; details stay outside Git."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image

from packages.claim_intelligence.document import fingerprint
from packages.real_data_evaluation.source_binding import PageIdentity, bind_pages

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation_results/qualification_closure"


def rendered_hash(image: Image.Image) -> str:
    h = hashlib.sha256(f"{image.mode}|{image.width}|{image.height}|".encode())
    h.update(image.tobytes())
    return h.hexdigest()


def run() -> dict:
    blind_path = ROOT / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    blind_bytes = blind_path.read_bytes()
    blind = json.loads(blind_bytes)
    expected = {p["page_id"]: p["package_id"] for p in blind["pages"]}
    records: dict[str, list[tuple[dict, Path]]] = {}
    for path in (ROOT / "evaluation_data/strict_identity_replay_v3/pages").glob("*.json"):
        row = json.loads(path.read_text())
        key = fingerprint(row["source_page_id"])
        if key in expected:
            records.setdefault(row["source_page_id"], []).append((row, path))
    caches: dict[str, list[tuple[dict, Path]]] = {}
    for path in (ROOT / "evaluation_data/strict_identity_replay_v2/ocr_cache").glob("*.json"):
        row = json.loads(path.read_text())
        if row["source_page_id"] in records:
            caches.setdefault(row["source_page_id"], []).append((row, path))
    sources, processed, source_views, failures = [], [], [], []
    verified_assets = {}
    for page_id, rows in records.items():
        available = caches.get(page_id, [])
        if len(available) != 1:
            failures.append(
                {"page_id": fingerprint(page_id), "reason": "NON_UNIQUE_OR_MISSING_OCR_LINEAGE"}
            )
            continue
        cache, cache_path = available[0]
        asset = Path(cache["source_asset_path"]).resolve()
        source_root = (ROOT / "evaluation_data/source_b_1000_claims").resolve()
        try:
            asset.relative_to(source_root)
            if asset not in verified_assets:
                verified_assets[asset] = hashlib.sha256(asset.read_bytes()).hexdigest()
            if verified_assets[asset] != cache["source_asset_sha256"]:
                raise ValueError("SOURCE_ASSET_CHANGED")
            frame = cache["frame_index"]
            if type(frame) is not int or frame < 0:
                raise ValueError("INVALID_FRAME")
            with Image.open(asset) as source:
                source.seek(frame)
                page_hash = rendered_hash(source)
            if page_hash != cache["rendered_page_sha256"]:
                raise ValueError("RENDERED_HASH_CHANGED")
            package = rows[0][0]["package_id"]
            if fingerprint(package) != expected[fingerprint(page_id)]:
                raise ValueError("BLIND_PACKAGE_MISMATCH")
            proof = (
                "ASSET_BYTES:" + verified_assets[asset],
                "FRAME_PIXELS:" + page_hash,
                "OCR_MANIFEST:" + hashlib.sha256(cache_path.read_bytes()).hexdigest(),
            )
            verified_source = PageIdentity(
                fingerprint(page_id),
                verified_assets[asset],
                frame,
                page_hash,
                fingerprint(package),
                proof,
            )
            verified_processed = []
            for prior, prior_path in rows:
                provenance = prior["ocr_provenance"]
                if (
                    prior["source_page_number"] - 1 != frame
                    or prior["source_page_sha256"] != page_hash
                    or provenance["source_asset_sha256"] != verified_assets[asset]
                    or provenance["rendered_page_sha256"] != page_hash
                    or provenance["frame_index"] != frame
                ):
                    raise ValueError("REPLAY_LINEAGE_CONTRADICTION")
                verified_processed.append(
                    PageIdentity(
                        page_id,
                        verified_assets[asset],
                        frame,
                        page_hash,
                        fingerprint(prior["package_id"]),
                        (
                            "CDP_STRICT_REPLAY:"
                            + hashlib.sha256(prior_path.read_bytes()).hexdigest(),
                        ),
                    )
                )
            sources.append(verified_source)
            processed.extend(verified_processed)
            source_views.append(
                {
                    "page_id": fingerprint(page_id),
                    "package_id": fingerprint(package),
                    "source_asset_path": str(asset),
                    "frame_index": frame,
                    "source_asset_sha256": verified_assets[asset],
                    "rendered_page_sha256": page_hash,
                }
            )
        except (OSError, ValueError, EOFError):
            failures.append(
                {"page_id": fingerprint(page_id), "reason": "SOURCE_OR_LINEAGE_VERIFICATION_FAILED"}
            )
    bindings = bind_pages(tuple(sources), tuple(processed))
    counts = Counter(b.state.value for b in bindings)
    # Pages without sufficient input evidence remain in the original denominator.
    missing = len(expected) - len(bindings)
    summary = {
        "source_page_count": len(expected),
        "bound_page_count": counts["EXACT"],
        "ambiguous_page_count": counts["AMBIGUOUS"],
        "unbound_page_count": counts["UNBOUND"] + missing,
        "binding_coverage": counts["EXACT"] / len(expected),
        "binding_method": "VERIFIED_ASSET_FRAME_RENDERED_HASH_AND_PACKAGE_LINEAGE",
        "cdp_page_namespace": "EXISTING_CDP_STRICT_IDENTITY_REPLAY",
        "production_database_page_binding_claimed": False,
        "claim_bindings_established": 0,
        "claim_boundary_status": "REQUIRES_GOVERNED_COMPLETE_CLAIM_MEMBERSHIP",
        "release_scored_claims": 0,
        "truth_created": False,
        "blind_manifest_sha256": hashlib.sha256(blind_bytes).hexdigest(),
        "status": "EXACT_PAGE_BINDING"
        if counts["EXACT"] == len(expected)
        else "INCOMPLETE_BINDING",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {**summary, "bindings": [b.as_dict() for b in bindings], "failures": failures}
    (OUT / "source_page_bindings.local.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUT / "blind_source_views.local.json").write_text(json.dumps(source_views, indent=2) + "\n")
    (OUT / "source_binding_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if blind_path.read_bytes() != blind_bytes:
        raise ValueError("BLIND_MANIFEST_MUTATED")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    run()
