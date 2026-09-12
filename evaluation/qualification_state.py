"""Private, checkout-independent state paths. No implicit repository fallback."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

STATE_ENV = "CDP_QUALIFICATION_STATE_ROOT"
DEV_ENV = "CDP_QUALIFICATION_ALLOW_LOCAL_STATE"


class StateUnavailable(ValueError):
    pass


def state_root() -> Path | None:
    value = os.environ.get(STATE_ENV)
    if not value:
        if os.environ.get(DEV_ENV) == "1": return None
        raise StateUnavailable("GOVERNED_STATE_ROOT_NOT_CONFIGURED")
    root = Path(value)
    if not root.is_absolute() or not root.is_dir():
        raise StateUnavailable("GOVERNED_STATE_ROOT_NOT_MOUNTED")
    root = root.resolve()
    if any((parent/".git").exists() for parent in (root, *root.parents)):
        raise StateUnavailable("GOVERNED_STATE_ROOT_MUST_BE_OUTSIDE_GIT")
    return root


def status() -> dict:
    try:
        root = state_root()
    except StateUnavailable as exc:
        return {"status":"UNAVAILABLE", "reason":str(exc), "counters":"UNKNOWN_NOT_ZERO"}
    return {"status":"MOUNTED" if root else "EXPLICIT_DEVELOPMENT_FALLBACK",
            "root_id":hashlib.sha256(str(root).encode()).hexdigest() if root else None,
            "path_disclosed":False}


def category(name: str) -> str:
    if "membership" in name or "lineage" in name: return "membership"
    if "registry" in name or "reviewer_authority" in name: return "reviewers"
    if "adjudicat" in name: return "adjudication"
    if "truth" in name: return "truth"
    if name.startswith(("deployment", "pricing", "measured_workload")) or name == "jobs": return "deployment"
    return "reviews"


def mapped(path: Path) -> Path:
    root = state_root()
    if root is None: return path
    absolute = path.resolve()
    if absolute.is_relative_to(root): return absolute
    parts = path.as_posix().split("/")
    if "qualification_closure" in parts:
        suffix = parts[parts.index("qualification_closure")+1:]
        if not suffix: return root / "reviews"
        result = root / category(suffix[0])
        for part in suffix: result /= part
    elif path.name in {"reviewer_registry.yaml", "deployment_control.yaml", "150_cohort_missing_membership.csv"}:
        result = root/category(path.name)/path.name
    elif "evaluation_results" in parts:
        result = root/"reviews"/"legacy"
        for part in parts[parts.index("evaluation_results")+1:]: result /= part
    else:
        result = root/category(path.name)/path.name
    if not result.resolve().is_relative_to(root): raise StateUnavailable("STATE_PATH_ESCAPE")
    return result


def ensure_parent(path: Path) -> Path:
    path = mapped(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def immutable_json(path: Path, payload: dict) -> None:
    path = ensure_parent(path)
    data = json.dumps(payload,sort_keys=True,indent=2)+"\n"
    try:
        with path.open("x",encoding="utf-8") as stream: stream.write(data)
    except FileExistsError:
        if json.loads(path.read_text(encoding="utf-8")) != payload:
            raise ValueError("IMMUTABLE_GOVERNED_STATE_CHANGED") from None


def initialize_layout() -> Path:
    root = state_root()
    if root is None: raise StateUnavailable("EXTERNAL_STATE_REQUIRED")
    for name in ("membership", "reviewers", "reviews", "adjudication", "truth", "deployment", "engineering"):
        (root/name).mkdir(exist_ok=True)
    return root
