"""Close the bounded runtime investigation using measured artifacts only."""

from __future__ import annotations

import hashlib
import json
import platform
from importlib.metadata import version

import onnxruntime as ort  # type: ignore[import-untyped]
import psutil  # type: ignore[import-untyped]

from evaluation.production_accelerator_probe import OUT, ROOT


def run() -> dict:
    hardware = json.loads((ROOT / ".test-tmp/runtime-hardware.json").read_text("utf-8-sig"))
    capabilities = {
        "cpu": hardware["cpu"],
        "gpu": hardware["gpu"],
        "gpu_adapter_ram_caveat": "WMI AdapterRAM is not a reliable dedicated VRAM measurement for an integrated GPU.",
        "ram_bytes": psutil.virtual_memory().total,
        "available_ram_bytes_at_discovery": psutil.virtual_memory().available,
        "python": platform.python_version(),
        "onnxruntime": ort.__version__,
        "rapidocr": version("rapidocr-onnxruntime"),
        "production_environment_providers": ort.get_available_providers(),
        "cuda": "UNAVAILABLE_NO_NVIDIA_ADAPTER_OR_CUDA_PROVIDER_DETECTED",
        "directml": "ISOLATED_1.24.4_EXECUTION_CONFIRMED_SEMANTIC_SCREEN_REJECTED",
        "openvino": "ISOLATED_2026.3.1_CPU_RECOGNITION_EXECUTED_SEMANTIC_SCREEN_REJECTED",
        "main_environment_modified": False,
    }
    contract = {
        "target_ms": 5000,
        "statistic": "P95_PER_REPETITION_MEDIAN_OF_AT_LEAST_3_WARM_REPETITIONS",
        "percentile_method": "NEAREST_RANK",
        "minimum_warm_repetitions": 3,
        "cold_start": "Model/session construction measured separately; one process start is not a P95 distribution.",
        "warm_page_extraction": "Long-lived initialized worker: decode/render, preprocessing, fresh OCR, strict identity, applicable registration/localization, candidates, validation, effective state and serialization. Excludes external authorities and request queue; both must be reported separately.",
        "full_claim_latency": "Claim arrival to final decision including all required pages, boundaries, authority lookups, policy and serialization. Independent lookups may overlap; do not sum overlapping durations.",
        "measured_scope": "Fresh TIFF decode/OCR/strict identity and downstream shadow; unavailable business context and canonical worker registration/localization are not exercised.",
        "measured_cohort_pages": 12,
        "ocr_cache": "BYPASS",
        "source_cache": "OS_MANAGED",
        "production_page_sla_qualified": False,
        "full_claim_latency_ms": None,
        "request_queue_latency_ms": None,
        "cached_100_page_replay": "Candidate generation on existing OCR; incompatible with fresh page SLA.",
    }
    names = ("directml_screen", "ort124_cpu_control", "openvino_cpu_screen")
    screens = {name: json.loads((OUT / f"{name}_result.json").read_text()) for name in names}
    if any(s["status"] != "REJECT_SEMANTIC_MISMATCH" for s in screens.values()):
        raise ValueError("UNRESOLVED_RUNTIME_SCREEN_REQUIRES_QUALIFICATION")
    latency = json.loads((ROOT / "docs/closure/production_latency_results.json").read_text())
    final = latency["fresh_qualification"]
    p95 = final["median_warm_p95_ms"]
    decision = {
        "decision": "SAFE_CPU_CEILING_ABOVE_TARGET",
        "cpu_status": "CPU_LATENCY_TARGET_NOT_MET",
        "target_ms": 5000,
        "median_warm_p95_ms": p95,
        "selected_runtime": "RapidOCR 1.4.4 / ONNX Runtime 1.29.0",
        "execution_provider": "CPUExecutionProvider",
        "threads": 8,
        "workers": 1,
        "cpu_memory_arena": True,
        "ocr_max_side": 2000,
        "semantic_fingerprint_preserved": True,
        "production_activated": False,
        "absolute_hardware_ceiling_proven": False,
        "scope": "BEST_SAFE_TESTED_CONFIGURATION_ON_THIS_HOST",
        "runtime_decision_matrix": screens,
        "directml_attribution": "The 1.24.4 CPU control also changes fingerprints relative to retained 1.29.0; differences cannot be attributed solely to GPU execution.",
        "alternative_count": 1,
        "challenger_promotion": "NONE; rejected at protected semantic screen before warm qualification or release recall claims.",
        "benchmark_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for name in names
            for p in (OUT / f"{name}_result.json",)
        },
        "required_next_host_acceptance": {
            "runtime": "Retained ONNX CPU 1.29.0 and exact current OCR model hashes on a dedicated higher-throughput host",
            "minimum_end_to_end_speedup_lower_bound": p95 / 5000,
            "qualification": "Same fixed 12 pages, at least 3 fresh warm repetitions, <=5000ms median P95, identical protected fingerprints; then complete production page/claim path measurement.",
            "specific_host_meeting_target_identified": False,
            "target_achievement_proven": False,
        },
        "further_cpu_sweeps": False,
    }
    for name, report in (
        ("runtime_capabilities.json", capabilities),
        ("latency_contract.json", contract),
        ("runtime_decision.json", decision),
    ):
        (ROOT / "docs/closure" / name).write_text(json.dumps(report, indent=2) + "\n")
    return decision


if __name__ == "__main__":
    run()
