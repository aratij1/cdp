from evaluation.router_v4_generalization import evaluate


def _row(partition,truth,predicted=None,degradation="clean",latency=100):
    return {"partition":partition,"truth":truth,"predicted":predicted or truth,
        "source_family":partition,"renderer_family":"independent","degradation_family":degradation,
        "routing_latency_ms":latency,"ocr_calls_page":1}


def test_generalization_score_is_worst_source_not_average():
    rows=[]
    for p in ("ROUTING_DEV_V4_A_STANDARD","ROUTING_DEV_V4_B_STANDARD_ALTERNATE"):
        rows += [_row(p,"CMS1500"),_row(p,"UB04")]
    rows += [_row("ROUTING_DEV_V4_C_CUSTOM_NEGATIVE","UNKNOWN_STRUCTURED"),
             _row("ROUTING_DEV_V4_C_CUSTOM_NEGATIVE","NON_CLAIM")]
    rows += [_row("ROUTING_DEV_V4_D_DEGRADATION","CMS1500","UNKNOWN_UNSTRUCTURED","fax"),
             _row("ROUTING_DEV_V4_D_DEGRADATION","UB04","UNKNOWN_UNSTRUCTURED","fax")]
    report=evaluate(rows)
    assert report["ROUTER_GENERALIZATION_SCORE"]==0
    assert report["promotion_gate"]["v4_d_pass"] is False
    assert report["promotion_gate"]["all_development_gates_pass"] is False


def test_rejects_missing_source_partition():
    try: evaluate([_row("ROUTING_DEV_V4_A_STANDARD","CMS1500")])
    except ValueError as error: assert "missing V4 partitions" in str(error)
    else: raise AssertionError("missing partitions accepted")
