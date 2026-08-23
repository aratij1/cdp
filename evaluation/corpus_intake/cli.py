"""CLI for controlled Phase 7A.12 intake. It never discovers assets implicitly."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import CorpusIntakeBatch
from .workflow import run_phase7a12


def main() -> None:
    parser = argparse.ArgumentParser(description="Run governed Phase 7A.12 corpus intake")
    parser.add_argument("--batch", type=Path,
                        help="Machine-readable batch containing only authorized supplied records")
    parser.add_argument("--asset-root", type=Path,
                        help="Controlled local root; asset_uri values must be relative to it")
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation_results/phase7a12"))
    parser.add_argument("--loso-cases", type=Path,
                        help="Optional one-to-one existing-runtime evidence cases; no model is trained")
    parser.add_argument("--reviewer-id", action="append", default=[],
                        help="Reviewer pool used only to create blind task assignments")
    parser.add_argument("--write-schema", type=Path,
                        help="Write the current JSON Schema and exit")
    args = parser.parse_args()
    if args.write_schema:
        args.write_schema.parent.mkdir(parents=True, exist_ok=True)
        args.write_schema.write_text(
            json.dumps(CorpusIntakeBatch.model_json_schema(), indent=2), "utf-8"
        )
        return
    if args.batch is None:
        parser.error("--batch is required unless --write-schema is used")
    batch = CorpusIntakeBatch.model_validate_json(args.batch.read_text("utf-8"))
    loso_cases = (
        json.loads(args.loso_cases.read_text("utf-8")) if args.loso_cases else None
    )
    root = Path(__file__).resolve().parents[2]
    result = run_phase7a12(
        batch, root=root, output_dir=args.output_dir, asset_root=args.asset_root,
        reviewer_ids=tuple(args.reviewer_id), loso_cases=loso_cases,
    )
    print(json.dumps(result["decision"], indent=2))


if __name__ == "__main__":
    main()
