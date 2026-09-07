"""Fail closed on cross-cohort identity or pixel overlap; publish counts only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from evaluation.governed_30_reference import seal
from evaluation.reconstruct_source_bindings import rendered_hash
from packages.real_data_evaluation.blind_workflow import content_digest

ROOT = Path(__file__).resolve().parents[1]
DIMENSIONS = (
    "source_assets",
    "packages",
    "known_claim_ids",
    "known_page_ids",
    "rendered_frame_content",
)


def compare(left: dict[str, set[str]], right: dict[str, set[str]]) -> dict:
    dimensions: dict = {
        name: {
            "governed_30_available": len(left.get(name, set())),
            "blind_150_available": len(right.get(name, set())),
            "overlap": len(left.get(name, set()) & right.get(name, set())),
            "comparison": "KNOWN_IDENTIFIERS_ONLY" if name.startswith("known_") else "COMPLETE",
        }
        for name in DIMENSIONS
    }
    overlaps = sum(r["overlap"] for r in dimensions.values())
    return {
        "scope": "TWO_TRACK_COHORT_ISOLATION",
        "status": "FAIL" if overlaps else "PASS",
        "overlap": overlaps,
        "dimensions": dimensions,
        "compare_known_only": True,
        "unknown_claim_membership_is_disjoint_proof": False,
        "pixel_comparison": "RGB_PIXELS_WITH_WIDTH_AND_HEIGHT",
        "issues": [],
    }


def assert_disjoint(report: dict) -> None:
    if report.get("status") != "PASS" or report.get("source_seals_verified") is not True:
        raise ValueError("TWO_TRACK_COHORT_ISOLATION_REQUIRED")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pixels(image: Image.Image) -> str:
    rgb = image.convert("RGB")
    digest = hashlib.sha256(f"RGB|{rgb.width}|{rgb.height}|".encode())
    digest.update(rgb.tobytes())
    return digest.hexdigest()


def _build(root: Path) -> dict:
    private = root / "evaluation_results/qualification_closure"
    member_path = private / "owner_sequence_membership.local.json"
    manifest_path = root / "evaluation_results/real_release/governed_30_manifest.json"
    blind_path = root / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    sources_path = private / "blind_source_views.local.json"
    bindings_path = private / "source_page_bindings.local.json"
    input_hashes = {
        p: _sha(p) for p in (member_path, manifest_path, blind_path, sources_path, bindings_path)
    }
    member, manifest, blind = _read(member_path), _read(manifest_path), _read(blind_path)
    sources, bindings = _read(sources_path), _read(bindings_path)
    if (
        member.get("governed") is not True
        or manifest.get("membership_input_sha256") != input_hashes[member_path]
        or manifest.get("cohort_hash")
        != seal({k: v for k, v in manifest.items() if k != "cohort_hash"})
    ):
        raise ValueError("GOVERNED_COHORT_SEAL_MISMATCH")
    if bindings.get("blind_manifest_sha256") != input_hashes[blind_path]:
        raise ValueError("BLIND_MANIFEST_SEAL_MISMATCH")
    reservation = _read(
        root / "evaluation_results/production_closure/release/package_reservation.local.json"
    )
    freeze = _read(private / "binding_reservation_freeze.local.json")
    if freeze != {
        "bindings_sha256": content_digest(bindings),
        "reservation_sha256": content_digest(reservation),
        "manifest_sha256": input_hashes[blind_path],
    }:
        raise ValueError("BLIND_BINDING_RESERVATION_SEAL_MISMATCH")
    expected = {(r["page_id"], r["package_id"]) for r in blind["pages"]}
    if (
        len(sources) != 150
        or len(expected) != 150
        or expected != {(r["page_id"], r["package_id"]) for r in sources}
    ):
        raise ValueError("BLIND_COHORT_SCOPE_MISMATCH")
    rows = member["mappings"]
    if len(rows) != 30 or len(manifest["claims"]) != 30:
        raise ValueError("GOVERNED_COHORT_SCOPE_MISMATCH")
    left: dict[str, set[str]] = {key: set() for key in DIMENSIONS}
    right: dict[str, set[str]] = {key: set() for key in DIMENSIONS}
    sealed_assets: dict[Path, str] = {}

    def check_asset(path: Path, expected_hash: str):
        if path not in sealed_assets:
            sealed_assets[path] = _sha(path)
        if sealed_assets[path] != expected_hash:
            raise ValueError("COHORT_SOURCE_HASH_MISMATCH")

    governed_frames = 0
    known_governed_claims = set()
    for row in rows:
        if row.get("membership_status") != "EXACT":
            raise ValueError("GOVERNED_EXACT_MEMBERSHIP_REQUIRED")
        path = Path(row["actual_source_path"])
        check_asset(path, row["source_sha256"])
        matches = [
            r
            for r in manifest["claims"]
            if r["source_hash"] == row["source_sha256"]
            and r["package_hash"] == seal(row["package_id"])
        ]
        if len(matches) != 1:
            raise ValueError("GOVERNED_MANIFEST_SOURCE_MISMATCH")
        known_governed_claims.add(matches[0]["claim_alias"])
        with Image.open(path) as img:
            count = getattr(img, "n_frames", 1)
            indices = [p["frame_index"] for p in matches[0]["pages"]]
            if indices != list(range(count)) or row["source_frame_count"] != count:
                raise ValueError("GOVERNED_FRAME_SCOPE_MISMATCH")
            for frame in indices:
                img.seek(frame)
                left["rendered_frame_content"].add(_pixels(img))
                governed_frames += 1
        left["source_assets"].add(row["source_sha256"])
        left["packages"].add(row["package_id"])
        left["known_claim_ids"].add(row["claim_id"])
        if row.get("page_id"):
            left["known_page_ids"].add(row["page_id"])
    if len(known_governed_claims) != 30 or governed_frames != 67:
        raise ValueError("GOVERNED_CLAIM_FRAME_COVERAGE_MISMATCH")
    by_page = {r["source_page_id"]: r for r in bindings["bindings"]}
    if len(by_page) != len(bindings["bindings"]) or set(by_page) != {r["page_id"] for r in sources}:
        raise ValueError("BLIND_BINDING_PAGE_SCOPE_MISMATCH")
    for row in sources:
        path = Path(row["source_asset_path"])
        check_asset(path, row["source_asset_sha256"])
        b = by_page[row["page_id"]]
        if (
            b.get("state") != "EXACT"
            or b.get("package_id") != row["package_id"]
            or b.get("source_asset_sha256") != row["source_asset_sha256"]
            or b.get("source_page_index") != row["frame_index"]
            or b.get("rendered_page_sha256") != row["rendered_page_sha256"]
            or b.get("cdp_page_sha256") != row["rendered_page_sha256"]
        ):
            raise ValueError("BLIND_EXACT_SOURCE_BINDING_REQUIRED")
        with Image.open(path) as img:
            img.seek(row["frame_index"])
            if rendered_hash(img) != row["rendered_page_sha256"]:
                raise ValueError("BLIND_RENDERED_SOURCE_SEAL_MISMATCH")
            right["rendered_frame_content"].add(_pixels(img))
        right["source_assets"].add(row["source_asset_sha256"])
        right["packages"].add(row["package_id"])
        right["known_page_ids"].add(row["page_id"])
        if b.get("claim_id"):
            right["known_claim_ids"].add(b["claim_id"])
    if any(_sha(p) != h for p, h in input_hashes.items()):
        raise ValueError("COHORT_INPUT_CHANGED_DURING_ISOLATION")
    result = compare(left, right)
    result.update(
        source_seals_verified=True,
        governed_frames_checked=governed_frames,
        blind_frames_checked=len(sources),
        governed_claim_aliases_checked=len(known_governed_claims),
        governed_cohort_hash=manifest["cohort_hash"],
        blind_manifest_sha256=input_hashes[blind_path],
        blind_pages_with_known_claim_id=sum(bool(b.get("claim_id")) for b in bindings["bindings"]),
    )
    if result["overlap"]:
        result["issues"].append("CROSS_COHORT_OVERLAP_DETECTED")
    return result


def build(root: Path = ROOT) -> dict:
    from evaluation.real_release import publish

    try:
        result = _build(root)
    except (OSError, ValueError, KeyError, TypeError, EOFError) as error:
        reason = (
            str(error)
            if isinstance(error, ValueError) and str(error).isupper()
            else "COHORT_INPUT_UNVERIFIABLE"
        )
        result = {
            "scope": "TWO_TRACK_COHORT_ISOLATION",
            "status": "FAIL",
            "overlap": None,
            "source_seals_verified": False,
            "issues": [reason],
        }
    publish(root / "evaluation_results/real_release/cohort_isolation.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
