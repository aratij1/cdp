"""Isolated same-model DirectML semantic screen; never activates production."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from evaluation.production_latency_governor import SEMANTIC_KEYS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation_results/production_closure/latency"


def run(provider_name: str = "DmlExecutionProvider") -> dict:
    # The caller inserts the isolated wheel directory before importing this module.
    import onnxruntime as ort  # type: ignore[import-untyped]

    from evaluation.closure_iteration6_latency import run as benchmark
    from packages.ocr import RapidOCRProvider

    if provider_name not in ort.get_available_providers():
        raise ValueError("EXECUTION_PROVIDER_UNAVAILABLE")
    original = RapidOCRProvider._load_backend
    sessions = []

    def load(self):
        if self._backend is not None:
            return self._backend
        backend = original(self)
        wrappers = (backend.text_det.infer, backend.text_cls.infer, backend.text_rec.session)
        for i, wrapper in enumerate(wrappers):
            old = wrapper.session
            options = old.get_session_options()
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.enable_mem_pattern = False
            options.enable_profiling = True
            options.profile_file_prefix = str(OUT / f"accelerator_nodes_{i}")
            session = ort.InferenceSession(
                old._model_path,
                sess_options=options,
                providers=[provider_name, "CPUExecutionProvider"]
                if provider_name != "CPUExecutionProvider"
                else [provider_name],
            )
            if session.get_providers()[0] != provider_name:
                raise ValueError("REQUESTED_PROVIDER_NOT_ACTIVE")
            wrapper.session = session
            sessions.append(session)
        return backend

    name = "directml_screen" if provider_name == "DmlExecutionProvider" else "ort124_cpu_control"
    RapidOCRProvider._load_backend = load
    try:
        result = benchmark(
            output_dir=OUT, output_name=f"{name}.local.json", page_limit=1, repetitions=1
        )
    finally:
        RapidOCRProvider._load_backend = original
    nodes: Counter = Counter()
    for session in sessions:
        path = Path(session.end_profiling())
        for event in json.loads(path.read_text()):
            provider = event.get("args", {}).get("provider")
            if provider:
                nodes[provider] += 1
    baseline = json.loads((OUT / "qualification.local.json").read_text())
    before = baseline["experiments"][0]["pages"][0]
    after = result["experiments"][0]["pages"][0]
    changed = [k for k in SEMANTIC_KEYS if before[k] != after[k]]
    report = {
        "name": name,
        "onnxruntime_version": ort.__version__,
        "requested_provider": provider_name,
        "executed_node_counts": dict(nodes),
        "protected_semantics_identical": not changed,
        "changed_keys": changed,
        "pages": 1,
        "warm_repetitions": 0,
        "latency_qualified": False,
        "production_activated": False,
        "status": "REJECT_SEMANTIC_MISMATCH" if changed else "SCREEN_PASS_REQUIRES_QUALIFICATION",
        "screen_page_ms": after["stages"]["total_ms"],
        "scope": "ONE_PAGE_SEMANTIC_SCREEN_WITH_NODE_PROFILING_NOT_LATENCY_QUALIFICATION",
    }
    (OUT / f"{name}_result.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
