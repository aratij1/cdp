"""Synthetic performance evidence must retain every protected semantic dimension."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from evaluation.production_latency_governor import SEMANTIC_KEYS, compare
from evaluation.production_latency_support import NativeTrace, performance_cores


def profile(p95):
    page = {k: "fixed" for k in SEMANTIC_KEYS}
    page.update(
        page_id="page",
        cache_hit=False,
        full_page_ocr_calls=1,
        memory_rss_bytes=100,
        stages={"total_ms": p95},
    )
    return {
        "scope": "SHADOW",
        "experiments": [
            {"mode": "WARM_STEADY_STATE", "pages": [deepcopy(page)], "latency": {"P95": p95}}
            for _ in range(3)
        ],
    }


@pytest.mark.parametrize("key", SEMANTIC_KEYS)
def test_each_semantic_dimension_is_protected(key):
    base, candidate = profile(8000), profile(4000)
    candidate["experiments"][2]["pages"][0][key] = "changed"
    result = compare(base, candidate)
    assert result["status"] == "REJECT" and "SEMANTIC_MISMATCH" in result["reasons"]


def test_complete_fresh_repetitions_required():
    base, candidate = profile(8000), profile(4000)
    assert compare(base, candidate)["status"] == "KEEP_ELIGIBLE_PENDING_SAFETY"
    candidate["experiments"].pop()
    assert "INSUFFICIENT_WARM_REPETITIONS" in compare(base, candidate)["reasons"]
    candidate = profile(4000)
    candidate["experiments"][0]["pages"] = []
    assert "INCOMPLETE_OR_DIFFERENT_COHORT" in compare(base, candidate)["reasons"]


def test_native_instrumentation_reuses_objects_and_preserves_arguments():
    calls, sentinel = [], object()

    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    backend = SimpleNamespace(
        load_img=original,
        preprocess=original,
        get_crop_img_list=original,
        text_det=SimpleNamespace(infer=original),
        text_cls=SimpleNamespace(infer=original),
        text_rec=SimpleNamespace(session=original, resize_norm_img=original),
    )
    trace = NativeTrace(backend)
    session = backend.text_rec.session
    for _ in range(3):
        assert backend.text_rec.session(sentinel, bounded=True) is sentinel
        assert backend.text_rec.session is session
    assert calls == [((sentinel,), {"bounded": True})] * 3
    assert trace.report()["calls"]["recognizer_inference_ms"] == 3
    trace.reset()
    assert not trace.report()["calls"]
    trace.restore()
    assert backend.text_rec.session is original


def test_affinity_requires_measured_heterogeneous_single_group():
    assert performance_cores(
        [
            {"group": 0, "logical_cpu": 0, "efficiency_class": 0},
            {"group": 0, "logical_cpu": 1, "efficiency_class": 1},
        ]
    ) == [1]
    with pytest.raises(ValueError):
        performance_cores([])


def test_fabricated_runtime_summary_cannot_pass():
    base, candidate = profile(8000), profile(8000)
    candidate["experiments"][0]["latency"]["P95"] = -1
    assert "P95_DOES_NOT_MATCH_PAGE_MEASUREMENTS" in compare(base, candidate)["reasons"]


def test_trace_restore_does_not_leave_bound_method_reference_cycle():
    import gc
    import weakref

    class Backend:
        def __init__(self):
            self.text_det = SimpleNamespace(infer=lambda x: x)
            self.text_cls = SimpleNamespace(infer=lambda x: x)
            self.text_rec = SimpleNamespace(session=lambda x: x, resize_norm_img=lambda x: x)

        def load_img(self, x):
            return x

        def preprocess(self, x):
            return x

        def get_crop_img_list(self, x):
            return x

    backend = Backend()
    reference = weakref.ref(backend)
    trace = NativeTrace(backend)
    trace.restore()
    assert "preprocess" not in vars(backend)
    del backend
    gc.collect()
    assert reference() is None
