"""Aggregate real check exits, JUnit counts and strict identity canaries."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from evaluation.strict_identity_cached_replay import _canaries
from packages.document_routing import MultiSignalRouter

ROOT = Path(__file__).resolve().parents[1]


def run() -> dict:
    checks = json.loads(
        (ROOT / ".test-tmp/production-validation-checks.json").read_text("utf-8-sig")
    )
    suites = ET.parse(ROOT / ".test-tmp/production-full.xml").getroot().findall("testsuite")
    totals = {
        key: sum(int(s.get(key, "0")) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    if not totals["tests"]:
        raise ValueError("EMPTY_TEST_RUN")
    canaries = _canaries(MultiSignalRouter.load())
    canary_pass = sum(
        r["ub04_rejected"] and r["ub04_localization_authorizations"] == 0 for r in canaries
    )
    engineering = json.loads((ROOT / "docs/closure/production_engineering_replay.json").read_text())
    release = json.loads((ROOT / "docs/closure/production_release_readiness.json").read_text())
    required = {
        "full_suite",
        "ruff_changed_scope",
        "mypy_changed_scope",
        "architecture",
        "compose_config",
        "diff_check",
    }
    valid = (
        {c["name"] for c in checks} == required
        and all(c["exit_code"] == 0 for c in checks)
        and not totals["failures"]
        and not totals["errors"]
        and canary_pass == 3
        and engineering["operational_replay"]["OTHER_canonical_localization"] == 0
        and engineering["operational_replay"]["UNKNOWN_canonical_localization"] == 0
        and release["blind_handoff_unchanged"]
    )
    result = {
        "checks": checks,
        "full_suite": {
            **totals,
            "passed": totals["tests"] - totals["skipped"] - totals["failures"] - totals["errors"],
        },
        "baseline_signature": {"passed": 1542, "skipped": 6, "failures": 0, "errors": 0},
        "new_semantic_regressions": 0 if valid else None,
        "false_ub04_canaries_passed": canary_pass,
        "OTHER_canonical_localization": engineering["operational_replay"][
            "OTHER_canonical_localization"
        ],
        "UNKNOWN_canonical_localization": engineering["operational_replay"][
            "UNKNOWN_canonical_localization"
        ],
        "blind_handoff_unchanged": release["blind_handoff_unchanged"],
        "production_authority_activated": False,
        "release_qualification": "NOT_EVALUABLE_WITHOUT_TRUSTED_TRUTH",
        "all_required_checks_passed": valid,
        "typing_scope": "CHANGED_MODULES_FOLLOW_IMPORTS_SKIP_NOT_REPOSITORY_WIDE",
    }
    (ROOT / "docs/closure/production_validation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result


if __name__ == "__main__":
    run()
