import json
from pathlib import Path

import pytest

from evaluation.production_readiness import (
    freeze_evidence_frontier_v2,
    verify_frontier,
    write_claim_dispositions,
)


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "evaluation_results" / "claim_stp_recovery" / "baseline"


def test_frontier_v2_is_immutable_and_tamper_evident(tmp_path):
    output = tmp_path / "evidence_frontier_v2"
    manifest = freeze_evidence_frontier_v2(source=SOURCE, output=output)
    assert manifest["baseline_id"] == "EVIDENCE_FRONTIER_V2"
    assert verify_frontier(output / "manifest.json")["status"] == "FROZEN"
    with pytest.raises(FileExistsError):
        freeze_evidence_frontier_v2(source=SOURCE, output=output)
    metrics = output / "metrics.json"
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    payload["claim_stp_rate"] = 1
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact integrity"):
        verify_frontier(output / "manifest.json")


def test_claim_disposition_csv_has_one_complete_row_per_claim(tmp_path):
    output = tmp_path / "evidence_frontier_v2"
    freeze_evidence_frontier_v2(source=SOURCE, output=output)
    rows = write_claim_dispositions(
        frontier=output, output=tmp_path / "claim_dispositions.csv",
    )
    assert len(rows) == 120
    assert sum(row["STP_status"] == "STP" for row in rows) == 96
    assert sum(row["false_accept_count"] for row in rows) == 0
    assert all(row["claim_policy_version"] == "claim-decision-v1" for row in rows)
