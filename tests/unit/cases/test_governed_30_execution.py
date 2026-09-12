"""Storage immutability and source/reference isolation for engineering execution."""

from pathlib import Path

import pytest

from evaluation.governed_30_execution import LocalEngineeringObjectStore


def test_local_store_refuses_mutation_and_path_escape(tmp_path: Path):
    store = LocalEngineeringObjectStore(tmp_path)
    ref = store.put_immutable("engineering", "frame", b"synthetic-source")
    assert store.get_bytes(ref) == b"synthetic-source"
    assert store.put_immutable("engineering", "frame", b"synthetic-source") == ref
    with pytest.raises(ValueError, match="IMMUTABLE_OBJECT_CHANGED"):
        store.put_immutable("engineering", "frame", b"changed")
    with pytest.raises(ValueError, match="OBJECT_PATH_ESCAPE"):
        store.put_immutable("engineering", "../../outside", b"x")
    (tmp_path / "engineering/frame").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="OBJECT_HASH_CHANGED"):
        store.get_bytes(ref)


def test_reference_input_rejected_before_ocr(tmp_path, monkeypatch):
    import asyncio
    import json

    from evaluation import governed_30_execution as module
    from evaluation import two_track_isolation

    (tmp_path / "execution_input.local.json").write_text(
        json.dumps(
            {
                "candidate_commit_sha": "test",
                "claims": [{"claim_alias": "test", "reference_value": "FORBIDDEN"}],
            }
        )
    )
    monkeypatch.setattr(
        two_track_isolation,
        "build",
        lambda root: {"status": "PASS", "source_seals_verified": True, "overlap": 0},
    )
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="REFERENCE_DATA_IN_EXECUTION_INPUT"):
        asyncio.run(module.run(tmp_path, tmp_path))


@pytest.mark.parametrize("mutation", ["hash", "source", "duplicate", "seal"])
def test_execution_input_must_match_the_sealed_isolated_cohort(mutation):
    from copy import deepcopy

    from evaluation.governed_30_execution import validate_execution_cohort
    from evaluation.governed_30_reference import seal

    manifest = {"claims": [{"claim_alias": "synthetic", "source_hash": "a" * 64}]}
    manifest["cohort_hash"] = seal(manifest)
    inputs = {
        "cohort_hash": manifest["cohort_hash"],
        "claims": [{"claim_alias": "synthetic", "source_sha256": "a" * 64}],
    }
    validate_execution_cohort(inputs, manifest)
    inputs = deepcopy(inputs)
    if mutation == "hash":
        inputs["cohort_hash"] = "wrong"
    elif mutation == "source":
        inputs["claims"][0]["source_sha256"] = "b" * 64
    elif mutation == "duplicate":
        inputs["claims"].append(inputs["claims"][0])
    else:
        manifest["claims"][0]["source_hash"] = "changed"
    with pytest.raises(ValueError, match="EXECUTION_COHORT"):
        validate_execution_cohort(inputs, manifest)
