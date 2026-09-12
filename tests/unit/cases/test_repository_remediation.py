"""Synthetic regression checks for repository and acceptance safety."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from packages.ocr_cache import InMemoryOCRCache, OCRCacheEntry
from scripts.repository_safety import classify
from tests.unit.cases.test_qualification_closure_inputs import snapshots
from tests.unit.cases.test_release_scoring_cost_closure import seal


@pytest.mark.parametrize(
    "path,payload",
    [
        ("claims/nested/a.txt", b"synthetic"),
        ("assets/a.TIFF", b"synthetic"),
        ("assets/renamed.bin", b"II*\x00synthetic"),
        ("assets/document.bin", b"%PDF-1.7 synthetic"),
        ("assets/big-endian.bin", b"MM\x00*synthetic"),
        ("assets/archive.bin", b"PK\x03\x04synthetic"),
        ("exports/data.json", b'{"patient_name": "SYNTHETIC ONLY"}'),
        (".pytest-custom/page.bin", b"synthetic"),
    ],
)
def test_sensitive_assets_are_blocked(path, payload):
    assert classify(path, payload)


def test_source_schema_is_not_a_data_export():
    assert not classify("packages/schema.py", b"patient_name: str")


def test_concurrent_identical_ocr_is_computed_once():
    cache = InMemoryOCRCache()
    entered, release = Event(), Event()
    calls = []

    def compute():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return OCRCacheEntry(("synthetic",), "synthetic-reference")

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(cache.get_or_compute, "same", compute) for _ in range(4)]
        assert entered.wait(5)
        release.set()
        results = [future.result() for future in futures]
    assert len(calls) == 1
    assert sum(not hit for _, hit in results) == 1


def test_failed_ocr_can_retry():
    cache = InMemoryOCRCache()
    with pytest.raises(ValueError):
        cache.get_or_compute("key", lambda: (_ for _ in ()).throw(ValueError("synthetic")))
    entry, hit = cache.get_or_compute("key", lambda: OCRCacheEntry((), "retry"))
    assert entry.evidence_reference == "retry" and not hit


def test_false_accepts_and_safe_stp_are_measured():
    truth, raw, _, membership, score = snapshots()
    for row in raw["fields"]:
        row["accepted"] = True
        row["review_required"] = False
    raw["fields"][0]["value"] = "DELIBERATELY WRONG"
    seal(raw)
    metrics = score(truth, raw, None, membership)["raw"]
    assert metrics["false_accepts"] >= 1
    assert metrics["stp_safe"] == 0
    assert (
        metrics["false_accepts"]
        == metrics["accepted_fields"] - metrics["accepted_precision_numerator"]
    )


def test_declared_stp_with_wrong_field_is_not_safe():
    truth, raw, _, membership, score = snapshots()
    for row in raw["fields"]:
        row.update(value="SYNTHETIC", accepted=True, review_required=False)
    raw["claims"]["claim"].update(
        output_completed=True,
        required_fields_pass=True,
        required_evidence_pass=True,
        automatic_output_safely_generated=True,
        human_corrected=False,
        human_reviewed=False,
    )
    seal(raw)
    assert score(truth, raw, None, membership)["raw"]["stp_safe"] == 1
    raw["fields"][0]["value"] = "INCORRECT"
    seal(raw)
    metrics = score(truth, raw, None, membership)["raw"]
    assert metrics["stp"] == 1
    assert metrics["stp_safe"] == 0
    assert metrics["false_stp_claims"] == 1


def test_zero_accepts_does_not_mean_perfect_precision():
    truth, raw, _, membership, score = snapshots()
    for row in raw["fields"]:
        row.update(accepted=False, review_required=True)
    seal(raw)
    metrics = score(truth, raw, None, membership)["raw"]
    assert metrics["accepted_precision"] is None
    assert metrics["false_accepts"] == 0


def test_history_guard_catches_deleted_path_with_reused_blob(tmp_path, monkeypatch):
    from scripts.repository_safety import git, scan

    monkeypatch.chdir(tmp_path)
    git("init")
    git("config", "user.name", "Synthetic Test")
    git("config", "user.email", "synthetic@example.invalid")
    (tmp_path / "safe.txt").write_text("synthetic")
    git("add", "safe.txt")
    git("commit", "-m", "synthetic")
    (tmp_path / "claims").mkdir()
    (tmp_path / "claims" / "sample.txt").write_text("synthetic")
    git("add", "claims/sample.txt")
    git("commit", "-m", "synthetic")
    git("rm", "claims/sample.txt")
    git("commit", "-m", "synthetic")
    assert scan()["status"] == "PASS"
    report = scan(history=True)
    assert report["status"] == "BLOCKED"
    assert "sample.txt" not in str(report)


def test_guard_reads_staged_content_not_working_copy(tmp_path, monkeypatch):
    from scripts.repository_safety import git, scan

    monkeypatch.chdir(tmp_path)
    git("init")
    payload = tmp_path / "renamed.bin"
    payload.write_bytes(b"II*\x00synthetic")
    git("add", "renamed.bin")
    payload.write_bytes(b"harmless working copy")
    assert scan()["status"] == "BLOCKED"


def test_history_guard_catches_sensitive_path_after_rename(tmp_path, monkeypatch):
    from scripts.repository_safety import git, scan

    monkeypatch.chdir(tmp_path)
    git("init")
    git("config", "user.name", "Synthetic Test")
    git("config", "user.email", "synthetic@example.invalid")
    (tmp_path / "claims").mkdir()
    (tmp_path / "claims" / "sample.txt").write_text("synthetic")
    git("add", ".")
    git("commit", "-m", "synthetic input")
    git("mv", "claims/sample.txt", "safe.txt")
    git("commit", "-m", "synthetic rename")
    assert scan()["status"] == "PASS"
    assert scan(history=True, ref="HEAD")["status"] == "BLOCKED"
