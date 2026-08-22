"""Technology-neutral LOSO evaluator for already-produced hierarchical observations."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from packages.document_taxonomy.policy import RoutingOutcome, summarize_outcomes


def evaluate(records: list[dict]) -> dict:
    by_source: dict[str, list[RoutingOutcome]] = defaultdict(list)
    for row in records:
        by_source[row["source_family"]].append(RoutingOutcome.model_validate(row["outcome"]))
    source_metrics = {source: summarize_outcomes(tuple(outcomes)) for source, outcomes in sorted(by_source.items())}
    metric_names = next(iter(source_metrics.values()), {}).keys()
    aggregate = {}
    for metric in metric_names:
        values = sorted(result[metric] for result in source_metrics.values())
        aggregate[metric] = {"worst_source": min(values), "median_source": values[len(values)//2],
                             "best_source": max(values)}
    return {"split_policy": "LEAVE_ONE_SOURCE_FAMILY_OUT", "source_metrics": source_metrics,
            "aggregate": aggregate}


def main(input_path: str, output_path: str) -> None:
    records = json.loads(Path(input_path).read_text("utf-8"))
    Path(output_path).write_text(json.dumps(evaluate(records), indent=2), "utf-8")
