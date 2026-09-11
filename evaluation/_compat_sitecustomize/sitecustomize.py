"""Environment-only compatibility shim for running local OCR benchmarks.

`paddleocr==2.7.0.3` (the last release exposing the legacy constructor
kwargs this codebase's `PaddleOCRTextExtractor` uses -- see
workers/page_detection/text_extraction.py) transitively imports `imgaug`,
which reads `numpy.sctypes`, removed in NumPy 2.0. This directory is added
to `PYTHONPATH` only for offline evaluation subprocess runs (see
evaluation/offline_pipeline.py); it is never imported by the production
Docker image or by any worker/package module. It does not change any
extraction, validation, or decision logic -- it only restores a removed
NumPy attribute so the legacy import path does not crash.
"""

import numpy as np

if not hasattr(np, "sctypes"):
    np.sctypes = {
        "float": [np.float16, np.float32, np.float64],
        "int": [np.int8, np.int16, np.int32, np.int64],
        "uint": [np.uint8, np.uint16, np.uint32, np.uint64],
        "complex": [np.complex64, np.complex128],
        "others": [bool, object, bytes, str, np.void],
    }
