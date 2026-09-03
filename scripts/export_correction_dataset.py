"""Create deterministic, source-disjoint offline-learning correction sets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.retraining import export_correction_dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="append-only corrections JSONL")
    parser.add_argument("output", type=Path, help="output directory")
    parser.add_argument("--seed", default="correction-dataset-v1")
    args = parser.parse_args()
    manifest = export_correction_dataset(args.source, args.output, seed=args.seed)
    print(json.dumps(manifest.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
