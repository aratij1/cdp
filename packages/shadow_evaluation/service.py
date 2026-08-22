from __future__ import annotations

from hashlib import sha256
from time import perf_counter, process_time
from typing import Callable, Protocol

from packages.evidence.normalization import normalize_agreement_value
from packages.ocr.contracts import OCRCandidate
from packages.route_registry import RouteLifecycle, RouteNotApprovedError, RouteRegistry
from packages.shadow_evaluation.models import (
    CandidateSnapshot,
    ShadowObservation,
    ShadowResult,
)


class ShadowObservationSink(Protocol):
    def append(self, observation: ShadowObservation) -> None: ...


class InMemoryShadowObservationSink:
    def __init__(self) -> None:
        self.observations: list[ShadowObservation] = []

    def append(self, observation: ShadowObservation) -> None:
        self.observations.append(observation)


class ShadowEvaluationService:
    """Execute a governed shadow route without exposing a canonical mutation API."""

    def __init__(self, registry: RouteRegistry, sink: ShadowObservationSink) -> None:
        self.registry = registry
        self.sink = sink

    def observe(
        self,
        *,
        field_name: str,
        document_family: str,
        production_candidate: OCRCandidate,
        shadow_runner: Callable[[], OCRCandidate],
        truth_value: str | None = None,
        additional_memory_bytes: int | None = None,
        cost_usd: float | None = None,
    ) -> ShadowResult:
        route = self.registry.find_any(field_name, document_family)
        if route is None or route.status is not RouteLifecycle.SHADOW:
            status = route.status.value if route else "MISSING"
            raise RouteNotApprovedError(
                f"route for {document_family}.{field_name} has status {status}, not SHADOW"
            )

        wall_started, cpu_started = perf_counter(), process_time()
        shadow_candidate: OCRCandidate | None = None
        execution_status = "COMPLETED"
        try:
            shadow_candidate = shadow_runner()
        except Exception:
            execution_status = "FAILED"
        wall_ms = (perf_counter() - wall_started) * 1000
        cpu_ms = (process_time() - cpu_started) * 1000
        production_value = normalize_agreement_value(field_name, production_candidate.value)
        shadow_value = normalize_agreement_value(
            field_name, shadow_candidate.value if shadow_candidate else None,
        )
        truth_normalized = normalize_agreement_value(field_name, truth_value)
        observation = ShadowObservation(
            field_name=field_name,
            document_family=document_family,
            route_id=route.route_id,
            route_status=route.status.value,
            production_candidate=CandidateSnapshot.from_candidate(production_candidate),
            shadow_candidate=(
                CandidateSnapshot.from_candidate(shadow_candidate)
                if shadow_candidate else None
            ),
            agreement=(
                production_value == shadow_value
                if shadow_candidate is not None else None
            ),
            runtime_latency_ms=wall_ms,
            additional_cpu_ms=cpu_ms,
            additional_memory_bytes=additional_memory_bytes,
            cost_usd=cost_usd,
            execution_status=execution_status,
            truth_status="AVAILABLE" if truth_value is not None else "UNAVAILABLE",
            truth_value_sha256=(
                sha256(truth_normalized.encode()).hexdigest()
                if truth_value is not None else None
            ),
            shadow_correct=(
                shadow_value == truth_normalized
                if truth_value is not None and shadow_candidate is not None else None
            ),
        )
        self.sink.append(observation)
        return ShadowResult(
            canonical_candidate_id=observation.production_candidate.candidate_id,
            canonical_value=production_candidate.value,
            canonical_unchanged=True,
            observation=observation,
        )
