from evaluation.run_local_load_and_cost import _percentile

def test_percentiles_are_deterministic_and_bounded():
    values = [40, 10, 30, 20, 50]
    assert _percentile(values, .5) == 30
    assert _percentile(values, .95) == 40
    assert _percentile(values, .99) == 40
