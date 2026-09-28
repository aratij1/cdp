"""Azure Document Intelligence prebuilt-read REST backend (crop-only).

Uses the Document Intelligence analyze API with polling. Credentials stay in
Settings / env — never logged or persisted on candidates.

F0 (free) tiers rate-limit Analyze / GetAnalyzeResult with HTTP 429. We sleep
for the server-requested backoff (default ~55s) and retry a bounded number of
times so last-resort page-corners can complete instead of terminal REG.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from workers.cascade.azure_read_adapter import AzureReadEvidence

# Azure F0 message typically says "Please retry after 55 seconds."
_DEFAULT_429_WAIT_SECONDS = 55.0
_DEFAULT_MIN_INTERVAL_SECONDS = 60.0
_RETRY_AFTER_RE = re.compile(
    r"retry\s+after\s+(\d+(?:\.\d+)?)\s*second",
    re.IGNORECASE,
)


def azure_di_min_interval_seconds() -> float:
    """Minimum gap between analyze transactions. F0 allows one per minute."""
    raw = (os.environ.get("CDP_AZURE_DI_MIN_INTERVAL_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_MIN_INTERVAL_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_MIN_INTERVAL_SECONDS


def azure_di_slot_path() -> Path:
    raw = (os.environ.get("CDP_AZURE_DI_SLOT_PATH") or "").strip()
    return Path(raw) if raw else Path("/tmp/cdp-azure-di-slot")


def wait_for_azure_di_slot(
    *,
    interval_seconds: float,
    sleeper,
    now=time.time,
    slot_path: Path | None = None,
) -> None:
    """Block until this process may send one new analyze request.

    Spawn workers do not share memory, so the timestamp lives in a file lock.
    Polls of an in-flight operation are not new transactions.
    """
    if interval_seconds <= 0:
        return
    path = slot_path or azure_di_slot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    import fcntl

    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        raw = handle.read().strip()
        try:
            last = float(raw) if raw else 0.0
        except ValueError:
            last = 0.0
        current = float(now())
        delay = interval_seconds - (current - last)
        if delay > 0:
            sleeper(delay)
            current = float(now())
        handle.seek(0)
        handle.truncate()
        handle.write(f"{current:.6f}")
        handle.flush()


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def parse_azure_di_retry_after_seconds(
    body: str,
    *,
    headers: Any | None = None,
    default: float = _DEFAULT_429_WAIT_SECONDS,
) -> float:
    """Extract backoff seconds from Retry-After header or Azure 429 body text."""
    if headers is not None:
        raw = None
        try:
            raw = headers.get("Retry-After") or headers.get("retry-after")
        except Exception:  # noqa: BLE001
            raw = None
        if raw is not None and str(raw).strip():
            try:
                return max(1.0, float(str(raw).strip()))
            except ValueError:
                pass
    match = _RETRY_AFTER_RE.search(body or "")
    if match:
        try:
            return max(1.0, float(match.group(1)))
        except ValueError:
            pass
    return max(1.0, float(default))


def _is_rate_limit_http(exc: HTTPError) -> bool:
    return int(getattr(exc, "code", 0) or 0) == 429


def _is_transport_timeout(exc: BaseException) -> bool:
    """True for urlopen/socket timeouts that often clear on a short retry."""
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            return True
        text = str(reason or exc).casefold()
        return "timed out" in text or "timeout" in text
    text = str(exc).casefold()
    return "timed out" in text or "timeout" in text


class AzureDocumentIntelligenceReadBackend:
    """Synchronous prebuilt-read client for regional field crops."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        api_version: str = "2024-11-30",
        model_id: str = "prebuilt-read",
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float | None = None,
        max_polls: int | None = None,
        opener=None,
        rate_limit_retries: int | None = None,
        rate_limit_wait_seconds: float | None = None,
        transport_retries: int | None = None,
        transport_wait_seconds: float | None = None,
        min_interval_seconds: float | None = None,
        sleeper=None,
        clock=None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._api_version = api_version
        self._model_id = model_id
        self._timeout = timeout_seconds
        # Full-page unstructured REG reads often need >6s; default 150×0.35s ≈ 50s.
        self._poll_interval = (
            float(poll_interval_seconds)
            if poll_interval_seconds is not None
            else _env_float("CDP_AZURE_DI_POLL_INTERVAL_SECONDS", 0.35)
        )
        self._max_polls = (
            int(max_polls)
            if max_polls is not None
            else _env_int("CDP_AZURE_DI_MAX_POLLS", 150)
        )
        self._opener = opener or urlopen
        # Default 2 retries ⇒ up to 3 attempts (initial + 2 waits) for F0 429.
        self._rate_limit_retries = (
            int(rate_limit_retries)
            if rate_limit_retries is not None
            else _env_int("CDP_AZURE_DI_429_RETRIES", 2)
        )
        self._rate_limit_wait_seconds = (
            float(rate_limit_wait_seconds)
            if rate_limit_wait_seconds is not None
            else _env_float("CDP_AZURE_DI_429_WAIT_SECONDS", _DEFAULT_429_WAIT_SECONDS)
        )
        # Transient urlopen / socket timeouts (unstructured REG page reads).
        self._transport_retries = (
            int(transport_retries)
            if transport_retries is not None
            else _env_int("CDP_AZURE_DI_TRANSPORT_RETRIES", 2)
        )
        self._transport_wait_seconds = (
            float(transport_wait_seconds)
            if transport_wait_seconds is not None
            else _env_float("CDP_AZURE_DI_TRANSPORT_WAIT_SECONDS", 2.0)
        )
        self._sleeper = sleeper or time.sleep
        self._clock = clock or time.time
        self._min_interval_seconds = (
            float(min_interval_seconds)
            if min_interval_seconds is not None
            else azure_di_min_interval_seconds()
        )

    def analyze(self, image_bytes: bytes) -> AzureReadEvidence:
        if not image_bytes:
            return AzureReadEvidence("", 0.0, False)
        payload = self.analyze_raw(image_bytes)
        return self._to_evidence(payload)

    def analyze_raw(self, image_bytes: bytes) -> dict[str, Any]:
        """Return the full Azure DI analyze payload (pages/polygons included)."""
        if not image_bytes:
            return {}
        wait_for_azure_di_slot(
            interval_seconds=self._min_interval_seconds,
            sleeper=self._sleeper,
            now=self._clock,
        )
        operation = self._start_analyze(image_bytes)
        return self._poll_result(operation)

    def _sleep_rate_limit(self, body: str, headers: Any | None = None) -> None:
        wait = parse_azure_di_retry_after_seconds(
            body,
            headers=headers,
            default=self._rate_limit_wait_seconds,
        )
        self._sleeper(wait)

    def _start_analyze(self, image_bytes: bytes) -> str:
        url = (
            f"{self._endpoint}/documentintelligence/documentModels/"
            f"{self._model_id}:analyze?api-version={self._api_version}"
        )
        attempts = (
            max(0, self._rate_limit_retries) + max(0, self._transport_retries) + 1
        )
        last_exc: Exception | None = None
        for attempt in range(attempts):
            request = Request(
                url,
                data=image_bytes,
                method="POST",
                headers={
                    "Ocp-Apim-Subscription-Key": self._api_key,
                    "Content-Type": "application/octet-stream",
                },
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    location = response.headers.get(
                        "operation-location"
                    ) or response.headers.get("Operation-Location")
                    if not location:
                        raise RuntimeError("Azure DI analyze missing operation-location")
                    return location
            except HTTPError as exc:
                body = exc.read()[:500].decode("utf-8", "replace")
                last_exc = RuntimeError(
                    f"Azure DI analyze HTTP {exc.code}: {body}"
                )
                last_exc.__cause__ = exc
                if _is_rate_limit_http(exc) and attempt + 1 < attempts:
                    self._sleep_rate_limit(body, headers=getattr(exc, "headers", None))
                    continue
                raise last_exc from exc
            except (URLError, TimeoutError) as exc:
                last_exc = RuntimeError(f"Azure DI analyze transport error: {exc}")
                last_exc.__cause__ = exc
                if _is_transport_timeout(exc) and attempt + 1 < attempts:
                    self._sleeper(self._transport_wait_seconds)
                    continue
                raise last_exc from exc
        assert last_exc is not None
        raise last_exc

    def _poll_result(self, operation_url: str) -> dict[str, Any]:
        rate_limit_retries_left = max(0, self._rate_limit_retries)
        transport_retries_left = max(0, self._transport_retries)
        polls = 0
        while polls < self._max_polls:
            request = Request(
                operation_url,
                method="GET",
                headers={"Ocp-Apim-Subscription-Key": self._api_key},
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    import json

                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read()[:500].decode("utf-8", "replace")
                if _is_rate_limit_http(exc) and rate_limit_retries_left > 0:
                    rate_limit_retries_left -= 1
                    self._sleep_rate_limit(body, headers=getattr(exc, "headers", None))
                    # Do not burn a poll slot on a throttled read — retry same poll.
                    continue
                raise RuntimeError(f"Azure DI poll HTTP {exc.code}: {body}") from exc
            except (URLError, TimeoutError) as exc:
                if _is_transport_timeout(exc) and transport_retries_left > 0:
                    transport_retries_left -= 1
                    self._sleeper(self._transport_wait_seconds)
                    continue
                raise RuntimeError(f"Azure DI poll transport error: {exc}") from exc
            polls += 1
            status = str(payload.get("status") or "").lower()
            if status in {"succeeded", "failed", "canceled", "cancelled"}:
                if status != "succeeded":
                    raise RuntimeError(f"Azure DI analyze ended with status={status}")
                return payload
            self._sleeper(self._poll_interval)
        raise RuntimeError("Azure DI analyze timed out waiting for result")

    def _to_evidence(self, payload: dict[str, Any]) -> AzureReadEvidence:
        result = payload.get("analyzeResult") or payload.get("analyze_result") or {}
        content = str(result.get("content") or "").strip()
        styles = result.get("styles") or []
        handwritten = any(bool(style.get("isHandwritten")) for style in styles)
        confidences: list[float] = []
        for page in result.get("pages") or []:
            for word in page.get("words") or []:
                if "confidence" in word:
                    confidences.append(float(word["confidence"]))
            for line in page.get("lines") or []:
                if "confidence" in line:
                    confidences.append(float(line["confidence"]))
        confidence = (
            sum(confidences) / len(confidences)
            if confidences
            else (0.7 if content else 0.0)
        )
        return AzureReadEvidence(content, confidence, handwritten)


def azure_di_handwriting_transport(
    *,
    endpoint: str,
    credential: str,
    crop_png: bytes,
    field_name: str,
    field_type: str,
    timeout: float = 30.0,
    api_version: str = "2024-11-30",
) -> dict[str, Any]:
    """Transport adapter for CropOnlyCloudProvider → Azure DI Read."""
    del field_name, field_type  # crop-only; field metadata is not sent to Azure
    backend = AzureDocumentIntelligenceReadBackend(
        endpoint,
        credential,
        api_version=api_version,
        timeout_seconds=timeout,
    )
    evidence = backend.analyze(crop_png)
    return {
        "value": evidence.text.strip() or None,
        "confidence": evidence.confidence,
        "model_version": f"prebuilt-read@{api_version}",
        "handwritten": evidence.handwritten,
    }
