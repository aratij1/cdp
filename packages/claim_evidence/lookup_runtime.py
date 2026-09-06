"""Bounded async authority lookup execution. No implicit network configuration.

Transports must be cancellation-cooperative and read-only. Each client is bound
for its lifetime to one provider/configuration; caches are process-private and
must not be serialized. No request content or exception text enters telemetry.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from .authoritative_snapshot import MatchStatus
from .enablement import LookupResult


@dataclass(frozen=True)
class LookupPolicy:
    timeout_ms: int = 500
    ttl_seconds: float = 0
    max_requests_per_minute: int = 60
    max_cache_entries: int = 128
    cost_usd_per_lookup: Decimal | None = None
    budget_usd: Decimal | None = None

    def __post_init__(self):
        if (
            any(
                type(v) is not int or v <= 0
                for v in (self.timeout_ms, self.max_requests_per_minute, self.max_cache_entries)
            )
            or self.timeout_ms <= 0
            or not math.isfinite(self.ttl_seconds)
            or self.ttl_seconds < 0
            or self.max_requests_per_minute <= 0
            or self.max_cache_entries <= 0
        ):
            raise ValueError("INVALID_LOOKUP_POLICY")
        for cost in (self.cost_usd_per_lookup, self.budget_usd):
            if cost is not None and (
                not isinstance(cost, Decimal) or not cost.is_finite() or cost < 0
            ):
                raise ValueError("INVALID_LOOKUP_COST")


@dataclass(frozen=True)
class LookupExecution:
    result: LookupResult
    elapsed_ms: float
    cache_hit: bool
    # Reserved configured charge, not a verified provider invoice.
    configured_cost_usd: Decimal | None


class BoundedAuthorityClient:
    """One event-loop client for an immutable, explicitly configured transport.

    Unknown pricing is visible; a configured budget requires configured pricing.
    Unavailable/error results are never cached. All charged attempts, including
    failures, consume the conservative configured budget; no retries are implied.
    """

    def __init__(
        self,
        provider_name: str,
        transport: Callable[..., Awaitable[LookupResult]] | None = None,
        *,
        policy: LookupPolicy = LookupPolicy(),
    ):
        self.provider_name = provider_name
        self._transport = transport
        self.policy = policy
        self._cache: dict[str, tuple[float, LookupResult]] = {}
        self._calls: deque[float] = deque()
        self._spent = Decimal(0)

    async def lookup(self, **query: object) -> LookupExecution:
        start = time.monotonic()

        def finish(
            result: LookupResult, *, cached: bool = False, cost: Decimal | None = Decimal(0)
        ) -> LookupExecution:
            return LookupExecution(result, (time.monotonic() - start) * 1000, cached, cost)

        def unavailable(reason: str, cost: Decimal | None = Decimal(0)) -> LookupExecution:
            return finish(
                LookupResult(
                    MatchStatus.NOT_AVAILABLE, self.provider_name, datetime.now(UTC), reason
                ),
                cost=cost,
            )

        if self._transport is None:
            return unavailable("PROVIDER_NOT_CONFIGURED")

        # Reject unsupported serialization rather than conflate distinct request contexts.
        def encode(value: object):
            # Tag every type, including containers, so a date cannot collide with
            # a caller-supplied dictionary that resembles its serialized form.
            if type(value) is date:
                return ["date", value.isoformat()]
            if value is None or type(value) in (str, bool, int):
                return [type(value).__name__, value]
            if type(value) is float and math.isfinite(value):
                return ["float", value]
            if isinstance(value, (list, tuple)) and type(value) in (list, tuple):
                return [type(value).__name__, [encode(v) for v in value]]
            if type(value) is dict and all(type(k) is str for k in value):
                return ["dict", [[k, encode(v)] for k, v in sorted(value.items())]]
            raise TypeError("UNSUPPORTED_QUERY_TYPE")

        try:
            query = copy.deepcopy(query)
            key = hashlib.sha256(
                json.dumps(encode(query), sort_keys=True, allow_nan=False).encode()
            ).hexdigest()
        except (TypeError, ValueError, RecursionError):
            return unavailable("INVALID_REQUEST_CONTEXT")
        # Preserve the hashed context across an await even if the caller later
        # mutates a nested list/dictionary used to construct the request.
        cached = self._cache.get(key)
        if cached and cached[0] > start:
            return finish(cached[1], cached=True)
        self._cache.pop(key, None)
        while self._calls and self._calls[0] <= start - 60:
            self._calls.popleft()
        if len(self._calls) >= self.policy.max_requests_per_minute:
            return unavailable("RATE_LIMITED")
        cost = self.policy.cost_usd_per_lookup
        if self.policy.budget_usd is not None:
            if cost is None:
                return unavailable("PRICING_NOT_CONFIGURED")
            if self._spent + cost > self.policy.budget_usd:
                return unavailable("LOOKUP_BUDGET_EXCEEDED")
        self._calls.append(start)
        if cost is not None:
            self._spent += cost
        try:
            result = await asyncio.wait_for(self._transport(**query), self.policy.timeout_ms / 1000)
        except TimeoutError:
            return unavailable("LOOKUP_TIMEOUT", cost)
        except Exception:  # noqa: BLE001 - isolate arbitrary provider failures without PHI logging
            return unavailable("LOOKUP_FAILED", cost)
        if (
            not isinstance(result, LookupResult)
            or not isinstance(result.provenance_ids, tuple)
            or not result.provenance_ids
            or not all(isinstance(p, str) and p.strip() for p in result.provenance_ids)
            or not isinstance(result.status, MatchStatus)
            or (result.status == MatchStatus.MATCH and not result.has_record_provenance)
        ):
            return unavailable("INVALID_PROVIDER_RESULT", cost)
        if self.policy.ttl_seconds and result.status != MatchStatus.NOT_AVAILABLE:
            if len(self._cache) >= self.policy.max_cache_entries:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.monotonic() + self.policy.ttl_seconds, result)
        return finish(result, cost=cost)


async def independent_lookups(
    requests: dict[str, tuple[BoundedAuthorityClient, dict[str, object]]],
    *,
    max_concurrent: int = 4,
) -> dict[str, LookupExecution]:
    """Call independent providers concurrently; each has its own deadline and limits.

    Caller supplies only already-authorized context; a result from one provider
    must not be required to form another request in this group.
    """
    if type(max_concurrent) is not int or max_concurrent <= 0:
        raise ValueError("INVALID_CONCURRENCY_BOUND")
    names = tuple(requests)
    # Snapshot before queueing so waiting for a concurrency slot cannot expose
    # caller mutation to a later transport or cache key.
    snapshots = {k: (requests[k][0], copy.deepcopy(requests[k][1])) for k in names}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def execute(name: str) -> LookupExecution:
        async with semaphore:
            client, query = snapshots[name]
            return await client.lookup(**query)

    results = await asyncio.gather(*(execute(k) for k in names))
    return dict(zip(names, results, strict=True))
