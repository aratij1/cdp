"""Generate machine-readable fail-closed qualification evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.production_qualification import qualify, write_qualification


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=Path("config/releases/cdp-vnext-candidate.yaml"))
    parser.add_argument("--frozen", type=Path, default=Path("config/releases/extraction-v2.yaml"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/vnext_qualification/qualification.json"))
    args = parser.parse_args()
    report = qualify(args.candidate, args.frozen)
    write_qualification(report, args.output)
    print(json.dumps(report.as_dict(), indent=2))
    return 0 if report.decision == "PROMOTABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
