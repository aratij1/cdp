"""Non-semantic native timing and Windows CPU topology for bounded benchmarks."""

from __future__ import annotations

import ctypes
import struct
from collections import Counter
from time import perf_counter


def windows_cpu_sets() -> list[dict]:
    """Read documented variable-sized SYSTEM_CPU_SET_INFORMATION records."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel.GetSystemCpuSetInformation
    query.argtypes = [
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
        wintypes.HANDLE,
        wintypes.ULONG,
    ]
    query.restype = wintypes.BOOL
    size = wintypes.ULONG()
    query(None, 0, ctypes.byref(size), None, 0)
    if not size.value:
        raise OSError("CPU_SET_TOPOLOGY_UNAVAILABLE")
    buffer = ctypes.create_string_buffer(size.value)
    if not query(buffer, size, ctypes.byref(size), None, 0):
        raise OSError("CPU_SET_QUERY_FAILED")
    offset, result = 0, []
    while offset < size.value:
        length, kind = struct.unpack_from("<II", buffer.raw, offset)
        if length < 8 or offset + length > size.value:
            raise ValueError("CPU_SET_LAYOUT_UNSUPPORTED")
        if kind == 0 and length >= 32:
            result.append(
                {
                    "group": struct.unpack_from("<H", buffer.raw, offset + 12)[0],
                    "logical_cpu": buffer.raw[offset + 14],
                    "efficiency_class": buffer.raw[offset + 18],
                }
            )
        offset += length
    return result


def performance_cores(rows: list[dict]) -> list[int]:
    if not rows or any(r["group"] != 0 for r in rows):
        raise ValueError("SINGLE_CPU_GROUP_REQUIRED")
    classes = {r["efficiency_class"] for r in rows}
    if len(classes) < 2:
        raise ValueError("HETEROGENEOUS_CPU_NOT_DETECTED")
    return sorted(r["logical_cpu"] for r in rows if r["efficiency_class"] == max(classes))


class _TimedCallable:
    def __init__(self, original, owner, name):
        self.original, self.owner, self.name = original, owner, name

    def __getattr__(self, name):
        return getattr(self.original, name)

    def __call__(self, *args, **kwargs):
        start = perf_counter()
        result = self.original(*args, **kwargs)
        self.owner.elapsed[self.name] += (perf_counter() - start) * 1000
        self.owner.calls[self.name] += 1
        if args and hasattr(args[0], "shape"):
            self.owner.shapes.setdefault(self.name, set()).add(tuple(args[0].shape))
        if self.name == "ocr_global_resize_ms" and isinstance(result, tuple):
            self.owner.shapes.setdefault("ocr_processed_shape", set()).add(tuple(result[0].shape))
        return result


class NativeTrace:
    """Pass through the exact arguments/results; retain no image or text values."""

    def __init__(self, backend):
        self.reset()
        self._wrapped = []
        for owner, attr, name in (
            (backend, "load_img", "ocr_input_conversion_ms"),
            (backend, "preprocess", "ocr_global_resize_ms"),
            (backend, "get_crop_img_list", "ocr_crop_rotation_copy_ms"),
            (backend.text_det, "infer", "detector_inference_ms"),
            (backend.text_cls, "infer", "orientation_inference_ms"),
            (backend.text_rec, "session", "recognizer_inference_ms"),
            (backend.text_rec, "resize_norm_img", "recognizer_resize_normalize_ms"),
        ):
            original = getattr(owner, attr)
            self._wrapped.append((owner, attr, original, attr in vars(owner)))
            setattr(owner, attr, _TimedCallable(original, self, name))

    def restore(self):
        """Break bound-method wrapper cycles before destroying a benchmark worker."""
        for owner, attr, original, instance_owned in self._wrapped:
            if instance_owned:
                setattr(owner, attr, original)
            else:
                delattr(owner, attr)
        self._wrapped.clear()

    def reset(self):
        self.elapsed: Counter[str] = Counter()
        self.calls: Counter[str] = Counter()
        self.shapes: dict[str, set[tuple]] = {}

    def report(self):
        return {
            "elapsed_ms": dict(self.elapsed),
            "calls": dict(self.calls),
            "array_shapes": {k: sorted(v) for k, v in self.shapes.items()},
            "deskew": "NOT_REQUESTED_BY_RETAINED_PREPROCESSING",
            "timings_nested_in_ocr_ms": True,
        }
