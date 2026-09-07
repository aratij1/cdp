"""Append source-only box-67 proposals to the sealed frozen-30 candidate pools."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict

from evaluation.governed_30_candidate_coverage import ranks, unique_values
from evaluation.governed_30_reference import ROOT, digest
from evaluation.governed_30_scorecard import metric
from workers.field_candidates.box67_recovery import SourceBox67Anchor, generate_box67
from workers.page_detection.text_extraction import TextLine


def build() -> dict:
    public = ROOT / "docs/closure/box67_candidate_recovery"
    private = ROOT / "evaluation_results/governed_30_box67"
    private.mkdir(parents=True, exist_ok=True)
    seal = json.loads((public / "input_seal.json").read_text())
    for relative, expected in seal.items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"Frozen input changed: {relative}")
    anchors = {}
    for row in json.loads((public / "source_anchors.json").read_text()):
        row["bbox"] = tuple(row["bbox"])
        anchors[row["image_sha256"]] = SourceBox67Anchor(**row)
    capture = ROOT / "evaluation_results/governed_30_candidate_coverage"
    pages = json.loads((capture / "primary_capture_input.local.json").read_text())["pages"]
    proposals = defaultdict(list)
    page_audit = []
    # Generate for every source page before the evaluator reads any reference values.
    for page in pages:
        alias, number = page["claim_alias"], page["page_number"]
        image_path = ROOT / page["image_path"]
        if digest(image_path) != page["image_sha256"]:
            raise ValueError("Source image changed")
        token_path = capture / "primary_tokens" / f"{alias}_P{number:03d}.local.json"
        token_data = json.loads(token_path.read_text())
        tokens = [TextLine(**t) for t in token_data["tokens"]]
        candidates = generate_box67(
            tokens,
            image_bytes=image_path.read_bytes(),
            token_image_sha256=token_data["image_sha256"],
            anchor=anchors.get(page["image_sha256"]),
        )
        for candidate in candidates:
            proposals[alias].append({**asdict(candidate), "page_number": number})
        page_audit.append(
            {
                "claim_alias": alias,
                "page_number": number,
                "source_sha256": page["image_sha256"],
                "anchored": page["image_sha256"] in anchors,
                "new_candidates": len(candidates),
            }
        )
    baseline = json.loads(
        (
            ROOT / "evaluation_results/governed_30_root_collapse/root_collapse_records.local.json"
        ).read_text()
    )
    assert len(baseline) == 118 and len({r["claim_alias"] for r in baseline}) == 30
    records = []
    for row in baseline:
        before = row["experiments"]["combined"]
        additions = proposals[row["claim_alias"]] if row["field"] == "principal_diagnosis" else []
        values = unique_values(row["field"], before["values"] + [c["value"] for c in additions])
        before_recall = ranks(row["field"], row["reference_value"], before["values"])
        assert before_recall == before["recall"]
        after_recall = ranks(row["field"], row["reference_value"], values)
        assert all(not before_recall[k] or after_recall[k] for k in before_recall)
        records.append(
            {
                "claim_alias": row["claim_alias"],
                "field": row["field"],
                "critical": row["critical"],
                "before": before_recall,
                "after": after_recall,
                "candidate_evidence": additions,
                "before_values": before["values"],
                "after_values": values,
            }
        )
    metrics = {}
    for label, subset in (("all", records), ("critical", [r for r in records if r["critical"]])):
        metrics[label] = {
            stage: {
                f"R@{k}": metric(sum(r[stage][k] for r in subset), len(subset))
                for k in ("1", "3", "5")
            }
            for stage in ("before", "after")
        }
    assert metrics["all"]["before"]["R@5"]["numerator"] == 21
    assert metrics["critical"]["before"]["R@5"]["numerator"] == 18
    deltas = {
        label: {
            "recovered": values["after"]["R@5"]["numerator"] - values["before"]["R@5"]["numerator"],
            "percentage_points": values["after"]["R@5"]["percentage"]
            - values["before"]["R@5"]["percentage"],
        }
        for label, values in metrics.items()
    }
    summary = {
        "scope": "FROZEN_30_REVIEW_ONLY_CANDIDATE_REPLAY",
        "claims": 30,
        "pages": len(pages),
        "metrics": metrics,
        "recall_at_5_delta": deltas,
        "new_candidates": sum(len(v) for v in proposals.values()),
        "new_ocr_calls": 0,
        "ranking": "APPEND_ONLY_EXISTING_ORDER_PRESERVED",
        "source_anchor_scope": "SIX_HASH_BOUND_MANUAL_SOURCE_REGIONS_NOT_GENERAL_DETECTOR",
        "reference_used_by_generator": False,
        "production_changes": False,
        "recovered_fields": [
            {"claim_alias": r["claim_alias"], "field": r["field"]}
            for r in records
            if r["after"]["5"] and not r["before"]["5"]
        ],
        "regressions": 0,
        "anchor_sha256": digest(public / "source_anchors.json"),
        "input_seal_sha256": digest(public / "input_seal.json"),
    }
    for name, value in (("records.local.json", records), ("page_audit.local.json", page_audit)):
        (private / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf8")
    summary["private_records_sha256"] = digest(private / "records.local.json")
    (public / "scorecard.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf8")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    build()
