import json
from copy import deepcopy

import pytest

from evaluation.claim_inventory import build, build_inventory
from packages.real_data_evaluation.blind_workflow import FIELDS


def fixture():
    bindings = [
        {
            "source_page_id": "private-page",
            "package_id": "private-package",
            "state": "EXACT",
            "rendered_page_sha256": "a" * 64,
            "cdp_page_sha256": "a" * 64,
            "cdp_page_id": "private-cdp",
            "claim_id": None,
        }
    ]
    membership = {
        "governed": True,
        "complete_claim_membership_confirmed": True,
        "boundary_provenance": "private-owner-approval",
        "claims": {
            "private-claim": {
                "package_id": "private-package",
                "page_ids": ["private-page"],
                "claim_form_page_ids": ["private-page"],
                "attachment_page_ids": [],
                "expected_field_keys": [["private-page", f] for f in FIELDS],
                "documents": {
                    "private-document": {
                        "page_ids": ["private-page"],
                        "boundary": "GOVERNED",
                        "boundary_provenance": "private-evidence",
                    }
                },
            }
        },
    }
    return membership, bindings


def test_complete_governed_membership_without_truth_or_predictions():
    membership, bindings = fixture()
    result = build_inventory(membership, bindings)
    assert result["membership_ready"] is True
    assert result["claims_exactly_bound"] == 1
    assert result["claims"][0]["attachments_per_claim"] == 0
    assert "private-" not in json.dumps(result)


@pytest.mark.parametrize(
    "key", ["governed", "complete_claim_membership_confirmed", "boundary_provenance"]
)
def test_governance_required(key):
    membership, bindings = fixture()
    del membership[key]
    assert build_inventory(membership, bindings)["claims_unbound"] == 1


def test_packages_and_adjacency_never_create_claims():
    _, bindings = fixture()
    result = build_inventory({}, bindings)
    assert result["packages"] == 1
    assert result["claims_discovered"] == 0
    assert result["pages_without_exact_claim"] == 1
    assert not result["membership_ready"]


def test_binding_claim_id_only_is_unbound():
    _, bindings = fixture()
    bindings[0]["claim_id"] = "existing-claim"
    result = build_inventory({}, bindings)
    assert result["claims_discovered"] == result["claims_unbound"] == 1


def test_shared_page_and_document_are_ambiguous():
    membership, bindings = fixture()
    membership["claims"]["another"] = deepcopy(membership["claims"]["private-claim"])
    result = build_inventory(membership, bindings)
    assert result["claims_ambiguous"] == 2
    assert not result["membership_ready"]


@pytest.mark.parametrize(
    "change", ["attachments", "boundary", "expected", "hash", "package", "source"]
)
def test_incomplete_or_mismatched_evidence_excluded(change):
    membership, bindings = fixture()
    claim = membership["claims"]["private-claim"]
    if change == "attachments":
        del claim["attachment_page_ids"]
    elif change == "boundary":
        claim["documents"]["private-document"]["boundary"] = "UNKNOWN"
    elif change == "expected":
        claim["expected_field_keys"].pop()
    elif change == "hash":
        bindings[0]["cdp_page_sha256"] = "b" * 64
    elif change == "package":
        bindings[0]["package_id"] = "other"
    else:
        bindings.clear()
    assert build_inventory(membership, bindings)["claims_exactly_bound"] == 0


def write_inputs(root, membership=None):
    private = root / "evaluation_results/qualification_closure"
    private.mkdir(parents=True)
    member, bindings = fixture()
    (private / "source_page_bindings.local.json").write_text(json.dumps({"bindings": bindings}))
    if membership is not None:
        (private / "claim_membership.local.json").write_text(json.dumps(membership))
    return private, member


def test_build_materializes_explicit_governed_source(tmp_path):
    private, member = write_inputs(tmp_path)
    (private / "package_manifest.local.json").write_text(json.dumps(member))
    assert build(tmp_path)["membership_ready"]
    assert json.loads((private / "claim_membership.local.json").read_text()) == member
    assert (
        "private-"
        not in (tmp_path / "evaluation_results/real_release/claim_inventory.json").read_text()
    )


def test_conflicts_do_not_materialize(tmp_path):
    private, member = write_inputs(tmp_path)
    (private / "package_manifest.local.json").write_text(json.dumps(member))
    member["boundary_provenance"] = "different"
    (private / "ingestion_lineage.local.json").write_text(json.dumps(member))
    result = build(tmp_path)
    assert result["conflicting_governed_manifests"]
    assert not (private / "claim_membership.local.json").exists()


def test_existing_owner_file_is_never_overwritten(tmp_path):
    private, member = write_inputs(tmp_path, {})
    (private / "package_manifest.local.json").write_text(json.dumps(member))
    assert not build(tmp_path)["membership_ready"]
    assert json.loads((private / "claim_membership.local.json").read_text()) == {}


def test_malformed_metadata_fails_closed():
    member, bindings = fixture()
    member["claims"]["private-claim"]["documents"] = None
    assert not build_inventory(member, bindings)["membership_ready"]


def test_existing_owner_conflicting_manifest_blocks_readiness(tmp_path):
    member, _ = fixture()
    private, source = write_inputs(tmp_path, member)
    source["boundary_provenance"] = "other approval"
    (private / "package_manifest.local.json").write_text(json.dumps(source))
    result = build(tmp_path)
    assert not result["membership_ready"]
    assert result["claims_ambiguous"] == 1
    assert json.loads((private / "claim_membership.local.json").read_text()) == member


def test_invalid_extra_claim_is_not_silently_dropped():
    member, bindings = fixture()
    member["claims"]["invalid"] = None
    assert not build_inventory(member, bindings)["membership_ready"]
