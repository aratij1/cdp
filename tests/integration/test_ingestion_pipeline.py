"""End-to-end against the real docker-compose stack (Postgres, MinIO,
Redpanda, ingestion-api, document-preparation-worker).

Run via `make test-integration` (brings the stack up first). Skipped
automatically if the ingestion API isn't reachable, so it never blocks
`pytest tests/unit`.
"""

import io
import random
import time

import httpx
import pytest
from PIL import Image

BASE_URL = "http://localhost:8000"


def _api_reachable() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/health", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _api_reachable(), reason="ingestion API not reachable at :8000"),
]


def _multipage_tiff_bytes(n_pages: int = 3) -> bytes:
    """Every call produces content-distinct bytes (a random marker pixel
    per page) -- this suite runs against a real, persistent Postgres/MinIO
    (the compose volumes aren't reset between runs), so fixed content
    would make a fresh test run look like a duplicate of a previous one
    and silently assert idempotency-path behavior instead of the
    new-document path it's meant to test. Tests that specifically want
    identical bytes (idempotency itself) generate the data once and reuse
    it for both uploads, rather than calling this twice."""
    images = [Image.new("1", (400, 300), color=1) for _ in range(n_pages)]
    for image in images:
        marker_x, marker_y = random.randrange(390), random.randrange(290)
        image.putpixel((marker_x, marker_y), 0)
    buf = io.BytesIO()
    images[0].save(
        buf, format="TIFF", compression="group4", save_all=True, append_images=images[1:]
    )
    return buf.getvalue()


def test_health_and_ready_endpoints():
    health = httpx.get(f"{BASE_URL}/health")
    ready = httpx.get(f"{BASE_URL}/ready")
    assert health.status_code == 200
    assert ready.status_code == 200


def test_upload_document_and_wait_for_preparation():
    data = _multipage_tiff_bytes(3)
    response = httpx.post(
        f"{BASE_URL}/documents",
        files={"file": ("integration-test.001", data, "image/tiff")},
        timeout=30.0,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_new_document"] is True
    document_id = body["document_id"]

    deadline = time.monotonic() + 30
    status = body["status"]
    while status not in ("PREPARED", "FAILED") and time.monotonic() < deadline:
        time.sleep(1)
        poll = httpx.get(f"{BASE_URL}/documents/{document_id}")
        assert poll.status_code == 200
        status = poll.json()["status"]

    assert status == "PREPARED"


def test_reuploading_identical_bytes_is_idempotent():
    data = _multipage_tiff_bytes(2)
    first = httpx.post(
        f"{BASE_URL}/documents",
        files={"file": ("dup-test-a.001", data, "image/tiff")},
        timeout=30.0,
    ).json()
    second = httpx.post(
        f"{BASE_URL}/documents",
        files={"file": ("dup-test-b.001", data, "image/tiff")},
        timeout=30.0,
    ).json()

    assert first["document_id"] == second["document_id"]
    assert second["is_new_document"] is False


def test_rejects_unsupported_file_type():
    response = httpx.post(
        f"{BASE_URL}/documents",
        files={"file": ("not-an-image.001", b"plain text", "text/plain")},
        timeout=10.0,
    )
    assert response.status_code == 415


def test_metrics_endpoint_reflects_uploads():
    """The ingestion API's lifespan calls `ObjectStore.ensure_bucket`
    unconditionally (a real MinIO call) -- unlike human_review_api, this
    makes its FastAPI layer only meaningfully testable against the real
    compose stack, not via TestClient + fakes (a bare TestClient attempt
    blocks on the real MinIO connection for the whole botocore retry
    window before failing)."""
    httpx.post(
        f"{BASE_URL}/documents",
        files={"file": ("metrics-test.001", _multipage_tiff_bytes(1), "image/tiff")},
        timeout=30.0,
    )
    response = httpx.get(f"{BASE_URL}/metrics")
    assert response.status_code == 200
    assert 'documents_received_total{detected_format="TIFF"' in response.text
