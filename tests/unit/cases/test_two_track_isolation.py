"""Source seals and rendered content prevent cross-cohort contamination."""

import hashlib
import json

import pytest
from PIL import Image

from evaluation.governed_30_reference import seal
from evaluation.reconstruct_source_bindings import rendered_hash
from evaluation.two_track_isolation import DIMENSIONS, assert_disjoint, build, compare
from packages.real_data_evaluation.blind_workflow import content_digest


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_any_known_overlap_fails(dimension):
    report = compare({dimension: {"shared"}}, {dimension: {"shared"}})
    assert report["status"] == "FAIL"
    assert report["dimensions"][dimension]["overlap"] == 1
    with pytest.raises(ValueError, match="TWO_TRACK_COHORT_ISOLATION_REQUIRED"):
        assert_disjoint(report)


def test_unknown_claims_are_never_claim_disjointness_proof():
    report = compare({"known_claim_ids": {"governed"}}, {"known_claim_ids": set()})
    assert report["dimensions"]["known_claim_ids"]["blind_150_available"] == 0
    assert report["unknown_claim_membership_is_disjoint_proof"] is False
    with pytest.raises(ValueError):
        assert_disjoint(report)


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def cohorts(tmp_path):
    private = tmp_path / "evaluation_results/qualification_closure"
    private.mkdir(parents=True)
    assets = tmp_path / "assets"
    assets.mkdir()
    mappings, claims = [], []
    offset = 0
    for i in range(30):
        count = 3 if i < 7 else 2
        pages = [Image.new("RGB", (3, 3), (offset + j, 0, 0)) for j in range(count)]
        offset += count
        path = assets / f"a{i}.tif"
        pages[0].save(path, save_all=True, append_images=pages[1:])
        mappings.append(
            {
                "membership_status": "EXACT",
                "actual_source_path": str(path),
                "source_sha256": sha(path),
                "source_frame_count": count,
                "package_id": "a-package",
                "claim_id": f"a-claim{i}",
                "page_id": f"a-page{i}",
            }
        )
        claims.append(
            {
                "source_hash": sha(path),
                "package_hash": seal("a-package"),
                "claim_alias": f"a{i}",
                "pages": [{"frame_index": j, "page_alias": f"a{i}-{j}"} for j in range(count)],
            }
        )
    member_path = private / "owner_sequence_membership.local.json"
    write(member_path, {"governed": True, "mappings": mappings})
    manifest = {"claims": claims, "membership_input_sha256": sha(member_path)}
    manifest["cohort_hash"] = seal(manifest)
    write(tmp_path / "evaluation_results/real_release/governed_30_manifest.json", manifest)
    sources, binding_rows = [], []
    for i in range(150):
        image = Image.new("RGB", (3, 3), (i + 67, 0, 0))
        path = assets / f"b{i}.tif"
        image.save(path)
        source = {
            "page_id": f"b-page{i}",
            "package_id": "b-package",
            "source_asset_path": str(path),
            "source_asset_sha256": sha(path),
            "frame_index": 0,
            "rendered_page_sha256": rendered_hash(image),
        }
        sources.append(source)
        binding_rows.append(
            {
                "source_page_id": source["page_id"],
                "package_id": "b-package",
                "state": "EXACT",
                "source_asset_sha256": sha(path),
                "source_page_index": 0,
                "rendered_page_sha256": rendered_hash(image),
                "cdp_page_sha256": rendered_hash(image),
            }
        )
    blind = {"pages": [{"page_id": s["page_id"], "package_id": s["package_id"]} for s in sources]}
    blind_path = tmp_path / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    write(blind_path, blind)
    bindings = {"blind_manifest_sha256": sha(blind_path), "bindings": binding_rows}
    write(private / "source_page_bindings.local.json", bindings)
    write(private / "blind_source_views.local.json", sources)
    reservation = {"assignments": {"b-package": "HOLDOUT"}}
    write(
        tmp_path / "evaluation_results/production_closure/release/package_reservation.local.json",
        reservation,
    )
    write(
        private / "binding_reservation_freeze.local.json",
        {
            "bindings_sha256": content_digest(bindings),
            "reservation_sha256": content_digest(reservation),
            "manifest_sha256": sha(blind_path),
        },
    )
    return tmp_path


def test_complete_sealed_source_and_pixel_isolation(cohorts):
    report = build(cohorts)
    assert report["status"] == "PASS"
    assert_disjoint(report)
    assert report["governed_frames_checked"] == 67
    assert report["blind_frames_checked"] == 150
    assert str(cohorts) not in json.dumps(report)


def test_source_byte_tampering_fails_closed(cohorts):
    with (cohorts / "assets/b0.tif").open("ab") as stream:
        stream.write(b"changed")
    report = build(cohorts)
    assert report["status"] == "FAIL"
    assert report["issues"] == ["COHORT_SOURCE_HASH_MISMATCH"]


def test_manifest_tampering_fails_closed(cohorts):
    path = cohorts / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    path.write_text(path.read_text() + " ")
    assert build(cohorts)["issues"] == ["BLIND_MANIFEST_SEAL_MISMATCH"]


def test_missing_inputs_fail_closed_without_private_path(tmp_path):
    report = build(tmp_path)
    assert report["status"] == "FAIL"
    assert str(tmp_path) not in json.dumps(report)


def test_same_rendered_frame_in_different_tiff_container_fails(cohorts):
    # A0 is a three-frame TIFF. B0 is a different single-frame TIFF containing
    # the same first rendered page, so source-file hashes alone cannot catch it.
    path = cohorts / "assets/b0.tif"
    Image.new("L", (3, 3), 0).save(path)
    with Image.open(path) as img:
        page_hash = rendered_hash(img)
    private = cohorts / "evaluation_results/qualification_closure"
    sources_path = private / "blind_source_views.local.json"
    sources = json.loads(sources_path.read_text())
    sources[0]["source_asset_sha256"] = sha(path)
    sources[0]["rendered_page_sha256"] = page_hash
    write(sources_path, sources)
    bindings_path = private / "source_page_bindings.local.json"
    bindings = json.loads(bindings_path.read_text())
    bindings["bindings"][0].update(
        source_asset_sha256=sha(path), rendered_page_sha256=page_hash, cdp_page_sha256=page_hash
    )
    write(bindings_path, bindings)
    freeze_path = private / "binding_reservation_freeze.local.json"
    freeze = json.loads(freeze_path.read_text())
    freeze["bindings_sha256"] = content_digest(bindings)
    write(freeze_path, freeze)
    report = build(cohorts)
    assert report["source_seals_verified"] is True
    assert report["dimensions"]["source_assets"]["overlap"] == 0
    assert report["dimensions"]["rendered_frame_content"]["overlap"] == 1
    assert report["status"] == "FAIL"
