from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.reference_data import snapshot_readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/reference_enrichment.yaml"))
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    report = snapshot_readiness(args.config)
    print(json.dumps(report, indent=2))
    return int(args.require_ready and not report["ready"])


if __name__ == "__main__":
    raise SystemExit(main())
