"""Evaluate deterministic claim-total E6 authority without changing runtime."""

from __future__ import annotations

import json

from evaluation.phase8_10b_total_charge_e6 import run


def main() -> int:
    result = run(write_outputs=False, candidate_financial_authority=True)
    result["authority"] = "EVALUATION_ONLY"
    result["runtime_changed"] = False
    print(json.dumps(result, indent=2))
    return 0 if result["decision"] == "PROMOTE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
