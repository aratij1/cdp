from evaluation.production_promotion_report import generate_promotion_report


def test_current_phase4_report_fails_closed_without_holdout():
    report = generate_promotion_report(full_suite_passed=True)
    assert report["decision"] == "NEEDS_MORE_DATA"
    assert report["holdout_status"] == "NEEDS_MORE_DATA"
    assert report["synthetic_metrics_are_production_authority"] is False
    assert all(row["decision"] == "NEEDS_MORE_DATA" for row in report["route_decisions"])
    assert all(row["new_status"] == row["current_status"] for row in report["route_decisions"])
    assert report["execution_order"][7]["status"] == "NOT_RUN"
