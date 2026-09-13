"""PHI-free runtime dependency preflight for qualification routes."""
from __future__ import annotations
import hashlib, importlib.util, json, os, sys
from pathlib import Path

def _check(name: str, required: bool, available: bool, detail: str) -> dict:
    return {"name": name, "status": "AVAILABLE" if available else ("MISSING" if required else "NOT_REQUIRED"), "detail": detail}

def _layoutlm_check() -> dict:
    from workers.unstructured_extraction.layoutlmv3_adapter import LayoutLMv3Adapter
    configured = os.environ.get("CDP_LAYOUTLMV3_CHECKPOINT")
    adapter = LayoutLMv3Adapter(configured)
    checkpoint = getattr(adapter, "_checkpoint_path", None)
    if not checkpoint:
        return _check("unstructured-layoutlmv3", True, False, "runtime adapter has no configured checkpoint")
    path = Path(checkpoint).expanduser()
    readable = path.exists() and path.is_dir() and any(path.iterdir())
    return _check("unstructured-layoutlmv3", True, readable, "configured checkpoint contract")

def run(candidate_sha: str | None = None) -> dict:
    cache = Path(os.environ.get("CDP_MODEL_CACHE", Path.home() / ".cache" / "cdp-models")).expanduser()
    rows = [_check("rapidocr-onnxruntime", True, importlib.util.find_spec("rapidocr_onnxruntime") is not None, "python package"), _check("paddleocr", False, importlib.util.find_spec("paddleocr") is not None, "optional route"), _layoutlm_check(), _check("unstructured-table-transformer", False, False, "route not required for CMS cohort"), _check("trocr", False, importlib.util.find_spec("transformers") is not None, "optional handwriting route")]
    payload = {"candidate_sha": candidate_sha, "model_cache": {"path_hash": hashlib.sha256(str(cache).encode()).hexdigest(), "exists": cache.exists()}, "dependencies": rows}
    payload["status"] = "PASS" if all(r["status"] in {"AVAILABLE", "NOT_REQUIRED"} for r in rows) else "FAIL"
    return payload

def main() -> int:
    payload = run(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1
if __name__ == "__main__": raise SystemExit(main())