"""Lineage evidence must never manufacture claim authority."""

import json
from copy import deepcopy

import pytest

from evaluation.blind_lineage_recovery import recover


def fixture():
    sources = [
        {
            "page_id": f"private-page-{i}",
            "package_id": "private-package",
            "source_asset_path": "root/private-source.tif",
            "frame_index": i,
            "source_asset_sha256": "a" * 64,
            "rendered_page_sha256": str(i) * 64,
        }
        for i in range(2)
    ]
    bindings = [
        {
            "source_page_id": s["page_id"],
            "package_id": s["package_id"],
            "source_asset_sha256": s["source_asset_sha256"],
            "source_page_index": s["frame_index"],
            "state": "EXACT",
            "rendered_page_sha256": s["rendered_page_sha256"],
            "cdp_page_sha256": s["rendered_page_sha256"],
        }
        for s in sources
    ]
    lineage = {
        "assets": [
            {
                "sha256": "a" * 64,
                "bundle_id": "private-package",
                "frame_count": 2,
                "relative_path": "private-source.tif",
            }
        ]
    }
    return sources, bindings, lineage


def test_file_frames_and_package_do_not_create_claims():
    rows, private, report = recover(*fixture())
    assert len(rows) == 2
    assert {r["membership_status"] for r in rows} == {"UNBOUND"}
    assert report["source_container_lineage_recovered_pages"] == 2
    assert report["automatically_recovered_claim_membership_pages"] == 0
    assert rows[0]["frame/page number"] == 1
    assert rows[1]["frame/page number"] == 2
    assert "private-" not in json.dumps(rows)
    assert "private-" not in json.dumps(report)
    assert "private-" in json.dumps(private)
    assert all(r["claim_alias_to_fill"] == r["owner_confirmation"] == "" for r in rows)


@pytest.mark.parametrize(
    "key,value",
    [
        ("state", "UNBOUND"),
        ("source_page_index", 9),
        ("source_asset_sha256", "b" * 64),
        ("package_id", "other"),
        ("cdp_page_sha256", "b" * 64),
    ],
)
def test_binding_mismatch_fails_closed(key, value):
    sources, bindings, lineage = fixture()
    bindings[0][key] = value
    with pytest.raises(ValueError, match="SOURCE_BINDING_SEAL_MISMATCH"):
        recover(sources, bindings, lineage)


def test_duplicate_hash_candidates_do_not_supply_boundary():
    sources, bindings, lineage = fixture()
    lineage["assets"].append(deepcopy(lineage["assets"][0]))
    rows, _, report = recover(sources, bindings, lineage)
    assert report["source_container_lineage_recovered_pages"] == 0
    assert all(r["suggested document boundary if evidenced"] == "" for r in rows)


def test_ungoverned_claim_id_never_becomes_exact():
    sources, bindings, lineage = fixture()
    for b in bindings:
        b["claim_id"] = "not-governed"
    rows, _, report = recover(sources, bindings, lineage)
    assert len(rows) == report["still_unbound_pages"] == 2


def test_duplicate_page_rejected():
    sources, bindings, lineage = fixture()
    sources.append(deepcopy(sources[0]))
    with pytest.raises(ValueError, match="DUPLICATE_PAGE_BINDING"):
        recover(sources, bindings, lineage)


def test_wrong_path_does_not_supply_container_boundary():
    sources, bindings, lineage = fixture()
    lineage["assets"][0]["relative_path"] = "other.tif"
    rows, _, report = recover(sources, bindings, lineage)
    assert report["source_container_lineage_recovered_pages"] == 0
    assert all(r["suggested document boundary if evidenced"] == "" for r in rows)
