from __future__ import annotations

import pytest

from evaluation.production_release_readiness import (
    audit_responses,
    reserve_packages,
    validate_blind,
)


def manifest():
    return {
        "cohort_sha256": "a" * 64,
        "creates_labels": False,
        "pages": [{"page_id": f"page-{i}", "package_id": f"package-{i // 3}"} for i in range(150)],
    }


def response():
    return {
        "reviewer_id": "Reviewer A",
        "page_id": "page-0",
        "package_id": "package-0",
        "source_sha256": "b" * 64,
        "fields": [
            {
                "field_name": "test_field",
                "visibility": "READABLE",
                "observed_value": "synthetic-test",
            }
        ],
    }


def test_empty_intake_never_creates_truth():
    result = audit_responses(manifest(), [], {})
    assert result["release_truth_created"] == 0
    assert result["status"] == "AWAITING_INDEPENDENT_REVIEW"


@pytest.mark.parametrize(
    "key", ["prediction", "confidence", "candidate_ranking", "canonical_value", "llm_result"]
)
def test_response_prediction_contamination_rejected(key):
    raw = response()
    raw[key] = "forbidden"
    result = audit_responses(manifest(), [raw], {"page-0": "b" * 64})
    assert result["rejected_responses"] == 1


def test_bound_response_not_release_truth():
    result = audit_responses(manifest(), [response()], {"page-0": "b" * 64})
    assert result["structurally_valid_bound_responses"] == 1
    assert result["release_truth_created"] == 0


def test_self_asserted_hash_is_not_source_binding():
    assert audit_responses(manifest(), [response()], {})["rejected_responses"] == 1


def test_normalized_duplicate_reviewer_is_not_independent():
    other = response()
    other["reviewer_id"] = " reviewer   a "
    result = audit_responses(manifest(), [response(), other], {"page-0": "b" * 64})
    assert result["rejection_reasons"]["DUPLICATE_REVIEWER_PAGE_RESPONSE"] == 1


def test_package_reservation_is_immutable_and_not_truth_freeze(tmp_path):
    path = tmp_path / "reservation.json"
    result = reserve_packages(manifest(), path)
    assert result == reserve_packages(manifest(), path)
    assert result["qualification_holdout_frozen"] is False
    assert result["truth_manifest_sha256"] is None
    assert set(result["assignments"].values()) == {"DEVELOPMENT", "HOLDOUT"}
    changed = manifest()
    changed["pages"][0]["package_id"] = "foreign"
    with pytest.raises(ValueError, match="IMMUTABLE"):
        reserve_packages(changed, path)


def test_blind_manifest_forbids_predictions():
    raw = manifest()
    raw["pages"][0]["prediction"] = "forbidden"
    with pytest.raises(ValueError):
        validate_blind(raw)


def test_unreadable_value_cannot_be_fabricated():
    raw = response()
    raw["fields"][0]["visibility"] = "UNREADABLE"
    assert audit_responses(manifest(), [raw], {"page-0": "b" * 64})["rejected_responses"] == 1


def test_unknown_package_rejected():
    raw = response()
    raw["package_id"] = "foreign"
    assert audit_responses(manifest(), [raw], {"page-0": "b" * 64})["rejected_responses"] == 1


def test_latency_development_packages_cannot_overlap_blind_review():
    from evaluation.production_release_readiness import assert_benchmark_disjoint
    from packages.claim_intelligence.document import fingerprint

    raw = manifest()
    with pytest.raises(ValueError, match="PACKAGE_LEAKAGE"):
        assert_benchmark_disjoint(raw, {fingerprint(raw["pages"][0]["package_id"])})
    assert_benchmark_disjoint(raw, {fingerprint("separate-latency-package")})
