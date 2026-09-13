"""Route-aware dependency checks; checkpoint presence never proves inference."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

from workers.unstructured_extraction.layoutlmv3_adapter import LayoutLMv3Adapter


def run(candidate_sha: str | None = None, *, route_plan: dict[str, Any] | None = None) -> dict:
    pages = (route_plan or {}).get("pages", [])
    standard_only = bool(pages) and all(
        page.get("identity_verified") is True
        and page.get("registration_accepted") is True
        and page.get("canonical_entered") is True
        and page.get("fallback_requested") is False
        for page in pages
    )
    if standard_only:
        layout_status = "NOT_REQUIRED_FOR_CMS_STANDARD_ROUTE"
    elif not pages:
        layout_status = "ROUTE_PLAN_REQUIRED"
    elif not LayoutLMv3Adapter.inference_implemented:
        layout_status = "FALLBACK_RUNTIME_NOT_IMPLEMENTED"
    else:
        # A future implementation must add an actual inference capability check.
        layout_status = "IMPLEMENTATION_PREFLIGHT_REQUIRED"
    rows = [
        {"name": "rapidocr-onnxruntime", "required": True,
         "status": "AVAILABLE" if importlib.util.find_spec("rapidocr_onnxruntime") else "MISSING"},
        {"name": "unstructured-layoutlmv3", "required": False,
         "status": layout_status,
         "inference_implemented": LayoutLMv3Adapter.inference_implemented},
    ]
    return {"candidate_sha": candidate_sha, "scope": "ENGINEERING_ROUTE_PREFLIGHT",
            "dependencies": rows,
            "standard_route_dependencies_available": rows[0]["status"] == "AVAILABLE",
            "status": "PASS" if rows[0]["status"] == "AVAILABLE" and standard_only else "FAIL"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_sha", nargs="?")
    parser.add_argument("--route-plan", type=Path)
    args = parser.parse_args()
    plan = json.loads(args.route_plan.read_text()) if args.route_plan else None
    payload = run(args.candidate_sha, route_plan=plan)
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
