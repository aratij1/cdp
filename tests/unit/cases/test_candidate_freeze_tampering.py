"""Exercise real Git reconstruction in isolated repos; never edit the frozen checkout."""
import json
import subprocess

import pytest

from evaluation import candidate_runtime_freeze as freeze


@pytest.mark.parametrize("change,expected", [
    ("runtime", "RUNTIME_DRIFT"),
    ("semantic_policy", "RUNTIME_DRIFT"),
    ("added_runtime", "RUNTIME_DRIFT"),
    ("config_bytes", "RUNTIME_DRIFT"),
    ("config_hash", "INVALID_FREEZE"),
    ("candidate_sha", "INVALID_FREEZE"),
])
def test_freeze_detects_tampering_against_real_git(tmp_path, change, expected):
    subprocess.run(["git", "clone", "--shared", "--no-checkout", "--single-branch",
                    str(freeze.ROOT), str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", freeze.CANDIDATE, "--", "packages", "workers", "config", freeze.SEMANTIC],
                   cwd=tmp_path, check=True, capture_output=True)
    record = freeze.create(tmp_path)
    assert freeze.readiness(tmp_path)["status"] == "PASS"
    original_record = (tmp_path/freeze.RECORD).read_bytes()
    if change in {"config_hash", "candidate_sha"}:
        if change == "config_hash": record["bindings"]["field_policy"]["sha256"] = "0" * 64
        else: record["candidate_commit_sha"] = "1a857337c200f704a159f43a8acc6c00a8d184d3"
        # Even a recomputed self-digest cannot replace the Git-bound candidate.
        record.pop("freeze_sha256")
        record["freeze_sha256"] = freeze.content_hash(record)
        (tmp_path/freeze.RECORD).write_text(json.dumps(record), encoding="utf-8")
    else:
        name = {"runtime":"packages/semantic_authority.py", "semantic_policy":freeze.SEMANTIC,
                "added_runtime":"packages/synthetic_added_runtime.py",
                "config_bytes":record["bindings"]["field_policy"]["path"]}[change]
        with (tmp_path/name).open("a", encoding="utf-8") as stream: stream.write("\n# synthetic tampering\n")
        assert (tmp_path/freeze.RECORD).read_bytes() == original_record
    assert freeze.readiness(tmp_path)["status"] == expected
