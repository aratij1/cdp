"""Synthetic regression checks for repository and acceptance safety."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from packages.ocr_cache import InMemoryOCRCache, OCRCacheEntry
from scripts.repository_safety import classify
from tests.unit.cases.test_qualification_closure_inputs import snapshots
from tests.unit.cases.test_release_scoring_cost_closure import seal


@pytest.mark.parametrize("path,payload", [
    ("claims/nested/a.txt", b"synthetic"),
    ("assets/a.TIFF", b"synthetic"),
    ("assets/renamed.bin", b"II*\x00synthetic"),
    ("assets/archive.bin", b"PK\x03\x04synthetic"),
    ("exports/data.json", b'{"patient_name": "SYNTHETIC ONLY"}'),
    (".pytest-custom/page.bin", b"synthetic"),
])
def test_sensitive_assets_are_blocked(path, payload):
    assert classify(path, payload)


def test_source_schema_is_not_a_data_export():
    assert not classify("packages/schema.py", b'patient_name: str')


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
    assert metrics["false_accepts"] == metrics["accepted_fields"] - metrics["accepted_precision_numerator"]
