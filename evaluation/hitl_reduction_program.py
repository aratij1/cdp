from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from packages.hitl_reduction import GovernedFieldLabel, HITLReductionInput, HITLReductionService


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write_outputs(output: Path, results: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in results.items():
        (output / f"{name}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare and score leakage-resistant HITL reduction evidence."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    score = subparsers.add_parser("score")
    score.add_argument("--sealed", type=Path, required=True)
    score.add_argument("--labels", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    service = HITLReductionService()
    if args.command == "prepare":
        result = service.prepare(HITLReductionInput.model_validate(_read_json(args.input)))
    else:
        labels = [GovernedFieldLabel.model_validate(item) for item in _read_jsonl(args.labels)]
        result = service.score(_read_json(args.sealed), labels)
    _write_outputs(args.output, result)


if __name__ == "__main__":
    main()
