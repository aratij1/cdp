"""Configured costs from measured workload; unknown nonzero-use rates stay unknown."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Workload:
    pages: int
    claims: int
    pages_per_busy_hour: Decimal | None = None
    utilization: Decimal | None = None
    gpu_used: bool = False
    paid_ocr_calls: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    authority_calls: int = 0


@dataclass(frozen=True)
class Rates:
    compute_hourly: Decimal | None = None
    gpu_hourly: Decimal | None = None
    paid_ocr_per_call: Decimal | None = None
    llm_input_per_million: Decimal | None = None
    llm_output_per_million: Decimal | None = None
    authority_per_call: Decimal | None = None
    storage_io_per_page: Decimal | None = None


def calculate(work: Workload, rates: Rates) -> dict:
    counts = (
        work.pages,
        work.claims,
        work.paid_ocr_calls,
        work.llm_input_tokens,
        work.llm_output_tokens,
        work.authority_calls,
    )
    if any(type(n) is not int or n < 0 for n in counts) or not work.pages:
        raise ValueError("INVALID_MEASURED_WORKLOAD")
    if type(work.gpu_used) is not bool:
        raise ValueError("BOOLEAN_GPU_USAGE_REQUIRED")
    for value in (*vars(rates).values(), work.pages_per_busy_hour, work.utilization):
        if value is not None and (
            not isinstance(value, Decimal) or not value.is_finite() or value < 0
        ):
            raise ValueError("FINITE_DECIMAL_RATE_REQUIRED")
    if work.utilization is not None and not 0 < work.utilization <= 1:
        raise ValueError("INVALID_UTILIZATION")
    if work.pages_per_busy_hour is not None and work.pages_per_busy_hour <= 0:
        raise ValueError("INVALID_THROUGHPUT")

    def used(count, rate, scale=Decimal(1)):
        return (
            Decimal(0)
            if count == 0
            else Decimal(count) * rate / scale
            if rate is not None
            else None
        )

    paid = [
        used(work.paid_ocr_calls, rates.paid_ocr_per_call),
        used(work.llm_input_tokens, rates.llm_input_per_million, Decimal(1000000)),
        used(work.llm_output_tokens, rates.llm_output_per_million, Decimal(1000000)),
    ]
    ai = sum(paid, Decimal(0)) / work.pages if all(p is not None for p in paid) else None
    gpu = rates.gpu_hourly if work.gpu_used else Decimal(0)
    compute = (
        (rates.compute_hourly + gpu) / (work.pages_per_busy_hour * work.utilization)
        if rates.compute_hourly is not None
        and gpu is not None
        and work.pages_per_busy_hour is not None
        and work.utilization is not None
        else None
    )
    authority = used(work.authority_calls, rates.authority_per_call)
    per_claim = authority / work.claims if authority is not None and work.claims else None
    components = (
        compute,
        ai,
        authority / work.pages if authority is not None else None,
        rates.storage_io_per_page,
    )
    total = (
        sum((c for c in components if c is not None), Decimal(0))
        if all(c is not None for c in components)
        else None
    )
    hourly_denominator = (
        work.pages_per_busy_hour * work.utilization
        if work.pages_per_busy_hour is not None and work.utilization is not None
        else None
    )
    cpu = (
        rates.compute_hourly / hourly_denominator
        if rates.compute_hourly is not None and hourly_denominator
        else None
    )
    gpu_cost = (
        Decimal(0)
        if not work.gpu_used
        else (
            rates.gpu_hourly / hourly_denominator
            if rates.gpu_hourly is not None and hourly_denominator
            else None
        )
    )
    details = {
        "cpu_runtime": cpu,
        "gpu_runtime": gpu_cost,
        "paid_ocr": paid[0] / work.pages if paid[0] is not None else None,
        "llm_input": paid[1] / work.pages if paid[1] is not None else None,
        "llm_output": paid[2] / work.pages if paid[2] is not None else None,
        "authority_lookup": authority / work.pages if authority is not None else None,
        "storage_io": rates.storage_io_per_page,
    }
    return {
        "components": {
            name: {
                "cost_per_page": str(value) if value is not None else None,
                "status": "CONFIGURED" if value is not None else "NOT_CONFIGURED",
            }
            for name, value in details.items()
        },
        "ocr_runtime_allocation": "INCLUDED_IN_FULL_PATH_CPU_GPU_RUNTIME; paid OCR calls are added separately",
        "compute_cost_per_page": str(compute) if compute is not None else None,
        "paid_ai_cost_per_page": str(ai) if ai is not None else None,
        "authority_cost_per_claim": str(per_claim) if per_claim is not None else None,
        "total_cost_per_page": str(total) if total is not None else None,
        "paid_ai_gate": "PASS"
        if ai is not None and ai <= Decimal("0.001")
        else "NOT_CONFIGURED"
        if ai is None
        else "FAIL",
        "pricing_status": "CONFIGURED" if total is not None else "NOT_CONFIGURED",
        "denominator_pages": work.pages,
        "denominator_claims": work.claims,
        "formula": "Hourly CPU plus used GPU / (busy pages per hour * utilization); add measured paid AI, authority and storage/IO allocations.",
    }
