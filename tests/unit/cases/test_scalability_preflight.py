from pathlib import Path
from evaluation.validate_scalability import validate

def test_required_load_tiers_metrics_and_worker_entrypoints_are_valid():
    report = validate(Path("."))
    assert report["status"] == "PASS", report["errors"]
    assert report["load_tiers"] == [1000, 10000, 50000]
    assert len(report["worker_pools"]) >= 7
    assert report["cluster_load_test_executed"] is False
