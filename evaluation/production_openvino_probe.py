"""One bounded alternative: same recognition model on OpenVINO CPU, shadow only."""

from __future__ import annotations

import json

from evaluation.production_accelerator_probe import OUT
from evaluation.production_latency_governor import SEMANTIC_KEYS


def run() -> dict:
    import openvino as ov  # type: ignore[import-not-found]

    from evaluation.closure_iteration6_latency import run as benchmark
    from packages.ocr import RapidOCRProvider

    original = RapidOCRProvider._load_backend
    core = ov.Core()
    executed = []

    def load(self):
        if self._backend is not None:
            return self._backend
        backend = original(self)
        model = core.read_model(backend.text_rec.session.session._model_path)
        compiled = core.compile_model(
            model,
            "CPU",
            {
                "PERFORMANCE_HINT": "LATENCY",
                "INFERENCE_PRECISION_HINT": "f32",
                "INFERENCE_NUM_THREADS": 8,
                "NUM_STREAMS": 1,
            },
        )
        executed.extend(compiled.get_property("EXECUTION_DEVICES"))

        def recognize(pixels):
            result = compiled([pixels])
            return [result[port] for port in compiled.outputs]

        backend.text_rec.session = recognize
        return backend

    RapidOCRProvider._load_backend = load
    try:
        result = benchmark(
            output_dir=OUT,
            output_name="openvino_cpu_screen.local.json",
            page_limit=1,
            repetitions=1,
        )
    finally:
        RapidOCRProvider._load_backend = original
    baseline = json.loads((OUT / "qualification.local.json").read_text())
    before = baseline["experiments"][0]["pages"][0]
    after = result["experiments"][0]["pages"][0]
    changed = [k for k in SEMANTIC_KEYS if before[k] != after[k]]
    report = {
        "name": "openvino_cpu_recognition",
        "version": ov.__version__,
        "available_devices": core.available_devices,
        "execution_devices": executed,
        "model_changed": False,
        "preprocessing_changed": False,
        "precision": "f32",
        "protected_semantics_identical": not changed,
        "changed_keys": changed,
        "pages": 1,
        "warm_repetitions": 0,
        "latency_qualified": False,
        "production_activated": False,
        "status": "REJECT_SEMANTIC_MISMATCH" if changed else "SCREEN_PASS_REQUIRES_QUALIFICATION",
        "screen_page_ms": after["stages"]["total_ms"],
        "scope": "ONE_PAGE_SEMANTIC_SCREEN_NOT_LATENCY_QUALIFICATION",
    }
    (OUT / "openvino_cpu_screen_result.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
