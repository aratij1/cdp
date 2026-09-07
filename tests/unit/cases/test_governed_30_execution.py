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
