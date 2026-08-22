import yaml
from evaluation.calculate_total_cost import calculate

def test_total_cost_includes_processing_compute_platform_and_hitl():
    config=yaml.safe_load(open("config/cost_model_v1.yaml",encoding="utf-8"))
    result=calculate(config)["scenarios"]["current"]
    assert result["pre_hitl_cost_per_page_usd"] > 0
    assert result["hitl_cost_per_page_usd"] > 0
    assert result["total_cost_per_page_usd"] == result["pre_hitl_cost_per_page_usd"] + result["hitl_cost_per_page_usd"]
    assert result["hitl_share_of_total"] > .99

def test_review_reduction_lowers_total_without_hiding_processing_cost():
    config=yaml.safe_load(open("config/cost_model_v1.yaml",encoding="utf-8"))
    scenarios=calculate(config)["scenarios"]
    assert scenarios["target_5_percent_review"]["total_cost_per_page_usd"] < scenarios["current"]["total_cost_per_page_usd"]
    assert scenarios["target_5_percent_review"]["pre_hitl_cost_per_page_usd"] == scenarios["current"]["pre_hitl_cost_per_page_usd"]
