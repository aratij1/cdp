import json
from io import BytesIO

from packages.settings import Settings
from workers.cascade.azure_di_backend import AzureDocumentIntelligenceReadBackend
from workers.cascade.azure_di_factory import (
    AzureDocumentIntelligenceConfigurationError,
    azure_document_intelligence_configured,
    build_azure_read_engine,
)
from workers.cascade.azure_read_adapter import AzureReadEvidence


class _FakeResponse:
    def __init__(self, *, headers=None, body=b"", status=200):
        self.headers = headers or {}
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_azure_di_backend_polls_prebuilt_read():
    calls: list[str] = []

    def opener(request, timeout=30):
        calls.append(request.full_url if hasattr(request, "full_url") else request.get_full_url())
        if request.get_method() == "POST":
            return _FakeResponse(
                headers={"Operation-Location": "https://di.example/ops/1"},
            )
        payload = {
            "status": "succeeded",
            "analyzeResult": {
                "content": "01/15/1966",
                "styles": [{"isHandwritten": True}],
                "pages": [{"words": [{"content": "01/15/1966", "confidence": 0.92}]}],
            },
        }
        return _FakeResponse(body=json.dumps(payload).encode("utf-8"))

    backend = AzureDocumentIntelligenceReadBackend(
        "https://di.example",
        "secret",
        opener=opener,
        poll_interval_seconds=0,
        min_interval_seconds=0,
    )
    evidence = backend.analyze(b"\x89PNG")
    assert isinstance(evidence, AzureReadEvidence)
    assert evidence.text == "01/15/1966"
    assert evidence.handwritten is True
    assert evidence.confidence == 0.92
    assert any("prebuilt-read:analyze" in url for url in calls)


def test_parse_azure_di_retry_after_from_body_and_header():
    from workers.cascade.azure_di_backend import parse_azure_di_retry_after_seconds

    body = (
        'Requests ... F0 pricing tier. Please retry after 55 seconds. '
        "To increase your rate limit switch to a paid tier."
    )
    assert parse_azure_di_retry_after_seconds(body) == 55.0
    assert (
        parse_azure_di_retry_after_seconds(
            "no hint",
            headers={"Retry-After": "12"},
            default=55.0,
        )
        == 12.0
    )
    assert parse_azure_di_retry_after_seconds("no hint", default=55.0) == 55.0


def test_azure_di_backend_retries_poll_on_http_429():
    """F0 tier 429 on GetAnalyzeResult should sleep then succeed."""
    from urllib.error import HTTPError

    sleeps: list[float] = []
    poll_calls = {"n": 0}

    def opener(request, timeout=30):
        if request.get_method() == "POST":
            return _FakeResponse(
                headers={"Operation-Location": "https://di.example/ops/1"},
            )
        poll_calls["n"] += 1
        if poll_calls["n"] == 1:
            raise HTTPError(
                "https://di.example/ops/1",
                429,
                "Too Many Requests",
                hdrs=None,
                fp=BytesIO(
                    b'{"error":{"code":"429","message":'
                    b'"Please retry after 55 seconds."}}'
                ),
            )
        payload = {
            "status": "succeeded",
            "analyzeResult": {"content": "ok", "pages": []},
        }
        return _FakeResponse(body=json.dumps(payload).encode("utf-8"))

    backend = AzureDocumentIntelligenceReadBackend(
        "https://di.example",
        "secret",
        opener=opener,
        poll_interval_seconds=0,
        rate_limit_retries=2,
        rate_limit_wait_seconds=55.0,
        min_interval_seconds=0,
        sleeper=sleeps.append,
    )
    evidence = backend.analyze(b"\x89PNG")
    assert evidence.text == "ok"
    assert sleeps == [55.0]
    assert poll_calls["n"] == 2


def test_azure_di_backend_retries_analyze_on_urlopen_timeout():
    """Transient urlopen timeouts should retry before REGISTRATION_FAILED."""
    from urllib.error import URLError

    sleeps: list[float] = []
    post_calls = {"n": 0}

    def opener(request, timeout=30):
        if request.get_method() == "POST":
            post_calls["n"] += 1
            if post_calls["n"] == 1:
                raise URLError(TimeoutError("timed out"))
            return _FakeResponse(
                headers={"Operation-Location": "https://di.example/ops/1"},
            )
        payload = {
            "status": "succeeded",
            "analyzeResult": {"content": "ok", "pages": []},
        }
        return _FakeResponse(body=json.dumps(payload).encode("utf-8"))

    backend = AzureDocumentIntelligenceReadBackend(
        "https://di.example",
        "secret",
        opener=opener,
        poll_interval_seconds=0,
        transport_retries=2,
        transport_wait_seconds=1.5,
        min_interval_seconds=0,
        sleeper=sleeps.append,
    )
    evidence = backend.analyze(b"\x89PNG")
    assert evidence.text == "ok"
    assert post_calls["n"] == 2
    assert sleeps == [1.5]


def test_analyze_requests_are_spaced_to_one_per_minute(tmp_path, monkeypatch):
    from workers.cascade.azure_di_backend import wait_for_azure_di_slot

    monkeypatch.setenv("CDP_AZURE_DI_SLOT_PATH", str(tmp_path / "slot"))
    clock = {"t": 1_000.0}
    sleeps: list[float] = []

    def now() -> float:
        return clock["t"]

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    def opener(request, timeout=30):
        if request.get_method() == "POST":
            return _FakeResponse(
                headers={"Operation-Location": "https://di.example/ops/1"},
            )
        payload = {"status": "succeeded", "analyzeResult": {"content": "ok", "pages": []}}
        return _FakeResponse(body=json.dumps(payload).encode("utf-8"))

    backend = AzureDocumentIntelligenceReadBackend(
        "https://di.example",
        "secret",
        opener=opener,
        poll_interval_seconds=0,
        min_interval_seconds=60,
        sleeper=sleeper,
        clock=now,
    )
    backend.analyze(b"png")
    backend.analyze(b"png")
    assert sleeps == [60.0]
    wait_for_azure_di_slot(interval_seconds=0, sleeper=sleeper, now=now)
    assert sleeps == [60.0]


def test_factory_fails_closed_without_gates():
    settings = Settings(
        _env_file=None,
        azure_document_intelligence_enabled=True,
        azure_document_intelligence_endpoint="https://di.example",
        azure_document_intelligence_api_key="secret",
        azure_document_intelligence_authorized=False,
    )
    assert azure_document_intelligence_configured(settings) is False
    try:
        build_azure_read_engine(settings)
    except AzureDocumentIntelligenceConfigurationError as exc:
        assert "authorization" in str(exc).lower() or "PHI" in str(exc)
    else:
        raise AssertionError("expected fail-closed configuration error")


def test_factory_builds_when_phi_gates_approved():
    settings = Settings(
        _env_file=None,
        azure_document_intelligence_enabled=True,
        azure_document_intelligence_endpoint="https://di.example",
        azure_document_intelligence_api_key="secret",
        azure_document_intelligence_authorized=True,
        azure_document_intelligence_region_approved=True,
        azure_document_intelligence_phi_contract_approved=True,
    )
    assert azure_document_intelligence_configured(settings) is True
    engine = build_azure_read_engine(settings)
    assert engine.engine_name == "azure_document_intelligence_read"
    assert engine.model_name == "prebuilt-read"
